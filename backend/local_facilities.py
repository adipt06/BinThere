"""Validated OSM snapshots with explicit full, partial and outside coverage."""
import copy
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

TYPES = ('Trash Bin', 'Restroom', 'Recycling Location')
DEFAULT_PATH = Path(__file__).with_name('data')
logger = logging.getLogger(__name__)


def timestamp(value):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Timestamp must have a timezone.')
    return date.astimezone(timezone.utc)


def validate_snapshot(data):
    if data.get('schema_version') != 1 or data.get('license') != 'ODbL-1.0':
        raise ValueError('Unsupported snapshot format/license.')
    if set(data.get('categories', [])) != set(TYPES):
        raise ValueError('Snapshot must contain verified searches for every category.')
    west, south, east, north = data['bbox']
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in data['bbox']):
        raise ValueError('Invalid coverage.')
    if not (-180 <= west < east <= 180 and -90 < south < north < 90):
        raise ValueError('Invalid coverage bounds.')
    if timestamp(data['retrieved_at']) > datetime.now(timezone.utc):
        raise ValueError('Snapshot retrieval date is in the future.')
    source = data['source']
    if source.get('kind') not in ('overpass', 'osm_extract') or not source.get('url', '').startswith('https://'):
        raise ValueError('Missing OSM provenance.')
    if not re.fullmatch('[a-f0-9]{64}', source.get('sha256', '')):
        raise ValueError('Missing source checksum.')
    if data.get('data_timestamp') is not None:
        timestamp(data['data_timestamp'])
    if not isinstance(data.get('name'), str) or not data['name']:
        raise ValueError('Missing snapshot name.')
    if not isinstance(data.get('warnings', []), list) or any(not isinstance(w, str) for w in data.get('warnings', [])):
        raise ValueError('Invalid snapshot warnings.')
    if not isinstance(data['facilities'], list):
        raise ValueError('Invalid facilities.')
    coverage = data.get('coverage', {})
    if coverage:
        if coverage.get('type') != 'circle': raise ValueError('Unsupported coverage boundary.')
        center = coverage['center']; radius = coverage['radius_meters']
        if not (-85 <= center['latitude'] <= 85 and -180 <= center['longitude'] <= 180 and 0 < radius <= 160934.4):
            raise ValueError('Invalid circle coverage.')
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (center['latitude'],center['longitude'],radius)):
            raise ValueError('Invalid circle values.')
    ids = set()
    for facility in data['facilities']:
        if not re.fullmatch(r'(node|way|relation)/[1-9][0-9]*', facility['id']) or facility['id'] in ids:
            raise ValueError('Invalid or duplicate OSM identity.')
        ids.add(facility['id'])
        lat, lon = facility['latitude'], facility['longitude']
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)):
            raise ValueError('Invalid coordinates.')
        if not (south <= lat <= north and west <= lon <= east):
            raise ValueError('Facility outside verified coverage.')
        if coverage and distance(center['latitude'],center['longitude'],lat,lon) > radius+1e-6:
            raise ValueError('Facility outside circle coverage.')
        if facility['type'] not in TYPES or not isinstance(facility['name'], str):
            raise ValueError('Invalid category/name.')
        if facility.get('coordinate_source') not in ('node', 'area_center'):
            raise ValueError('Missing coordinate provenance.')
        expected_coordinate = 'node' if facility['id'].startswith('node/') else 'area_center'
        if facility['coordinate_source'] != expected_coordinate:
            raise ValueError('Coordinate provenance does not match OSM element type.')
        if 'osm_tags' in facility:
            tags = facility['osm_tags']
            expected_amenity = dict(zip(TYPES, ('waste_basket', 'toilets', 'recycling')))[facility['type']]
            if not isinstance(tags, dict) or any(not isinstance(v, str) for v in tags.values()) or tags.get('amenity') != expected_amenity:
                raise ValueError('Original OSM tags do not match facility category.')
        if not isinstance(facility.get('metadata'), dict) or any(not isinstance(v, str) for v in facility['metadata'].values()):
            raise ValueError('Invalid metadata.')
    if 'record_count' in data and data['record_count'] != len(data['facilities']): raise ValueError('Record count mismatch.')
    if 'counts' in data and data['counts'] != {category:sum(f['type']==category for f in data['facilities']) for category in TYPES}: raise ValueError('Category counts mismatch.')
    return data


