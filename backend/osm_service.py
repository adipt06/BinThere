"""Real OSM amenities, with bounded retries and short-lived caching."""
import math
import os
import time
import hashlib
import logging
import threading
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))
logger = logging.getLogger(__name__)
try:
    from .services import ServiceError, TTLCache, request_json
    from . import local_facilities as local
except ImportError:
    from services import ServiceError, TTLCache, request_json
    import local_facilities as local

OVERPASS_API_URL = os.getenv('OVERPASS_API_URL', 'https://overpass.private.coffee/api/interpreter')
OVERPASS_ALT_URL = os.getenv('OVERPASS_ALT_URL', 'https://overpass-api.de/api/interpreter')
AMENITY_TAGS = {'Trash Bin': 'waste_basket', 'Restroom': 'toilets', 'Recycling Location': 'recycling'}
cache = TTLCache(ttl=float(os.getenv('OVERPASS_CACHE_SECONDS', '90')))
failure_cache = TTLCache(ttl=5)
category_cache = TTLCache(ttl=float(os.getenv("OVERPASS_CACHE_SECONDS", "90")))
combined_failures = TTLCache(ttl=60)
query_failures = TTLCache(ttl=30)
_request_lock = threading.Lock()
_cooldowns = {}
_preferred = None
_last_failures = {}
_last_request_started = None
_snapshot_fallback_until = 0


def _endpoint_host(endpoint):
    # Do not log URL paths, userinfo or query strings: private providers may embed API keys there.
    return urlsplit(endpoint).hostname or 'invalid-host'


def _endpoints():
    configured = os.getenv('OVERPASS_ENDPOINTS')
    urls = configured.split(',') if configured else [OVERPASS_API_URL, OVERPASS_ALT_URL]
    endpoints = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        parts = urlsplit(url)
        if parts.hostname == 'overpass.kumi.systems':
            # The old virtual host returns HTTP 500; Private.coffee is its current name.
            url = 'https://overpass.private.coffee/api/interpreter'
        if url not in endpoints:
            endpoints.append(url)
    return endpoints[:3]


def _retry_delay(error):
    minimum = 60 if error.upstream_status in (429, 406) else 30
    try:
        raw = error.retry_after
        delay = float(raw)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(raw).timestamp() - time.time() if isinstance(raw, str) else minimum
        except (TypeError, ValueError, OverflowError):
            delay = minimum
    return max(minimum, min(3600, delay))


def reset_overpass_state():
    """Reset in-process state for deterministic tests, not a public API."""
    global _preferred, _last_request_started, _snapshot_fallback_until
    _snapshot_fallback_until = 0
    cache.clear()
    failure_cache.clear()
    category_cache.clear()
    combined_failures.clear()
    query_failures.clear()
    _cooldowns.clear()
    _last_failures.clear()
    _preferred = None
    _last_request_started = None


def fetch_overpass(query, *, query_specific=False, budget=None):
    cached = cache.get(query)
    if cached is not None:
        return cached
    # Serialize cache misses. Simultaneous identical searches share the completed cache entry,
    # and distinct queries do not run concurrently against public infrastructure.
    if not _request_lock.acquire(timeout=100):
        raise ServiceError('Facility search is busy. Please retry shortly.', 503)
    try:
        return _fetch_uncached(query, query_specific=query_specific, budget=budget)
    finally:
        _request_lock.release()


