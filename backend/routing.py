"""Mapbox walking directions; all coordinates sent longitude first."""
import math
import os
from pathlib import Path
from dotenv import load_dotenv
try:
    from .services import ServiceError, TTLCache, request_json
except ImportError:
    from services import ServiceError, TTLCache, request_json

load_dotenv(Path(__file__).with_name('.env'))
MAPBOX_TOKEN = os.getenv('MAPBOX_TOKEN', '')
MAX_SNAP_METERS = float(os.getenv('MAX_SNAP_METERS', '50'))
route_cache = TTLCache(ttl=60)


def valid_coordinate(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in value)
            and -180 <= value[0] <= 180 and -90 <= value[1] <= 90)


def get_route(start_lat, start_lon, end_lat, end_lon, stop=None, timeout=8):
    if not MAPBOX_TOKEN:
        raise ServiceError('MAPBOX_TOKEN is missing. Configure backend/.env and restart the API.', 503)
    points = [[start_lon, start_lat]]
    if stop is not None:
        points.append([stop['longitude'], stop['latitude']])
    points.append([end_lon, end_lat])
    if not all(valid_coordinate(p) for p in points):
        raise ServiceError('Invalid route coordinates.', 422)
    key = (tuple(map(tuple, points)), MAX_SNAP_METERS)
    cached = route_cache.get(key)
    if cached is not None:
        return cached
    coordinates = ';'.join(f'{lon},{lat}' for lon, lat in points)
    data = request_json('get', 'https://api.mapbox.com/directions/v5/mapbox/walking/' + coordinates,
                        service='Mapbox Directions', attempts=1, allowed_status=(422,), timeout=(3, timeout),
                        params={'access_token': MAPBOX_TOKEN, 'geometries': 'geojson', 'overview': 'full',
                                'radiuses': ';'.join([str(MAX_SNAP_METERS)] * len(points))})
    if data.get('code') in ('NoRoute', 'NoSegment'):
        return None
    if data.get('code') != 'Ok':
        raise ServiceError('Mapbox Directions returned an unexpected result.')
    try:
        route = data['routes'][0]
        geometry = route['geometry']
        waypoints = data['waypoints']
        if (geometry['type'] != 'LineString' or len(geometry['coordinates']) < 2
                or not all(valid_coordinate(p) for p in geometry['coordinates'])
                or len(waypoints) != len(points)):
            raise ValueError()
        for waypoint in waypoints:
            distance = waypoint['distance']
            if not valid_coordinate(waypoint['location']) or isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance < 0:
                raise ValueError()
            if distance > MAX_SNAP_METERS:
                return None
        if any(isinstance(route[k], bool) or not isinstance(route[k], (int, float)) or not math.isfinite(route[k]) or route[k] < 0
               for k in ('distance', 'duration')):
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ServiceError('Mapbox Directions returned malformed route or waypoint data.') from None
    result = {k: route[k] for k in ('distance', 'duration', 'geometry')}
    result['waypoints'] = waypoints
    result['warnings'] = ['Walking access and opening hours are not verified.'] if stop else []
    route_cache.put(key, result)
    return result