def snapshots():
    if os.getenv('LOCAL_FACILITIES_ENABLED', 'true').lower() not in ('1', 'true', 'yes'):
        return []
    root = Path(os.getenv('LOCAL_FACILITIES_PATH', str(DEFAULT_PATH)))
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    files = sorted(root.glob('*.json')) if root.is_dir() else [root]
    result = []
    for path in files:
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 10_000_000:
                raise ValueError('Snapshot too large.')
            data = validate_snapshot(json.loads(path.read_text()))
            result.append(data)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            logger.warning('Ignoring invalid local facility snapshot %s (%s)', path.name, type(error).__name__)
    return sorted(result, key=lambda data: data['retrieved_at'], reverse=True)


def covering(bounds):
    """bounds=(south,west,north,east); require the entire search envelope inside one file."""
    south, west, north, east = bounds
    if west > east:  # Never pretend a single ordinary bbox covers date-line wrapping.
        return None
    for data in snapshots():
        left, bottom, right, top = data['bbox']
        if bottom <= south <= north <= top and left <= west <= east <= right:
            coverage=data.get('coverage',{})
            if coverage.get('type')=='circle':
                center=coverage['center']
                if any(distance(center['latitude'],center['longitude'],lat,lon)>coverage['radius_meters'] for lat in (south,north) for lon in (west,east)):continue
            return data
    return None


def source_info(data):
    return {'kind': 'local_snapshot', 'name': data['name'], 'retrieved_at': data['retrieved_at'],
            'data_timestamp': data.get('data_timestamp'), 'bbox': data['bbox'], 'coverage': data.get('coverage', {'type':'bbox','bbox':data['bbox']}),
            'attribution': '© OpenStreetMap contributors', 'license': 'ODbL-1.0',
            'license_url': 'https://www.openstreetmap.org/copyright', 'url': data['source']['url']}


def warnings(data):
    oldest = min(timestamp(data['retrieved_at']), timestamp(data.get('data_timestamp') or data['retrieved_at']))
    age = max(0, (datetime.now(timezone.utc) - oldest).total_seconds() / 86400)
    result = [f"Showing saved OpenStreetMap facilities for {data['name']}. Retrieved {data['retrieved_at']}; not live. © OpenStreetMap contributors, ODbL."]
    if age >= float(os.getenv('LOCAL_FACILITIES_STALE_DAYS', '7')):
        result.append(f'Saved facility data is {int(age)} days old and may be stale. Refresh the snapshot.')
    result.extend(data.get('warnings', []))
    return result


def facilities(data, category=None):
    source = source_info(data)
    return [{**copy.deepcopy(item), 'source': source} for item in data['facilities'] if category is None or item['type'] == category]


class CorridorFacilities(list):
    def __init__(self, items, snapshot, coverage='full'):
        super().__init__(items)
        self.warnings = warnings(snapshot)
        self.complete = coverage == 'full'
        self.coverage = coverage
        if not self.complete:self.warnings.append('Route corridor extends outside saved geographic coverage; facility recommendation may be incomplete.')


def corridor(data, coordinates, radius, category, coverage='full'):
    def distance(item):
        latitude, longitude = item['latitude'], item['longitude']
        scale = 111320 * math.cos(math.radians(latitude))
        points = [((lon-longitude)*scale, (lat-latitude)*111320) for lon, lat in coordinates]
        best = min(math.hypot(*point) for point in points)
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dx, dy = bx-ax, by-ay
            length = dx*dx+dy*dy
            t = max(0, min(1, -(ax*dx+ay*dy)/length)) if length else 0
            best = min(best, math.hypot(ax+t*dx, ay+t*dy))
        return best
    return CorridorFacilities([f for f in facilities(data, category) if distance(f) <= radius], data, coverage)


def distance(latitude, longitude, other_latitude, other_longitude):
    a,b=math.radians(latitude),math.radians(other_latitude)
    h=math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(math.radians(other_longitude-longitude)/2)**2
    return 12742000*math.asin(min(1,math.sqrt(h)))