def _fetch_uncached(query, *, query_specific=False, budget=None):
    global _preferred, _last_request_started
    cached = cache.get(query)
    if cached is not None:
        return cached
    failed = failure_cache.get(query)
    if failed is not None:
        raise ServiceError(failed[0], failed[1])
    endpoints = _endpoints()
    endpoints.sort(key=lambda endpoint: endpoint != _preferred)
    failures = []
    query_id = hashlib.sha256(query.encode()).hexdigest()[:12]
    for endpoint in endpoints:
        host = _endpoint_host(endpoint)
        if _cooldowns.get(endpoint, 0) > time.monotonic():
            failures.append(f"{host}: {_last_failures.get(endpoint, 'unavailable')} (cooling down)")
            continue
        if query_failures.get((endpoint, query)) is not None:
            failures.append(f'{host}: query cooling down')
            continue
        # Bound aggregate request rate across different query keys and endpoints too.
        if _last_request_started is not None:
            time.sleep(max(0, 1 - (time.monotonic() - _last_request_started)))
        started = time.monotonic()
        if budget is not None:
            if budget["remaining"] <= 0 or started >= budget["deadline"]:
                raise ServiceError("Facility search request budget reached. Please retry shortly.", 503)
            budget["remaining"] -= 1
        _last_request_started = started
        try:
            data = request_json('post', endpoint, service='Overpass', attempts=1,
                                data={'data': query}, timeout=(3, min(100, max(1, budget['deadline'] - started))) if budget else (3, 100),
                                headers={'User-Agent': os.getenv('OVERPASS_USER_AGENT', 'ReRoute-HackRU/1.0 (environmental walking navigation)'),
                                         'Accept': 'application/json'})
            if data.get('remark'):
                raise ServiceError('Overpass could not complete the search.', 504, reason='runtime')
            if not isinstance(data.get('elements'), list):
                raise ServiceError('Overpass returned malformed facility data.', reason='schema')
            resources = _parse_resources(data)
        except ServiceError as error:
            if query_specific and (error.upstream_status == 500 or error.reason == 'runtime'):
                # A rejected combined query does not establish that small category queries fail.
                query_failures.put((endpoint, query), True)
            else:
                _cooldowns[endpoint] = time.monotonic() + _retry_delay(error)
            outcome = f'HTTP {error.upstream_status}' if error.upstream_status else error.reason or 'invalid response'
            _last_failures[endpoint] = outcome
            failures.append(f'{host}: {outcome}')
            logger.warning('Overpass failure host=%s outcome=%s query=%s bytes=%d elapsed=%.2fs',
                           host, outcome, query_id, len(query), time.monotonic() - started)
            continue
        _preferred = endpoint
        _cooldowns.pop(endpoint, None)
        _last_failures.pop(endpoint, None)
        cache.put(query, resources)
        logger.info('Overpass success host=%s query=%s facilities=%d elapsed=%.2fs',
                    host, query_id, len(resources), time.monotonic() - started)
        return resources
    message = 'Facility service unavailable (' + '; '.join(failures or ['no Overpass endpoints configured']) + '). Please retry shortly.'
    # Failures are never cached as empty facility lists.
    failure_cache.put(query, (message, 503))
    raise ServiceError(message, 503)


def _parse_resources(data):
    resources = {}
    names = {v: k for k, v in AMENITY_TAGS.items()}
    for element in data['elements']:
        if not isinstance(element, dict):
            raise ServiceError('Overpass returned a malformed facility.')
        tags = element.get('tags', {})
        if not isinstance(tags, dict) or any(not isinstance(v, str) for v in tags.values()):
            raise ServiceError('Overpass returned malformed facility tags.')
        if tags.get('amenity') not in names:
            continue
        center = element.get('center') or {}
        if not isinstance(center, dict) or any(not isinstance(v, str) for v in tags.values()):
            raise ServiceError('Overpass returned malformed facility metadata.')
        lat, lon = element.get('lat', center.get('lat')), element.get('lon', center.get('lon'))
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if element.get('type') not in ('node', 'way', 'relation') or 'id' not in element:
            raise ServiceError('Overpass returned an invalid facility identity.')
        resource_id = f"{element['type']}/{element['id']}"
        metadata = {k: v for k, v in tags.items() if k in ('access', 'wheelchair', 'opening_hours', 'fee', 'operator', 'drinking_water') or k.startswith('recycling:')}
        resources[resource_id] = {'id': resource_id, 'name': tags.get('name') or 'Unknown',
                                  'type': names[tags['amenity']], 'latitude': lat, 'longitude': lon,
                                  'metadata': metadata, 'osm_tags': dict(tags), 'coordinate_source': 'node' if element['type'] == 'node' else 'area_center',
                                  'access_verified': False}
    result = list(resources.values())
    return result


def _nearby_bounds(latitude, longitude, radius):
    """Conservative spherical bounding box, including pole/date-line handling."""
    delta = radius / 6371000
    south = max(-90, latitude - math.degrees(delta))
    north = min(90, latitude + math.degrees(delta))
    if south == -90 or north == 90:
        west, east = -180, 180
    else:
        spread = math.degrees(math.asin(min(1, math.sin(delta) / math.cos(math.radians(latitude)))))
        west = (longitude - spread + 180) % 360 - 180
        east = (longitude + spread + 180) % 360 - 180
    return south, west, north, east


def _selector(tag):
    return 'node' if tag == 'waste_basket' else 'nwr'


def _combined_query(latitude, longitude, radius):
    # Restore the original exact-tag circular union; avoid regex/bbox query-plan changes.
    return '[out:json][timeout:100];(' + ''.join(
        f'{_selector(tag)}["amenity"="{tag}"](around:{radius},{latitude},{longitude});'
        for tag in AMENITY_TAGS.values()) + ');out center;'


