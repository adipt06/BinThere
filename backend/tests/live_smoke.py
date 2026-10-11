"""Explicitly invoked smoke check: a few real requests, no credential output."""
from backend.routing import get_route
from backend.osm_service import get_resources, get_resources_along_route
from backend.main import search
from backend.services import ServiceError


def run():
    route = None
    checks = []
    try:
        route = get_route(40.5008, -74.4474, 40.5030, -74.4520)
        checks.append(('Mapbox walking directions', 'PASS' if route else 'NO ROUTE'))
    except ServiceError as error:
        checks.append(('Mapbox walking directions', str(error)))
    try:
        result = search(q='New Brunswick New Jersey', longitude=-74.4474, latitude=40.5008)
        checks.append(('Mapbox address/POI search', f"{'PASS' if result['results'] else 'EMPTY'} ({len(result['results'])} results)"))
    except ServiceError as error:
        checks.append(('Mapbox address/POI search', str(error)))
    try:
        result = get_resources(40.5008, -74.4474, 500)
        checks.append(('Overpass nearby facilities', f'PASS ({len(result)} mapped facilities)'))
    except ServiceError as error:
        checks.append(('Overpass nearby facilities', str(error)))
    if route:
        try:
            result = get_resources_along_route(route['geometry']['coordinates'], radius=200, facility_type='Trash Bin')
            checks.append(('Overpass full-geometry corridor', f'PASS ({len(result)} mapped bins)'))
        except ServiceError as error:
            checks.append(('Overpass full-geometry corridor', str(error)))
    for name, outcome in checks:
        print(f'{name}: {outcome}')


if __name__ == '__main__':
    import sys
    if '--search' in sys.argv:
        try:
            result = search(q='New York', longitude=-74.006, latitude=40.7128)
            print(f"Mapbox place search: {len(result['results'])} results")
        except ServiceError as error:
            print(f'Mapbox place search: {error}')
    elif '--alternate' in sys.argv:
        from backend import osm_service
        osm_service.OVERPASS_API_URL = 'https://overpass.kumi.systems/api/interpreter'
        osm_service.OVERPASS_ALT_URL = ''
        try:
            result = osm_service.get_resources(40.7681, -73.9819, 500)
            print(f'Alternate Overpass nearby: PASS ({len(result)} facilities)')
        except ServiceError as error:
            print(f'Alternate Overpass nearby: {error}')
    else:
        run()
