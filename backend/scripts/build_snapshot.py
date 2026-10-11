"""Acquire genuine small-area OSM snapshots, or import an authorized OSM JSON/XML extract.
Run: python -m backend.scripts.build_snapshot --help
No automatic retries, no synthetic records, atomic output only after all categories succeed.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import requests
from backend import osm_service as osm
from backend.local_facilities import TYPES, validate_snapshot


def xml_elements(path):
    """OSM XML extracts must include referenced nodes to derive real area centers."""
    root = ET.parse(path).getroot()
    nodes = {int(n.attrib['id']): (float(n.attrib['lat']), float(n.attrib['lon'])) for n in root.findall('node')}
    ways = {int(w.attrib['id']): [int(n.attrib['ref']) for n in w.findall('nd')] for w in root.findall('way')}
    elements = []
    for item in root:
        if item.tag not in ('node', 'way', 'relation'):
            continue
        tags = {tag.attrib['k']: tag.attrib['v'] for tag in item.findall('tag')}
        if tags.get('amenity') not in osm.AMENITY_TAGS.values():
            continue
        element = {'type': item.tag, 'id': int(item.attrib['id']), 'tags': tags}
        if item.tag == 'node':
            element.update(lat=float(item.attrib['lat']), lon=float(item.attrib['lon']))
        else:
            if item.tag == 'way':
                refs = ways[element['id']]
            else:
                members = item.findall('member')
                if any(m.attrib['type'] not in ('node', 'way') for m in members):
                    raise ValueError('Facility relation has nested members; supply a complete Overpass JSON extract instead.')
                refs = []
                for member in members:
                    ref = int(member.attrib['ref'])
                    refs.extend([ref] if member.attrib['type'] == 'node' else ways[ref])
            points = [nodes[ref] for ref in refs]
            if not points:
                raise ValueError('Facility area has no geometry.')
            # Same representative convention as Overpass out center: bbox midpoint, not entrance.
            element['center'] = {'lat': (min(p[0] for p in points)+max(p[0] for p in points))/2,
                                 'lon': (min(p[1] for p in points)+max(p[1] for p in points))/2}
        elements.append(element)
    return elements


def pbf_elements(path, bbox):
    """Optional pyosmium importer; all OSM IDs/tags originate in the real regional extract."""
    import osmium
    west, south, east, north = bbox
    elements, used = [], set()

    def append(kind, object_id, tags, points):
        if tags.get('amenity') not in osm.AMENITY_TAGS.values() or not points:
            return
        lat = (min(p[0] for p in points)+max(p[0] for p in points))/2
        lon = (min(p[1] for p in points)+max(p[1] for p in points))/2
        if not (south <= lat <= north and west <= lon <= east):
            return
        key = (kind, object_id)
        if key in used:
            return
        used.add(key)
        element = {'type':kind,'id':object_id,'tags':tags}
        if kind == 'node': element.update(lat=lat, lon=lon)
        else: element['center'] = {'lat':lat, 'lon':lon}
        elements.append(element)

    class Handler(osmium.SimpleHandler):
        def node(self, node):
            if node.tags.get('amenity') in osm.AMENITY_TAGS.values() and node.location.valid():
                append('node',node.id,dict(node.tags),[(node.location.lat,node.location.lon)])
        def way(self, way):
            if way.tags.get('amenity') not in osm.AMENITY_TAGS.values(): return
            points = [(n.lat,n.lon) for n in way.nodes if n.location.valid()]
            if len(points) != len(way.nodes):
                raise ValueError('Facility way has missing node locations.')
            append('way',way.id,dict(way.tags),points)
        def area(self, area):
            if area.from_way() or area.tags.get('amenity') not in osm.AMENITY_TAGS.values(): return
            points = [(n.lat,n.lon) for ring in area.outer_rings() for n in ring if n.location.valid()]
            append('relation',area.orig_id(),dict(area.tags),points)
    Handler().apply_file(str(path),locations=True,idx='flex_mem')
    return elements


def build(args):
    west, south, east, north = args.bbox
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError('Invalid bbox (west south east north).')
    if (east-west)*(north-south) > .01 and not args.input:
        raise ValueError('Live snapshots must be small (at most .01 square degrees). Use an authorized extract for larger areas.')
    raw, elements, timestamps = [], [], []
    if args.input:
        if not args.source_url or not args.data_timestamp:
            raise ValueError('Extract imports require --source-url and --data-timestamp; bbox must describe verified complete extract coverage.')
        path = Path(args.input)
        if path.suffix == '.pbf':
            import osmium
            reader = osmium.io.Reader(str(path))
            embedded_timestamp = reader.header().get('osmosis_replication_timestamp')
            reader.close()
            if embedded_timestamp and embedded_timestamp != args.data_timestamp:
                raise ValueError('Declared data timestamp does not match PBF header.')
            elements = pbf_elements(path, args.bbox)
            # Stream checksumming avoids copying a regional extract into the JSON archive.
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024*1024), b''): digest.update(chunk)
            raw.append(json.dumps({'original_extract':path.name,'sha256':digest.hexdigest(),'elements':elements}).encode())
        else:
            raw.append(path.read_bytes())
        if path.suffix == '.pbf':
            pass
        elif path.suffix in ('.osm', '.xml'):
            elements = xml_elements(path)
        else:
            data = json.loads(raw[0])
            if data.get('remark') or not isinstance(data.get('elements'), list):
                raise ValueError('Expected complete Overpass JSON with elements, not a failed/partial response.')
            elements = data['elements']
        source = {'kind':'osm_extract','url':args.source_url}
        timestamps.append(args.data_timestamp)
    else:
        endpoint = osm._endpoints()[0]
        source = {'kind':'overpass','url':f'https://{urlsplit(endpoint).hostname}/api/interpreter'}
        for index, (category, tag) in enumerate(osm.AMENITY_TAGS.items()):
            if index: time.sleep(2)
            output = 'body' if tag == 'waste_basket' else 'center'
            query = f'[out:json][timeout:25];{osm._selector(tag)}["amenity"="{tag}"]({south},{west},{north},{east});out {output};'
            started = time.monotonic()
            response = requests.post(endpoint, data={'data':query}, timeout=(3,100),
                headers={'User-Agent':os.getenv('OVERPASS_USER_AGENT','ReRoute-HackRU/1.0 (environmental walking navigation)'), 'Accept':'application/json'})
            print(f'{category}: host={urlsplit(endpoint).hostname} HTTP={response.status_code} elapsed={time.monotonic()-started:.2f}s query={query}', flush=True)
            if response.status_code != 200:
                raise ValueError(f'{category} download failed with HTTP {response.status_code}; stopped without writing snapshot.')
            data = response.json()
            if data.get('remark') or not isinstance(data.get('elements'),list):
                raise ValueError('Incomplete/invalid upstream response; no snapshot written.')
            if any(e.get('tags',{}).get('amenity') != tag for e in data['elements']):
                raise ValueError('Upstream category mismatch.')
            raw.append(response.content)
            elements.extend(data['elements'])
            if data.get('osm3s',{}).get('timestamp_osm_base'):
                timestamps.append(data['osm3s']['timestamp_osm_base'])
    parsed = osm._parse_resources({'elements':elements})
    expected = [e for e in elements if e.get('tags',{}).get('amenity') in osm.AMENITY_TAGS.values()]
    if len(parsed) != len({(e.get('type'), e.get('id')) for e in expected}):
        raise ValueError('Some facilities have invalid geometry/identity; refusing incomplete import.')
    # Area centers can lie outside the query bbox; retain only coordinates within declared coverage.
    parsed = [f for f in parsed if south <= f['latitude'] <= north and west <= f['longitude'] <= east]
    center = getattr(args, 'center', None)
    radius_meters = getattr(args, 'radius_meters', None)
    if center is not None:
        parsed = [f for f in parsed if osm._distance(center[0], center[1], f['latitude'], f['longitude']) <= radius_meters]
    source['extract_sha256'] = digest.hexdigest() if args.input and Path(args.input).suffix == '.pbf' else None
    source['sha256'] = hashlib.sha256(b'\n'.join(raw)).hexdigest()
    snapshot = {'schema_version':1,'name':args.name,'bbox':args.bbox,'categories':list(TYPES),
                'retrieved_at':datetime.now(timezone.utc).isoformat(), 'data_timestamp':min(timestamps) if timestamps else None,
                'source':source,'license':'ODbL-1.0','attribution':'© OpenStreetMap contributors',
                'warnings':['OSM coverage, public access, opening hours and area entrances are not guaranteed.'],
                'facilities':parsed}
    if center is not None:
        snapshot['coverage'] = {'type':'circle', 'center':{'latitude':center[0], 'longitude':center[1]},
                                'radius_meters':radius_meters, 'approximate_center':True}
        snapshot['center'] = snapshot['coverage']['center']
        snapshot['radius_meters'] = radius_meters
    snapshot['record_count'] = len(parsed)
    snapshot['counts'] = {category:sum(f['type'] == category for f in parsed) for category in TYPES}
    snapshot['freshness'] = {'data_timestamp':snapshot['data_timestamp'], 'retrieved_at':snapshot['retrieved_at']}
    validate_snapshot(snapshot)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    archive = output.with_suffix('.source.json.gz')
    archive_tmp = archive.with_suffix('.tmp')
    with gzip.open(archive_tmp,'wt',encoding='utf-8') as handle:
        json.dump({'source':source,'bbox':args.bbox,'retrieved_at':snapshot['retrieved_at'],
                   'downloaded_payloads':[chunk.decode('utf-8') for chunk in raw]},handle)
    archive_tmp.replace(archive)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot,indent=2,ensure_ascii=False)+'\n')
    temporary.replace(output)
    print(json.dumps({'snapshot':str(output),'source_archive':str(archive),
                      'counts':{category:sum(f['type']==category for f in parsed) for category in TYPES},
                      'bbox':args.bbox,'retrieved_at':snapshot['retrieved_at']},indent=2))
    return snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bbox',type=float,nargs=4,required=True,metavar=('WEST','SOUTH','EAST','NORTH'))
    parser.add_argument('--name',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--input',help='Complete, trusted OSM .osm/.xml/.pbf or Overpass JSON extract (all three categories).')
    parser.add_argument('--source-url',help='Original authorized HTTPS OSM extract download URL.')
    parser.add_argument('--data-timestamp',help='ISO timestamp with timezone for extract contents.')
    args=parser.parse_args()
    try: build(args)
    except (ValueError,KeyError,TypeError,OSError,ImportError,requests.RequestException,osm.ServiceError) as error:
        # Exception strings from requests can contain credentials; only print the safe class.
        print(f'Snapshot generation failed ({type(error).__name__}); no replacement snapshot was published.')
        raise SystemExit(1)

if __name__ == '__main__': main()