def _category_query(latitude, longitude, radius, category):
    tag = AMENITY_TAGS[category]
    timeout, output = (10, 'body') if tag == 'waste_basket' else (100, 'center')
    return f'[out:json][timeout:{timeout}];{_selector(tag)}["amenity"="{tag}"](around:{radius},{latitude},{longitude});out {output};'


def _within(resources, latitude, longitude, radius, category=None):
    return list({r['id']: r for r in resources if (category is None or r['type'] == category)
                 and _distance(latitude, longitude, r['latitude'], r['longitude']) <= radius}.values())


def get_resources_report(latitude, longitude, radius=2000, facility_type=None):
    """Explicit per-category coverage; failed searches are never successful empty lists."""
    categories = [facility_type] if facility_type else list(AMENITY_TAGS)
    if any(c not in AMENITY_TAGS for c in categories):
        raise ServiceError('Unknown facility category.', 422)
    global _snapshot_fallback_until
    mode = local.mode()
    match = local.nearby_snapshot(latitude, longitude, radius)
    if match and ((mode == 'local_first' and match[1] == 'full') or mode == 'local_only'
                  or (match[1] == 'full' and _snapshot_fallback_until > time.monotonic())):
        return local.nearby_report(match, latitude, longitude, radius, categories)
    if mode == 'local_only':
        error = ServiceError('Requested area is outside saved OSM coverage or no valid local dataset is available. Live discovery is disabled in local_only mode.', 503)
        error.coverage = 'outside' if local.snapshots() else 'unavailable'
        raise error
    budget = {"remaining": 6, "deadline": time.monotonic() + 100}
    key = (latitude, longitude, radius)
    results, states, warnings = {}, {}, []
    for category in categories:
        cached = category_cache.get((*key, category))
        if cached is not None:
            results[category], states[category] = cached['facilities'], cached['state']
    missing = [c for c in categories if c not in states]
    combined_cap = max(1, min(5000, int(os.getenv('OVERPASS_COMBINED_MAX_RADIUS', '1000'))))
    if os.getenv('OVERPASS_COMBINED_ENABLED', 'false').lower() in ('true', '1', 'yes') and not facility_type and len(missing) == len(categories) and radius <= combined_cap and combined_failures.get(key) is None:
        try:
            resources = fetch_overpass(_combined_query(latitude, longitude, radius), query_specific=True, budget=budget)
            for category in categories:
                results[category] = _within(resources, latitude, longitude, radius, category)
                states[category] = {'status': 'ok', 'searched_radius': radius, 'count': len(results[category])}
                category_cache.put((*key, category), {'facilities': results[category], 'state': states[category]})
        except ServiceError:
            combined_failures.put(key, True)
    fallback_cap = max(1, min(1000, int(os.getenv('OVERPASS_CATEGORY_MAX_RADIUS', '200'))))
    for category in categories:
        if category in states:
            continue
        searched_radius = min(radius, fallback_cap)
        try:
            resources = fetch_overpass(_category_query(latitude, longitude, searched_radius, category), query_specific=True, budget=budget)
            results[category] = _within(resources, latitude, longitude, searched_radius, category)
            states[category] = {'status': 'ok', 'searched_radius': searched_radius, 'count': len(results[category])}
            category_cache.put((*key, category), {'facilities': results[category], 'state': states[category]})
        except ServiceError as error:
            states[category] = {'status': 'failed', 'searched_radius': searched_radius, 'count': None, 'warning': str(error)}
    failed_categories = [category for category, state in states.items() if state['status'] == 'failed']
    if match is not None and failed_categories:
        data, coverage = match
        saved = local.nearby_report(match, latitude, longitude, radius, failed_categories)
        for category in failed_categories:
            results[category] = [f for f in saved['facilities'] if f['type'] == category]
            states[category] = saved['categories'][category]
        warnings.append('Live facility service is temporarily unavailable; showing saved results where covered.')
        warnings.extend(saved['warnings'])
        _snapshot_fallback_until = time.monotonic() + 30
    for category, state in states.items():
        if state['status'] == 'failed':
            warnings.append(f"{category} could not be loaded: {state['warning']}")
        elif state['searched_radius'] < radius:
            warnings.append(f"{category} searched within {state['searched_radius']} m of the requested {radius} m radius to limit public-server load.")
    if all(state['status'] == 'failed' for state in states.values()):
        reasons = list(dict.fromkeys(state['warning'] for state in states.values()))
        raise ServiceError('All requested facility categories failed. ' + ' '.join(reasons), 503)
    merged = {r['id']: r for group in results.values() for r in group}
    complete = all(state['status'] == 'ok' and state['searched_radius'] >= radius for state in states.values())
    return {'facilities': list(merged.values()), 'categories': states, 'warnings': warnings,
            'partial': not complete, 'complete': complete, 'requested_radius': radius,
            'coverage': 'full' if complete else 'partial', 'data_mode': mode}


