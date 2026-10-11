"""Generate genuine OSM facilities within a configurable radius; reuses existing snapshot builder.
PBF parsing is a build-only dependency: pip install -r backend/requirements-snapshot.txt
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from backend.local_facilities import segment_distance
from pathlib import Path
import requests
from backend import osm_service as osm
from backend.scripts.build_snapshot import build

SOURCE_URL='https://download.geofabrik.de/north-america/us/new-jersey-latest.osm.pbf'


def obtain_extract(path, url, refresh=False):
    """Download to a temporary file, verify provider MD5 and PBF header, then publish."""
    import osmium
    path=Path(path)
    metadata_path=path.with_suffix(path.suffix+'.provenance.json')
    if path.exists() and not refresh:
        reader=osmium.io.Reader(str(path))
        stamp=reader.header().get('osmosis_replication_timestamp')
        reader.close()
        if not stamp: raise ValueError('Cached PBF has no embedded data timestamp.')
        metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {'url':url,'retrieved_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}
        return path, stamp, metadata
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.download.osm.pbf')
    try:
        response=requests.get(url,stream=True,timeout=(5,60),headers={'User-Agent':'BinThere-HackRU/1.0 (OSM snapshot generation)'})
        response.raise_for_status()
        digest=hashlib.md5()
        length=int(response.headers.get('Content-Length',0))
        received=0
        with temporary.open('wb') as handle:
            for chunk in response.iter_content(1024*1024):
                if chunk: handle.write(chunk); digest.update(chunk); received+=len(chunk)
        if received==0 or (length and received != length): raise ValueError('Incomplete extract download.')
        checksum=requests.get(response.url+'.md5',timeout=(5,20))
        checksum.raise_for_status()
        expected=checksum.text.split()[0]
        if digest.hexdigest()!=expected: raise ValueError('Extract checksum mismatch.')
        reader=osmium.io.Reader(str(temporary))
        stamp=reader.header().get('osmosis_replication_timestamp')
        reader.close()
        if not stamp: raise ValueError('Extract has no data timestamp.')
        metadata={'url':response.url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'md5':expected}
        temporary.replace(path)
        metadata_tmp=metadata_path.with_suffix('.tmp')
        metadata_tmp.write_text(json.dumps(metadata,indent=2)+'\n'); metadata_tmp.replace(metadata_path)
        return path,stamp,metadata
    finally:
        temporary.unlink(missing_ok=True)


def verify_source_coverage(path, latitude, longitude, radius):
    """Require the complete requested circle inside an authentic Geofabrik .poly boundary."""
    lines=Path(path).read_text().splitlines()[1:]
    rings=[]; current=None; hole=False
    for line in lines:
        parts=line.split()
        if not parts:continue
        if current is None:
            if parts[0]=='END':break
            current=[];hole=parts[0].startswith('!')
        elif parts[0]=='END':
            if len(current)<3:raise ValueError('Malformed source coverage polygon.')
            rings.append((hole,current));current=None
        else:current.append((float(parts[0]),float(parts[1])))
    def inside(ring):
        result=False
        for (x1,y1),(x2,y2) in zip(ring,ring[1:]+ring[:1]):
            if (y1>latitude)!=(y2>latitude) and longitude<(x2-x1)*(latitude-y1)/(y2-y1)+x1:result=not result
        return result
    if not any(not hole and inside(ring) for hole,ring in rings) or any(hole and inside(ring) for hole,ring in rings):
        raise ValueError('Center is outside source-extract coverage.')
    for hole,ring in rings:
        if any(segment_distance(latitude,longitude,a,b)<=radius for a,b in zip(ring,ring[1:]+ring[:1])):
            raise ValueError('Requested circle crosses source-extract coverage. Use a larger or different extract.')


def generate(args):
    if not (-85 <= args.latitude <= 85 and -180 <= args.longitude <= 180 and 0 < args.radius_miles <= 100):
        raise ValueError('Invalid center or radius (0–100 miles; avoid polar/date-line regions).')
    radius=args.radius_miles*1609.344
    south,west,north,east=osm._nearby_bounds(args.latitude,args.longitude,radius)
    if west>=east: raise ValueError('Date-line spanning datasets need a different regional source.')
    extract=Path(args.extract) if args.extract else Path.home()/'.cache'/'reroute'/'new-jersey.osm.pbf'
    # Reuse the authentic versioned extract from the earlier verified acquisition if available.
    if not args.extract and not args.refresh and not extract.exists() and Path('/tmp/reroute-new-jersey.osm.pbf').exists():
        extract=Path('/tmp/reroute-new-jersey.osm.pbf')
    path,stamp,metadata=obtain_extract(extract,args.source_url,args.refresh)
    polygon=Path(args.coverage_polygon) if args.coverage_polygon else path.with_suffix('.poly')
    if not polygon.exists() or args.refresh:
        polygon_url=args.source_polygon_url or re.sub(r'-(latest|[0-9]{6})\.osm\.pbf$', '.poly', metadata['url'])
        if not polygon_url.endswith('.poly'):raise ValueError('Supply --coverage-polygon or --source-polygon-url for this extract.')
        response=requests.get(polygon_url,timeout=(5,20))
        response.raise_for_status()
        temporary=polygon.with_suffix('.tmp');temporary.write_text(response.text);temporary.replace(polygon)
    verify_source_coverage(polygon,args.latitude,args.longitude,radius)
    print(f'Using authentic extract {path}; data timestamp {stamp}; approximate center {args.latitude},{args.longitude}; radius {radius:.2f}m',flush=True)
    build_args=argparse.Namespace(bbox=[west,south,east,north],name=args.name,output=args.output,input=str(path),
                                  source_url=metadata['url'],data_timestamp=stamp,
                                  center=[args.latitude,args.longitude],radius_meters=radius)
    return build(build_args)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--latitude',type=float,default=40.53399)
    parser.add_argument('--longitude',type=float,default=-74.45793)
    parser.add_argument('--radius-miles',type=float,default=10)
    parser.add_argument('--extract',help='Reuse an existing genuine, complete regional .osm.pbf.')
    parser.add_argument('--source-url',default=SOURCE_URL)
    parser.add_argument('--coverage-polygon',help='Authentic source .poly boundary; downloaded automatically for Geofabrik.')
    parser.add_argument('--source-polygon-url',help='HTTPS boundary URL for another authorized extract.')
    parser.add_argument('--refresh',action='store_true',help='Download and checksum-verify a new extract before regenerating.')
    parser.add_argument('--output',default='backend/data/resources_10mi.json')
    parser.add_argument('--name',default='Piscataway / New Brunswick area')
    args=parser.parse_args()
    try: generate(args)
    except (ImportError,OSError,ValueError,RuntimeError,KeyError,requests.RequestException):
        print('Generation failed; existing facility dataset was preserved. Check source coverage, network, and optional osmium installation.')
        raise SystemExit(1)

if __name__=='__main__':main()
