"""Bounded heuristic: best eligible route among evaluated, usable facilities."""
import os
import time
try:
    from .osm_service import get_resources_along_route, _distance
    from .routing import get_route
    from .services import ServiceError
except ImportError:
    from osm_service import get_resources_along_route, _distance
    from routing import get_route
    from services import ServiceError
import math


def distance_to_route(resource, coordinates):

    latitude = resource["latitude"]
    longitude = resource["longitude"]

    scale_x = 111320 * math.cos(math.radians(latitude))
    scale_y = 111320

    points = []

    for lon, lat in coordinates:
        x = (lon - longitude) * scale_x
        y = (lat - latitude) * scale_y
        points.append((x, y))

    if len(points) == 1:
        return math.hypot(*points[0])

    closest = float("inf")

    for i in range(len(points) - 1):

        ax, ay = points[i]
        bx, by = points[i + 1]

        dx = bx - ax
        dy = by - ay

        length_squared = dx * dx + dy * dy

        if length_squared == 0:
            t = 0
        else:
            t = -(ax * dx + ay * dy) / length_squared
            t = max(0, min(1, t))

        x = ax + t * dx
        y = ay + t * dy

        distance = math.hypot(x, y)
        closest = min(closest, distance)

    return closest


def find_best_route(start_lat, start_lon, end_lat, end_lon, facility_type,
                    max_detour_minutes=5, max_candidates=None):
    budget = float(os.getenv('OPTIMIZER_TIMEOUT_SECONDS', '45'))
    limit = max_candidates if max_candidates is not None else int(os.getenv('OPTIMIZER_MAX_CANDIDATES', '8'))
    limit = max(1, min(100, limit))
    direct = get_route(start_lat, start_lon, end_lat, end_lon)
    if direct is None:
        return None
    warnings = ['Best route among evaluated candidates; map coverage and walking access are not guaranteed.']
    # A round-trip perpendicular excursion at about 1.4 m/s; a heuristic, not a completeness bound.
    requested_radius = max(200, round(max_detour_minutes * 60 * 1.4 / 2 + 100))
    radius = min(requested_radius, int(os.getenv('OPTIMIZER_MAX_CORRIDOR_METERS', '2000')))
    if radius < requested_radius:
        warnings.append('Search corridor was capped by the configured radius limit.')
    try:
        resources = get_resources_along_route(direct['geometry']['coordinates'], radius=radius, facility_type=facility_type)
    except ServiceError as error:
        result = _result(direct, None, None, 0, 0, 0, radius, [*warnings, str(error)], False, 1)
        result.update(coverage=getattr(error, 'coverage', 'unavailable'), facility_search_complete=False)
        return result
    warnings.extend(getattr(resources, 'warnings', []))
    coverage_complete = getattr(resources, 'complete', True)
    unique = {r['id']: r for r in resources if r['type'] == facility_type
              and str(r.get('metadata', {}).get('access', '')).lower() not in ('private', 'no')}
    candidates = list(unique.values())
    coordinates = direct['geometry']['coordinates']
    near = sorted(candidates, key=lambda r: distance_to_route(r, coordinates))
    via = sorted(candidates, key=lambda r: _distance(start_lat, start_lon, r['latitude'], r['longitude'])
                 + _distance(r['latitude'], r['longitude'], end_lat, end_lon))
    # Interleave two rankings rather than spending the entire budget on closest-to-path facilities.
    ranked, seen = [], set()
    for pair in zip(via, near):
        for resource in pair:
            if resource['id'] not in seen:
                ranked.append(resource)
                seen.add(resource['id'])
    best, facility = None, None
    evaluated = attempted = failures = 0
    exhausted = False
    # Reserve the candidate-routing budget after discovery: a slow failed upstream
    # must not prevent optimization using a valid local snapshot.
    started = time.monotonic()
    for resource in ranked[:limit]:
        remaining = budget - (time.monotonic() - started)
        if remaining < 1:
            exhausted = True
            break
        attempted += 1
        try:
            alternative = get_route(start_lat, start_lon, end_lat, end_lon, stop=resource, timeout=min(8, remaining))
        except ServiceError as error:
            failures += 1
            if error.status == 503:
                warnings.append(str(error))
                break
            continue
        if alternative is None:
            continue
        evaluated += 1
        detour = max(0, alternative['duration'] - direct['duration'])
        if detour <= max_detour_minutes * 60 and (best is None or alternative['duration'] < best['duration']):
            best, facility = alternative, resource
    limited = exhausted or attempted < len(ranked)
    if limited:
        warnings.append('Candidate or time limit reached; some facilities were not evaluated.')
    if failures:
        warnings.append(f'{failures} candidate request(s) failed; recommendation may be incomplete.')
    if facility and facility.get('coordinate_source') == 'area_center':
        warnings.append('Facility location is an OSM area center; confirm the entrance on arrival.')
    result = _result(direct, best, facility, evaluated, attempted, len(ranked), radius, warnings, limited, failures)
    result['coverage'] = getattr(resources, 'coverage', 'full')
    result['facility_search_complete'] = coverage_complete
    result['search_complete'] = result['search_complete'] and coverage_complete
    if not coverage_complete and facility is None:
        result['message'] = 'Facility search was incomplete; showing the direct route'
    return result


def _result(direct, best, facility, evaluated, attempted, total, radius, warnings, limited, failures):
    detour = max(0, best['duration'] - direct['duration']) if best else None
    summary = {
        'direct_distance_meters': round(direct['distance'], 2),
        'direct_duration_minutes': round(direct['duration'] / 60, 2),
        'optimized_distance_meters': round(best['distance'], 2) if best else None,
        'optimized_duration_minutes': round(best['duration'] / 60, 2) if best else None,
        'extra_distance_meters': round(best['distance'] - direct['distance'], 2) if best else None,
        'detour_minutes': round(detour / 60, 2) if best else None,
        'detour_seconds': round(detour, 2) if best else None,
        'facility_type': facility['type'] if facility else None,
        'facility_name': facility['name'] if facility else None,
        'facility_latitude': facility['latitude'] if facility else None,
        'facility_longitude': facility['longitude'] if facility else None,
        'meets_detour_constraint': True if best else None,
    }
    return {'summary': summary, 'direct_route': direct, 'optimized_route': best,
            'facility': facility, 'detour_seconds': detour, 'candidates_evaluated': evaluated,
            'candidates_attempted': attempted, 'candidates_found': total, 'candidate_limit_reached': limited,
            'candidate_failures': failures, 'search_radius_meters': radius, 'warnings': warnings,
            'search_complete': not limited and failures == 0, 'globally_optimal': False,
            'message': ('Route found among evaluated facilities' if best else
                        'Facility search was incomplete; showing the direct route' if failures or limited else
                        'No qualifying facility found in the searched corridor; showing the direct route')}