def get_resources(latitude, longitude, radius=2000):
    # Existing array consumers never silently receive an incomplete search.
    report = get_resources_report(latitude, longitude, radius)
    if not report['complete']:
        raise ServiceError('Partial facility results available; request /resources?include_metadata=true. ' + ' '.join(report['warnings']), 503)
    return report['facilities']


def _distance(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(h)))


def _simplify_corridor(coordinates, tolerance=10):
    """Douglas-Peucker in a local metric plane; retain turns, endpoints and original geometry."""
    if len(coordinates) < 3:
        return coordinates
    latitude = sum(p[1] for p in coordinates) / len(coordinates)
    scale = 111320 * math.cos(math.radians(latitude))
    origin_lon, origin_lat = coordinates[0]
    points = [((lon-origin_lon)*scale, (lat-origin_lat)*111320) for lon, lat in coordinates]
    keep, pending = {0, len(points)-1}, [(0, len(points)-1)]
    while pending:
        first, last = pending.pop()
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx-ax, by-ay
        length = dx*dx+dy*dy
        maximum, index = 0, None
        for i in range(first+1, last):
            x, y = points[i]
            t = max(0, min(1, ((x-ax)*dx+(y-ay)*dy)/length)) if length else 0
            distance = math.hypot(x-ax-t*dx, y-ay-t*dy)
            if distance > maximum:
                maximum, index = distance, i
        if maximum > tolerance:
            keep.add(index)
            if len(keep) > 256:
                raise ServiceError('This route is too complex for a bounded facility search.', 422)
            pending.extend([(first,index),(index,last)])
    return [coordinates[i] for i in sorted(keep)]


def _live_resources_along_route(coordinates, radius=200, facility_type=None):
    if not coordinates:
        return []
    if len(coordinates) > 20000:
        raise ServiceError('This walking route is too long for facility optimization.', 422)
    if facility_type is not None and facility_type not in AMENITY_TAGS:
        raise ServiceError('Unknown facility category.', 422)
    # Simplify before transport, not before Mapbox routing/ranking. Ten-meter padding
    # conservatively compensates for simplification in the local metric plane.
    corridor = _simplify_corridor(coordinates)
    if len(corridor) > 256:
        raise ServiceError('This route is too complex for a bounded facility search.', 422)
    search_radius = radius + 10 if len(corridor) < len(coordinates) else radius
    path = ','.join(f'{lat},{lon}' for lon, lat in corridor)
    tags = [AMENITY_TAGS[facility_type]] if facility_type else AMENITY_TAGS.values()
    query = '[out:json][timeout:100];(' + ''.join(
        f'{_selector(tag)}["amenity"="{tag}"](around:{search_radius},{path});' for tag in tags) + ');out center;'
    return fetch_overpass(query, budget={"remaining": 3, "deadline": time.monotonic() + 100})


def get_resources_along_route(coordinates, radius=200, facility_type=None):
    global _snapshot_fallback_until
    if not coordinates:
        return []
    if facility_type is not None and facility_type not in AMENITY_TAGS:
        raise ServiceError('Unknown facility category.', 422)
    mode = local.mode()
    match = local.route_snapshot(coordinates, radius)
    if match and ((mode == 'local_first' and match[1] == 'full') or mode == 'local_only'
                  or (match[1] == 'full' and _snapshot_fallback_until > time.monotonic())):
        return local.corridor(match[0], coordinates, radius, facility_type, match[1])
    if mode == 'local_only':
        error = ServiceError('Route corridor is outside saved OSM coverage or no valid local dataset is available. Live discovery is disabled.', 503)
        error.coverage = 'outside' if local.snapshots() else 'unavailable'
        raise error
    try:
        return _live_resources_along_route(coordinates, radius, facility_type)
    except ServiceError:
        if match is None:
            raise
        _snapshot_fallback_until = time.monotonic() + 30
        return local.corridor(match[0], coordinates, radius, facility_type, match[1])