def segment_distance(latitude, longitude, start, end):
    """Shortest distance to a minor great-circle segment, in meters."""
    def bearing(a,b):
        lat1,lat2=map(math.radians,(a[1],b[1])); delta=math.radians(b[0]-a[0])
        return math.atan2(math.sin(delta)*math.cos(lat2),math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta))
    point=[longitude,latitude]
    length=distance(start[1],start[0],end[1],end[0])/6371000
    angular=distance(start[1],start[0],latitude,longitude)/6371000
    if length<1e-12:return angular*6371000
    delta=bearing(start,point)-bearing(start,end)
    along=math.atan2(math.sin(angular)*math.cos(delta),math.cos(angular))
    if 0<=along<=length:
        return abs(math.asin(max(-1,min(1,math.sin(angular)*math.sin(delta)))))*6371000
    return min(distance(latitude,longitude,start[1],start[0]),distance(latitude,longitude,end[1],end[0]))


def mode():
    value=os.getenv('FACILITY_DATA_MODE','live_first').lower().strip()
    if value not in ('live_first','local_first','local_only'):
        try:
            from .services import ServiceError
        except ImportError:
            from services import ServiceError
        raise ServiceError('FACILITY_DATA_MODE must be live_first, local_first or local_only.', 503)
    return value


def nearby_coverage(data, latitude, longitude, radius):
    coverage=data.get('coverage',{})
    if coverage.get('type')=='circle':
        center=coverage['center']; limit=coverage['radius_meters']
        separation=distance(latitude,longitude,center['latitude'],center['longitude'])
        if separation+radius<=limit+1e-6:return 'full'
        return 'partial' if separation<=limit+radius else 'outside'
    # Legacy bbox snapshots retain conservative full-radius checks.
    delta=math.degrees(radius/6371000)
    spread=math.degrees(math.asin(min(1,math.sin(radius/6371000)/max(1e-12,math.cos(math.radians(latitude))))))
    west,south,east,north=data['bbox']
    if south<=latitude-delta and latitude+delta<=north and west<=longitude-spread and longitude+spread<=east:return 'full'
    if latitude+delta>=south and latitude-delta<=north and longitude+spread>=west and longitude-spread<=east:return 'partial'
    return 'outside'


def nearby_snapshot(latitude, longitude, radius, allow_partial=True):
    partial=None
    for data in snapshots():
        status=nearby_coverage(data,latitude,longitude,radius)
        if status=='full':return data,status
        if status=='partial' and partial is None:partial=(data,status)
    return partial if allow_partial else None


def route_snapshot(coordinates, radius, allow_partial=True):
    partial=None
    for data in snapshots():
        coverage=data.get('coverage',{})
        if coverage.get('type')=='circle':
            center=coverage['center']; limit=coverage['radius_meters']
            distances=[distance(center['latitude'],center['longitude'],lat,lon) for lon,lat in coordinates]
            full=max(distances)+radius<=limit+1e-6
            intersects=min(distances)<=limit+radius or any(segment_distance(center['latitude'],center['longitude'],a,b)<=limit+radius for a,b in zip(coordinates,coordinates[1:]))
        else:
            statuses=[nearby_coverage(data,lat,lon,radius) for lon,lat in coordinates]
            full=all(status=='full' for status in statuses)
            west,south,east,north=data['bbox']
            # Conservative segment intersection test; never claim an uncovered empty as complete.
            intersects=any(status!='outside' for status in statuses) or any(max(a[0],b[0])>=west and min(a[0],b[0])<=east and max(a[1],b[1])>=south and min(a[1],b[1])<=north for a,b in zip(coordinates,coordinates[1:]))
        if full:return data,'full'
        if intersects and partial is None:partial=(data,'partial')
    return partial if allow_partial else None


def nearby_report(match, latitude, longitude, radius, categories):
    data,coverage=match
    items=[f for f in facilities(data) if f['type'] in categories and distance(latitude,longitude,f['latitude'],f['longitude'])<=radius]
    notes=warnings(data)
    if coverage=='partial':notes.append('Search extends beyond saved geographic coverage; results cover only the overlapping area.')
    return {'facilities':items,'categories':{category:{'status':'ok' if coverage=='full' else 'partial','count':sum(f['type']==category for f in items),'searched_radius':radius,'coverage':coverage,'source':source_info(data)} for category in categories},
            'warnings':notes,'partial':coverage!='full','complete':coverage=='full','coverage':coverage,
            'requested_radius':radius,'data_mode':mode(),'sources':[source_info(data)]}
