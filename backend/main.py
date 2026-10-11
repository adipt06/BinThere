"""ReRoute HTTP contracts. Launch from root or from backend/."""
import os
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).with_name('.env'))
try:
    from .osm_service import get_resources, get_resources_report, _distance
    from .routing import get_route, valid_coordinate, MAPBOX_TOKEN
    from .optimizer import find_best_route
    from .services import ServiceError, request_json
except ImportError:
    from osm_service import get_resources, get_resources_report, _distance
    from routing import get_route, valid_coordinate, MAPBOX_TOKEN
    from optimizer import find_best_route
    from services import ServiceError, request_json

app = FastAPI(title='ReRoute API')
origins = os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173')
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins.split(',') if o.strip()],
                   allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])


@app.exception_handler(ServiceError)
async def service_error(_request: Request, error: ServiceError):
    content = {'detail': str(error)}
    if hasattr(error, 'coverage'): content['coverage'] = error.coverage
    return JSONResponse(status_code=error.status, content=content)


@app.get('/')
def home():
    return {'message': 'Backend is running!'}


@app.get('/health')
def health():
    return {'status': 'ok' if MAPBOX_TOKEN else 'degraded', 'mapbox_configured': bool(MAPBOX_TOKEN)}


@app.get('/resources')
def resources(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180),
              radius: int = Query(default=2000, ge=1, le=20000),
              include_metadata: bool = False,
              facility_type: Literal['Trash Bin', 'Restroom', 'Recycling Location'] | None = None):
    if include_metadata:
        return get_resources_report(latitude, longitude, radius, facility_type)
    if facility_type is not None:
        raise HTTPException(422, 'Category-specific searches require include_metadata=true.')
    return get_resources(latitude, longitude, radius)


@app.get('/route')
def route(start_lat: float = Query(ge=-90, le=90), start_lon: float = Query(ge=-180, le=180),
          end_lat: float = Query(ge=-90, le=90), end_lon: float = Query(ge=-180, le=180)):
    result = get_route(start_lat, start_lon, end_lat, end_lon)
    if result is None:
        raise HTTPException(404, 'No walking route within the allowed snapping distance.')
    return result


class OptimizeRequest(BaseModel):
    start_lat: float = Field(ge=-90, le=90)
    start_lon: float = Field(ge=-180, le=180)
    end_lat: float = Field(ge=-90, le=90)
    end_lon: float = Field(ge=-180, le=180)
    facility_type: Literal['Trash Bin', 'Restroom', 'Recycling Location']
    max_detour_minutes: float = Field(default=5, ge=0, le=30)


@app.post('/optimized-route')
def optimized_route(request: OptimizeRequest):
    result = find_best_route(**request.model_dump())
    if result is None:
        raise HTTPException(404, 'No direct walking route found within the allowed snapping distance.')
    return result


@app.get('/search')
def search(q: str = Query(min_length=2, max_length=256),
           longitude: float | None = Query(default=None, ge=-180, le=180),
           latitude: float | None = Query(default=None, ge=-90, le=90)):
    if not MAPBOX_TOKEN:
        raise ServiceError('MAPBOX_TOKEN is missing. Configure backend/.env and restart the API.', 503)
    if not q.strip():
        raise HTTPException(422, 'Enter an address or place name.')
    params = {'q': q.strip(), 'access_token': MAPBOX_TOKEN, 'limit': 5}
    if latitude is not None and longitude is not None:
        params['proximity'] = f'{longitude},{latitude}'
    # Search Box supports POIs as well as addresses; one request on form submission.
    data = request_json('get', 'https://api.mapbox.com/search/searchbox/v1/forward',
                        service='Mapbox Search', timeout=(3, 8), params=params)
    try:
        if data['type'] != 'FeatureCollection' or not isinstance(data['features'], list):
            raise ValueError()
        results = []
        for feature in data['features']:
            coord = feature['geometry']['coordinates']
            props = feature['properties']
            if feature['geometry']['type'] != 'Point' or not valid_coordinate(coord) or not isinstance(props['name'], str):
                raise ValueError()
            results.append({'name': props.get('full_address') or props['name'], 'coordinates': coord})
        return {'results': results, 'attribution': data.get('attribution', '© Mapbox and its suppliers')}
    except (KeyError, TypeError, ValueError):
        raise ServiceError('Mapbox Search returned malformed results.') from None


@app.get('/nearest-bin')
def nearest_bin(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180),
                radius: int = Query(default=1000, ge=1, le=20000)):
    discovery = get_resources_report(latitude, longitude, radius, 'Trash Bin')
    bins = [r for r in discovery['facilities'] if r['type'] == 'Trash Bin'
            and r.get('metadata', {}).get('access') not in ('private', 'no')]
    bins.sort(key=lambda r: _distance(latitude, longitude, r['latitude'], r['longitude']))
    limit = max(1, min(20, int(os.getenv('NEAREST_MAX_CANDIDATES', '6'))))
    best = facility = None
    evaluated = failures = 0
    for candidate in bins[:limit]:
        try:
            candidate_route = get_route(latitude, longitude, candidate['latitude'], candidate['longitude'], timeout=5)
        except ServiceError as error:
            if error.status == 503:
                raise
            failures += 1
            continue
        if candidate_route is not None:
            evaluated += 1
            if best is None or candidate_route['duration'] < best['duration']:
                best, facility = candidate_route, candidate
    if bins and evaluated == 0 and failures:
        raise ServiceError('Walking routes to nearby bins could not be checked. Please retry.', 504)
    return {'facility': facility, 'route': best, 'candidates_evaluated': evaluated,
            'coverage': discovery.get('coverage', 'full'), 'search_complete': discovery.get('complete', True),
            'warnings': discovery['warnings'] + ['Shortest walking time among checked nearby bins; access is unverified.']
                        + (['Some bins were not checked.'] if len(bins) > limit or failures else [])}
