"""Photo-confirmed community submissions. Browser identity is anonymous, not authentication."""
from fastapi import APIRouter, File, Query, Request, Response, UploadFile
try:
    from . import community_store as store, gemini_service
    from .community_models import FacilitySubmission, FacilityReport
    from .routing import MAPBOX_TOKEN, valid_coordinate
    from .services import ServiceError, request_json
except ImportError:
    import community_store as store
    import gemini_service
    from community_models import FacilitySubmission, FacilityReport
    from routing import MAPBOX_TOKEN, valid_coordinate
    from services import ServiceError, request_json

router = APIRouter(prefix='/community', tags=['Community facilities'])


def actor(request, response):
    owner, cookie, network = store.identity(request.cookies.get('reroute_community'),
                                           request.client.host if request.client else 'unknown')
    response.set_cookie('reroute_community', cookie, max_age=31536000, httponly=True,
                        secure=request.url.scheme=='https', samesite='lax', path='/')
    return owner, network


@router.post('/recognize')
def recognize(request: Request, response: Response, image: UploadFile = File()):
    owner, network = actor(request, response)
    try:
        store.rate_limit(network, 'recognize', 12)
        content, mime = gemini_service.validate_image(image.file.read(gemini_service.MAX_IMAGE_BYTES+1), image.content_type)
    finally:
        image.file.close()
    result = gemini_service.identify_facility(content, mime)
    token = None
    if result.facility_type != 'unknown' and result.confidence >= .75:
        token = store.ticket(owner, 'photo', result.model_dump())
    return {'recognition': result.model_dump(), 'recognition_token': token,
            'warning': 'Image recognition does not verify public access or the facility location.'}


@router.get('/address-search')
def address_search(request: Request, response: Response, q: str = Query(min_length=2, max_length=256)):
    owner, network = actor(request, response)
    if not q.strip() or ';' in q or len(q.split())>20:
        raise ServiceError('Enter a street address of up to 20 words.',422)
    if not MAPBOX_TOKEN: raise ServiceError('Mapbox is not configured for address lookup.',503)
    store.rate_limit(network, 'address', 30)
    # Unlike temporary Search Box results, these coordinates will be stored.
    data = request_json('get', 'https://api.mapbox.com/search/geocode/v6/forward',
        service='Mapbox permanent address lookup', attempts=1, timeout=(3,10),
        params={'q':q.strip(), 'access_token':MAPBOX_TOKEN, 'permanent':'true',
                'autocomplete':'false', 'types':'address', 'limit':5})
    try:
        if data['type']!='FeatureCollection' or not isinstance(data['features'],list): raise ValueError()
        results=[]
        for feature in data['features']:
            coordinates=feature['geometry']['coordinates']
            props=feature['properties']
            if feature['geometry']['type']!='Point' or not valid_coordinate(coordinates): raise ValueError()
            name=props.get('full_address') or props.get('name')
            if not isinstance(name,str): raise ValueError()
            results.append({'name':name, 'coordinates':coordinates,
                            'address_token':store.ticket(owner,'address',{'coordinates':coordinates})})
        return {'results':results, 'attribution':data.get('attribution','© Mapbox and its suppliers')}
    except (KeyError,TypeError,ValueError):
        raise ServiceError('Address lookup returned malformed results.') from None


@router.post('/facilities', status_code=201)
def submit(request: Request, response: Response, submission: FacilitySubmission):
    owner, network = actor(request, response)
    store.rate_limit(network,'submit',10)
    return {'facility':store.create(owner,submission)}


@router.post('/facilities/{facility_id:path}/reports')
def report(request: Request, response: Response, facility_id: str, payload: FacilityReport):
    owner, network = actor(request,response)
    store.rate_limit(network,'report',20,86400)
    return store.report(facility_id,owner,payload.reason)
