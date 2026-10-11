"""Community fixtures use temporary SQLite storage; no public submissions or live AI calls."""
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from PIL import Image
from backend.main import app
from backend import community_store as store, community_api, osm_service as osm, gemini_service, optimizer
from backend.community_models import FacilityRecognition, FacilitySubmission
from backend.services import ServiceError

RECOGNITION={'facility_type':'Trash Bin','confidence':.95,'description':'A visible waste basket.','suggested_name':'Community bin'}

def photo():
    output=io.BytesIO(); Image.new('RGB',(20,20),'white').save(output,format='PNG'); return output.getvalue()

class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.environment=patch.dict('os.environ',{'COMMUNITY_DB_PATH':str(Path(self.directory.name)/'community.sqlite3'),'COMMUNITY_REPORT_THRESHOLD':'3'})
        self.environment.start();self.addCleanup(self.environment.stop)
        self.client=TestClient(app)

    def recognize(self, client=None, result=None):
        client=client or self.client
        with patch.object(gemini_service,'identify_facility',return_value=FacilityRecognition(**(result or RECOGNITION))) as identify:
            response=client.post('/community/recognize',files={'image':('facility.png',photo(),'image/png')})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(identify.call_args.args[1],'image/jpeg')
        return response.json()['recognition_token']

    def submit(self, client=None, **updates):
        client=client or self.client
        data={'recognition_token':self.recognize(client),'latitude':40.53399,'longitude':-74.45793,
              'name':'A community bin','location_source':'gps','public_access_confirmed':True}
        data.update(updates)
        return client.post('/community/facilities',json=data)

    def test_persistence_and_discovery_merge_without_changing_osm(self):
        response=self.submit();self.assertEqual(response.status_code,201,response.text)
        identifier=response.json()['facility']['id'];self.assertTrue(identifier.startswith('community/'))
        self.assertEqual(store.active()[0]['id'],identifier)
        original={'facilities':[{'id':'node/7','type':'Trash Bin'}], 'categories':{'Trash Bin':{'status':'ok','count':1}},
                  'warnings':[], 'partial':False,'complete':True}
        with patch.object(osm,'_osm_resources_report',return_value=original):
            result=osm.get_resources_report(40.53399,-74.45793,100,'Trash Bin')
        self.assertEqual(len(result['facilities']),2);self.assertEqual(result['categories']['Trash Bin']['count'],2)
        self.assertFalse(result['facilities'][1]['access_verified']);self.assertEqual(result['facilities'][1]['source']['kind'],'community')
        self.assertEqual(len(store.nearby(40.53399,-74.45793,100,'Restroom')),0)
        self.assertEqual(len(store.nearby(0,0,100)),0)

    def test_recognition_tokens_are_owner_bound_single_use_and_expiring(self):
        token=self.recognize();payload={'recognition_token':token,'latitude':40.,'longitude':-74.,'name':'Bin','location_source':'gps','public_access_confirmed':True}
        self.assertEqual(TestClient(app).post('/community/facilities',json=payload).status_code,422)
        self.assertEqual(self.client.post('/community/facilities',json=payload).status_code,201)
        self.assertEqual(self.client.post('/community/facilities',json=payload).status_code,422)
        expired=self.recognize()
        with store.database() as db:db.execute('UPDATE tickets SET expires=? WHERE token=?',(time.time()-1,expired))
        payload['recognition_token']=expired
        self.assertEqual(self.client.post('/community/facilities',json=payload).status_code,422)

    def test_unknown_and_low_confidence_do_not_issue_publish_token(self):
        for result in ({**RECOGNITION,'facility_type':'unknown'},{**RECOGNITION,'confidence':.4}):
            self.assertIsNone(self.recognize(result=result))
        self.assertEqual(store.active(),[])

    def test_invalid_photo_and_provider_failure_do_not_create_facilities(self):
        with patch.object(gemini_service,'identify_facility',side_effect=ServiceError('Gemini timed out.',504)):
            response=self.client.post('/community/recognize',files={'image':('test.png',photo(),'image/png')})
        self.assertEqual(response.status_code,504)
        with patch.object(gemini_service,'identify_facility',side_effect=AssertionError('must not call')):
            response=self.client.post('/community/recognize',files={'image':('bad.png',b'invalid','image/png')})
        self.assertEqual(response.status_code,422);self.assertFalse(store.active())
        response=self.client.post('/community/recognize',content=b'x'*(gemini_service.MAX_BODY_BYTES+1))
        self.assertEqual(response.status_code,413)

    def test_submission_validation_and_nearby_deduplication(self):
        for updates in ({'public_access_confirmed':False},{'latitude':91},{'longitude':181},{'name':' '},{'facility_type':'Restroom'}):
            self.assertEqual(self.submit(**updates).status_code,422)
        self.assertEqual(self.submit().status_code,201)
        self.assertEqual(self.submit(latitude=40.534).status_code,409)
        self.assertEqual(len(store.active()),1)

    def test_three_distinct_browser_reports_hide_and_duplicate_does_not_count(self):
        facility=self.submit().json()['facility'];path=f"/community/facilities/{facility['id']}/reports"
        response=self.client.post(path,json={'reason':'not_here'});self.assertEqual(response.json()['report_count'],1)
        self.assertFalse(response.json()['removed'])
        self.assertEqual(self.client.post(path,json={'reason':'fraudulent'}).status_code,409)
        response=TestClient(app).post(path,json={'reason':'fraudulent'});self.assertEqual(response.json()['report_count'],2)
        response=TestClient(app).post(path,json={'reason':'not_public'});self.assertTrue(response.json()['removed'])
        self.assertEqual(store.active(),[])
        self.assertEqual(self.client.post(path,json={'reason':'not_here'}).status_code,410)
        self.assertEqual(self.client.post('/community/facilities/node/7/reports',json={'reason':'not_here'}).status_code,404)

    def test_concurrent_reports_atomically_deduplicate(self):
        facility=self.submit().json()['facility']
        def send(_):
            try:return store.report(facility['id'],'same-browser','not_here')['report_count']
            except ServiceError as error:return error.status
        with ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(send,range(4)))
        self.assertEqual(sorted(results),[1,409,409,409])

    def test_rate_limits_are_persistent(self):
        store.rate_limit('test-network','recognize',1)
        with self.assertRaises(ServiceError) as error:store.rate_limit('test-network','recognize',1)
        self.assertEqual(error.exception.status,429)

    def test_address_coordinates_are_permanent_and_bound_to_selected_result(self):
        data={'type':'FeatureCollection','features':[{'geometry':{'type':'Point','coordinates':[-74.45793,40.53399]},'properties':{'full_address':'Public park street address'}}]}
        with patch.object(community_api,'MAPBOX_TOKEN','test-token'),patch.object(community_api,'request_json',return_value=data) as geocode:
            response=self.client.get('/community/address-search',params={'q':'123 Public Park Road'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(geocode.call_args.kwargs['params']['permanent'],'true')
        address_token=response.json()['results'][0]['address_token']
        self.assertEqual(self.submit(location_source='address',address_token=address_token,longitude=-70).status_code,422)
        response=self.submit(location_source='address',address_token=address_token)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['facility']['coordinate_source'],'community_address')

    def test_community_only_discovery_preserves_failed_coverage(self):
        self.submit()
        with patch.object(osm,'_osm_resources_report',side_effect=ServiceError('Upstream unavailable',503)):
            result=osm.get_resources_report(40.53399,-74.45793,100,'Trash Bin')
            self.assertTrue(result['partial']);self.assertFalse(result['complete'])
            self.assertEqual(result['categories']['Trash Bin']['status'],'failed')
            self.assertIsNone(result['categories']['Trash Bin']['count']);self.assertEqual(len(result['facilities']),1)
        with patch.object(osm,'_osm_resources_report',side_effect=ServiceError('Upstream unavailable',503)):
            with self.assertRaises(ServiceError):osm.get_resources_report(0,0,100)

    def test_corridor_filters_category_and_immediately_excludes_removed_facility(self):
        facility=self.submit().json()['facility'];coordinates=[[-74.46,40.53399],[-74.455,40.53399]]
        with patch.object(osm,'_osm_resources_along_route',return_value=[]):
            self.assertEqual(len(osm.get_resources_along_route(coordinates,100,'Trash Bin')),1)
            self.assertFalse(osm.get_resources_along_route(coordinates,100,'Restroom'))
        with patch.object(osm,'_osm_resources_along_route',side_effect=ServiceError('Upstream unavailable',503)):
            result=osm.get_resources_along_route(coordinates,100,'Trash Bin')
            self.assertEqual(len(result),1);self.assertFalse(result.complete)
        for owner in ['one','two','three']:store.report(facility['id'],owner,'not_here')
        with patch.object(osm,'_osm_resources_along_route',return_value=[]):
            self.assertFalse(osm.get_resources_along_route(coordinates,100,'Trash Bin'))

    def test_real_classification_contract_uses_image_and_facility_schema(self):
        class Response:
            status_code=200
            def __init__(self,payload):self.payload=payload
            def json(self):return self.payload
        gemini_service.model_cache.clear()
        self.addCleanup(gemini_service.model_cache.clear)
        with patch.dict('os.environ',{'GEMINI_API_KEY':'test-secret','GEMINI_MODEL':'gemini-test'}),patch.object(gemini_service.requests,'request',side_effect=[
            Response({'supportedGenerationMethods':['generateContent']}),
            Response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(RECOGNITION)}]}}]})]) as send:
            image,mime=gemini_service.validate_image(photo(),'image/png')
            result=gemini_service.identify_facility(image,mime)
        self.assertEqual(result.facility_type,'Trash Bin')
        payload=send.call_args.kwargs['json']
        self.assertIn('inlineData',payload['contents'][0]['parts'][0])
        self.assertIn('unknown',payload['systemInstruction']['parts'][0]['text'])
        self.assertIn('facility_type',payload['generationConfig']['responseFormat']['text']['schema']['properties'])

    def test_all_supported_facility_categories_can_be_added(self):
        for category in ['Trash Bin','Restroom','Recycling Location']:
            token=self.recognize(result={**RECOGNITION,'facility_type':category})
            response=self.client.post('/community/facilities',json={
                'recognition_token':token,'latitude':40.53399,'longitude':-74.45793,
                'name':category,'location_source':'gps','public_access_confirmed':True})
            self.assertEqual(response.status_code,201,response.text)
        self.assertEqual({f['type'] for f in store.active()},{'Trash Bin','Restroom','Recycling Location'})

    def test_optimizer_evaluates_community_stop_and_nearest_bin_includes_it(self):
        facility=self.submit().json()['facility']
        coordinates=[[-74.46,40.53399],[-74.455,40.53399]]
        direct={'distance':500,'duration':400,'geometry':{'type':'LineString','coordinates':coordinates}}
        alternative={**direct,'duration':420,'distance':520}
        with patch.object(osm,'_osm_resources_along_route',return_value=[]),patch.object(optimizer,'get_route',side_effect=[direct,alternative]) as route:
            result=optimizer.find_best_route(40.53399,-74.46,40.53399,-74.455,'Trash Bin')
        self.assertEqual(result['facility']['id'],facility['id'])
        self.assertEqual(result['detour_seconds'],20)
        self.assertEqual(route.call_args.kwargs['stop']['id'],facility['id'])
        self.assertTrue(any('Community submissions' in warning for warning in result['warnings']))
        with patch.object(osm,'_osm_resources_report',return_value={'facilities':[],'categories':{'Trash Bin':{'status':'ok','count':0}},'warnings':[],'complete':True}),patch('backend.main.get_route',return_value=direct):
            result=self.client.get('/nearest-bin',params={'latitude':40.53399,'longitude':-74.45793,'radius':100})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['facility']['id'],facility['id'])

    def test_browser_identity_cookie_and_cors_credentials(self):
        self.recognize()
        cookie=self.client.cookies.get('reroute_community')
        self.assertTrue(cookie)
        response=self.client.options('/community/facilities',headers={
            'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        self.assertEqual(response.headers['access-control-allow-credentials'],'true')
        self.assertEqual(response.headers['access-control-allow-origin'],'http://localhost:5173')

    def test_community_storage_failure_preserves_osm_results_with_warning(self):
        original={'facilities':[{'id':'node/7','type':'Trash Bin'}], 'categories':{'Trash Bin':{'status':'ok','count':1}},
                  'warnings':[],'partial':False,'complete':True}
        with patch.object(store,'nearby',side_effect=ServiceError('Storage unavailable',503)),patch.object(osm,'_osm_resources_report',return_value=original):
            result=osm.get_resources_report(40,-74,100,'Trash Bin')
        self.assertEqual(result['facilities'][0]['id'],'node/7');self.assertTrue(result['partial'])
        self.assertIn('Community facilities could not be loaded',result['warnings'][0])
        with patch.object(store,'corridor',side_effect=ServiceError('Storage unavailable',503)),patch.object(osm,'_osm_resources_along_route',return_value=original['facilities']):
            result=osm.get_resources_along_route([[-74,40]],100,'Trash Bin')
        self.assertEqual(result[0]['id'],'node/7');self.assertFalse(result.complete)
