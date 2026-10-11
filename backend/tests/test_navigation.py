import copy
import importlib
import os
import unittest
from unittest.mock import Mock, patch
import requests
from fastapi.testclient import TestClient
from backend import main, routing, optimizer, osm_service, services

ROUTE = {'distance': 1000, 'duration': 600, 'geometry': {'type': 'LineString', 'coordinates': [[-74,40],[-74.01,40]]}}
FACILITY = {'id': 'node/1', 'name': 'Campus Bin', 'type': 'Trash Bin', 'latitude': 40, 'longitude': -74.005, 'metadata': {}}
PAYLOAD = dict(start_lat=40, start_lon=-74, end_lat=40, end_lon=-74.01, facility_type='Trash Bin', max_detour_minutes=5)
ELEMENT = {'type':'node','id':1,'lat':40,'lon':-74,'tags':{'amenity':'waste_basket','name':'Campus Bin','wheelchair':'yes','recycling:paper':'yes'}}


def response(data, status=200):
    r = Mock(status_code=status, ok=200 <= status < 300)
    r.json.return_value = data
    return r


def mapbox_data():
    return {'code':'Ok','routes':[copy.deepcopy(ROUTE)], 'waypoints':[{'distance':1,'location':[-74,40]},{'distance':2,'location':[-74.01,40]}]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def test_health(self):
        self.assertEqual(self.client.get('/health').status_code,200)
        self.assertIn('mapbox_configured',self.client.get('/health').json())

    def test_invalid_resource_inputs(self):
        for query in ['latitude=91&longitude=0','latitude=0&longitude=181','latitude=0&longitude=0&radius=0','latitude=0&longitude=0&radius=20001','latitude=nan&longitude=0','latitude=0&longitude=0&radius=1.5']:
            with self.subTest(query=query): self.assertEqual(self.client.get('/resources?'+query).status_code,422)

    def test_invalid_route(self):
        self.assertEqual(self.client.get('/route?start_lat=40&start_lon=-74&end_lat=91&end_lon=-74').status_code,422)

    def test_invalid_optimization(self):
        for change in [{'facility_type':'All'},{'max_detour_minutes':31},{'max_detour_minutes':-1},{'end_lat':91}]:
            with self.subTest(change=change): self.assertEqual(self.client.post('/optimized-route',json={**PAYLOAD,**change}).status_code,422)

    @patch.object(main,'get_resources',return_value=[FACILITY])
    def test_resources_contract(self,mock):
        r=self.client.get('/resources?latitude=40&longitude=-74&radius=1000')
        self.assertEqual(r.json(),[FACILITY]); mock.assert_called_once_with(40,-74,1000)

    @patch.object(main,'get_route',return_value=ROUTE)
    def test_route_contract(self,mock):
        self.assertEqual(self.client.get('/route?start_lat=40&start_lon=-74&end_lat=40&end_lon=-74.01').json(),ROUTE)

    @patch.object(main,'get_route',return_value=None)
    def test_no_route(self,_mock):
        self.assertEqual(self.client.get('/route?start_lat=40&start_lon=-74&end_lat=40&end_lon=-74.01').status_code,404)

    @patch.object(main,'get_route',side_effect=services.ServiceError('MAPBOX_TOKEN is missing.',503))
    def test_configuration_error(self,_mock):
        r=self.client.get('/route?start_lat=40&start_lon=-74&end_lat=40&end_lon=-74.01')
        self.assertEqual(r.status_code,503); self.assertIn('MAPBOX_TOKEN',r.json()['detail'])

    def test_cors(self):
        r=self.client.options('/optimized-route',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['access-control-allow-origin'],'http://localhost:5173')

    def test_configurable_production_cors(self):
        try:
            with patch.dict(os.environ, {'CORS_ORIGINS':'https://reroute.example'}):
                importlib.reload(main)
                r=TestClient(main.app).options('/optimized-route',headers={'Origin':'https://reroute.example','Access-Control-Request-Method':'POST'})
                self.assertEqual(r.headers['access-control-allow-origin'],'https://reroute.example')
        finally:
            importlib.reload(main)

    @patch.object(main,'MAPBOX_TOKEN','test')
    @patch.object(main,'request_json',return_value={'type':'FeatureCollection','features':[{'geometry':{'type':'Point','coordinates':[-74,40]},'properties':{'name':'Campus','full_address':'Campus, NJ'}}]})
    def test_place_search(self,mock):
        self.assertEqual(self.client.get('/search?q=Campus').json()['results'][0]['coordinates'],[-74,40])
        self.assertIn('/search/searchbox/v1/forward',mock.call_args.args[1])

    @patch.object(main,'MAPBOX_TOKEN','test')
    @patch.object(main,'request_json',return_value={'features':[]})
    def test_malformed_search(self,_mock):
        self.assertEqual(self.client.get('/search?q=Campus').status_code,502)

    @patch.object(main,'get_resources_report',return_value={'warnings':[], 'facilities':[FACILITY,{**FACILITY,'id':'node/2','longitude':-74.006}]})
    @patch.object(main,'get_route',side_effect=[{**ROUTE,'duration':700},{**ROUTE,'duration':500}])
    def test_nearest_by_walking_time(self,_route,_resources):
        result=self.client.get('/nearest-bin?latitude=40&longitude=-74').json()
        self.assertEqual(result['facility']['id'],'node/2'); self.assertEqual(result['candidates_evaluated'],2)

    @patch.object(main,'get_resources_report',return_value={'warnings':[], 'facilities':[]})
    def test_nearest_empty(self,_mock):
        self.assertIsNone(self.client.get('/nearest-bin?latitude=40&longitude=-74').json()['facility'])


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.sleep_patch = patch.object(osm_service.time, 'sleep')
        self.sleeper = self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)
        osm_service.reset_overpass_state(); routing.route_cache.clear()

    @patch.object(services.requests,'post',return_value=response({'elements':[ELEMENT,ELEMENT]}))
    def test_dedup_metadata_cache(self,mock):
        a=osm_service.fetch_overpass('query'); a[0]['name']='changed'
        b=osm_service.fetch_overpass('query')
        self.assertEqual(len(b),1); self.assertEqual(b[0]['name'],'Campus Bin')
        self.assertEqual(b[0]['metadata']['wheelchair'],'yes'); self.assertFalse(b[0]['access_verified'])
        self.assertEqual(mock.call_count,1)

    @patch.object(services.requests,'post',return_value=response({'remark':'runtime error timeout','elements':[]}))
    def test_overpass_runtime_error(self,_mock):
        with self.assertRaises(services.ServiceError): osm_service.fetch_overpass('query')
        self.assertIsNone(osm_service.cache.get('query'))

    @patch.object(services.time,'sleep')
    @patch.object(services.requests,'post',side_effect=requests.Timeout('secret token'))
    def test_overpass_timeout_retry(self,mock,_sleep):
        with self.assertRaises(services.ServiceError) as result: osm_service.fetch_overpass('query')
        self.assertEqual(result.exception.status,503); self.assertNotIn('secret',str(result.exception)); self.assertEqual(mock.call_count,2)

    @patch.object(services.time,'sleep')
    @patch.object(services.requests,'post',side_effect=[response({},429),response({'elements':[]})])
    def test_http_retry(self,mock,_sleep):
        self.assertEqual(osm_service.fetch_overpass('query'),[]); self.assertEqual(mock.call_count,2)

    @patch.object(osm_service,'OVERPASS_ALT_URL','https://alternate.invalid')
    @patch.object(services.requests,'post',side_effect=[response({},503),response({'elements':[]})])
    def test_alternate_endpoint(self,mock):
        self.assertEqual(osm_service.fetch_overpass('query'),[]); self.assertEqual(mock.call_args.args[0],'https://alternate.invalid')

    @patch.object(services.requests,'post',return_value=response({'elements':'bad'}))
    def test_overpass_malformed(self,_mock):
        with self.assertRaises(services.ServiceError): osm_service.fetch_overpass('query')

    @patch.object(osm_service,'fetch_overpass',return_value=[])
    def test_corridor_retains_bends_category(self,mock):
        coords=[[-74+i/10000,40+(i%2)/1000] for i in range(50)]
        osm_service.get_resources_along_route(coords,600,'Restroom')
        query=mock.call_args.args[0]; self.assertIn('toilets',query); self.assertNotIn('waste_basket',query)
        for lon,lat in coords: self.assertIn(f'{lat},{lon}',query)

    @patch.object(osm_service,'fetch_overpass',return_value=[{**FACILITY,'latitude':41}])
    def test_area_center_outside_radius(self,_mock):
        with patch.dict('os.environ', {'OVERPASS_COMBINED_ENABLED':'true'}):
            self.assertEqual(osm_service.get_resources(40,-74,500),[])

    @patch.object(routing,'MAPBOX_TOKEN','')
    def test_missing_token(self):
        with self.assertRaises(services.ServiceError) as error: routing.get_route(40,-74,40,-74.01)
        self.assertEqual(error.exception.status,503)

    @patch.object(routing,'MAPBOX_TOKEN','test')
    @patch.object(routing,'request_json',side_effect=lambda *a,**kw:mapbox_data())
    def test_mapbox_coordinates_cache(self,mock):
        self.assertEqual(routing.get_route(40,-74,40,-74.01)['distance'],1000)
        routing.get_route(40,-74,40,-74.01)
        self.assertEqual(mock.call_count,1); self.assertTrue(mock.call_args.args[1].endswith('-74,40;-74.01,40'))

    @patch.object(routing,'MAPBOX_TOKEN','test')
    def test_intermediate_stop(self):
        data=mapbox_data(); data['waypoints'].insert(1,{'distance':1,'location':[-74.005,40]})
        with patch.object(routing,'request_json',return_value=data) as mock:
            self.assertIsNotNone(routing.get_route(40,-74,40,-74.01,stop=FACILITY))
            self.assertTrue(mock.call_args.args[1].endswith('-74,40;-74.005,40;-74.01,40'))
            self.assertEqual(len(mock.call_args.kwargs['params']['radiuses'].split(';')),3)

    @patch.object(routing,'MAPBOX_TOKEN','test')
    def test_snap_too_far(self):
        data=mapbox_data(); data['waypoints'][0]['distance']=1000
        with patch.object(routing,'request_json',return_value=data): self.assertIsNone(routing.get_route(40,-74,40,-74.01))

    @patch.object(routing,'MAPBOX_TOKEN','test')
    @patch.object(routing,'request_json',return_value={'code':'NoRoute'})
    def test_mapbox_no_route(self,_mock): self.assertIsNone(routing.get_route(40,-74,40,-74.01))

    @patch.object(routing,'MAPBOX_TOKEN','test')
    def test_mapbox_malformed(self):
        for data in [{'code':'Ok','routes':[]},{'code':'Ok','routes':[ROUTE]}, {'code':'Unexpected'}]:
            with self.subTest(data=data),patch.object(routing,'request_json',return_value=data):
                with self.assertRaises(services.ServiceError): routing.get_route(40,-74,40,-74.01)

    @patch.object(services.requests,'get',return_value=response({},401))
    def test_credentials_redacted(self,_mock):
        with self.assertRaises(services.ServiceError) as error:
            services.request_json('get','https://example.invalid?access_token=secret',service='Mapbox')
        self.assertNotIn('secret',str(error.exception)); self.assertEqual(error.exception.status,503)

    @patch.object(routing, 'MAPBOX_TOKEN', 'test')
    @patch.object(services.requests, 'get', return_value=response({'code':'NoSegment'},422))
    def test_mapbox_http_422_no_segment(self, _mock):
        self.assertIsNone(routing.get_route(40,-74,40,-74.01))

    @patch.object(services.requests, 'post', return_value=response({'elements':[{**ELEMENT,'center':[]}]}))
    def test_invalid_center_ignored_for_valid_node(self, _mock):
        self.assertEqual(len(osm_service.fetch_overpass('query')),1)

    @patch.object(services.requests, 'post', return_value=response({'elements':[{**ELEMENT,'center':'invalid'}]}))
    def test_malformed_center(self, _mock):
        with self.assertRaises(services.ServiceError): osm_service.fetch_overpass('query')

    def test_cache_expiry_capacity(self):
        cache=services.TTLCache(ttl=0,capacity=1); cache.put('a',[]); self.assertIsNone(cache.get('a'))
        cache=services.TTLCache(capacity=1); cache.put('a',1); cache.put('b',2); self.assertIsNone(cache.get('a'))


class OptimizerTests(unittest.TestCase):
    def run_optimizer(self, facilities, outcomes, **kwargs):
        with patch.object(optimizer,'get_resources_along_route',return_value=facilities) as resources,patch.object(optimizer,'get_route',side_effect=[ROUTE,*outcomes]):
            result=optimizer.find_best_route(40,-74,40,-74.01,'Trash Bin',**kwargs)
            return result,resources

    def test_detour_boundary_and_summary(self):
        result,_=self.run_optimizer([FACILITY],[{**ROUTE,'duration':900,'distance':1400}],max_detour_minutes=5)
        self.assertEqual(result['detour_seconds'],300); self.assertEqual(result['summary']['extra_distance_meters'],400)
        self.assertTrue(result['summary']['meets_detour_constraint']); self.assertFalse(result['globally_optimal'])

    def test_detour_rejected(self):
        result,_=self.run_optimizer([FACILITY],[{**ROUTE,'duration':901}],max_detour_minutes=5)
        self.assertIsNone(result['optimized_route']); self.assertEqual(result['direct_route'],ROUTE)

    def test_zero_detour(self):
        result,_=self.run_optimizer([FACILITY],[ROUTE],max_detour_minutes=0)
        self.assertEqual(result['detour_seconds'],0); self.assertIsNotNone(result['facility'])

    def test_filter_private_and_type(self):
        result,_=self.run_optimizer([{**FACILITY,'metadata':{'access':'private'}},{**FACILITY,'id':'node/2','type':'Restroom'}],[])
        self.assertEqual(result['candidates_attempted'],0)

    def test_partial_success(self):
        result,_=self.run_optimizer([FACILITY,{**FACILITY,'id':'node/2'}],[{**ROUTE,'duration':650},services.ServiceError('timeout',504)])
        self.assertIsNotNone(result['facility']); self.assertEqual(result['candidate_failures'],1); self.assertFalse(result['search_complete'])

    def test_unroutable_candidate(self):
        result,_=self.run_optimizer([FACILITY,{**FACILITY,'id':'node/2'}],[None,ROUTE])
        self.assertEqual(result['candidates_evaluated'],1); self.assertIsNotNone(result['facility'])

    def test_more_than_eight(self):
        facilities=[{**FACILITY,'id':f'node/{i}'} for i in range(9)]
        result,_=self.run_optimizer(facilities,[{**ROUTE,'duration':1000}]*8+[ROUTE],max_candidates=24)
        self.assertEqual(result['candidates_evaluated'],9); self.assertIsNotNone(result['facility'])

    def test_candidate_limit(self):
        result,_=self.run_optimizer([FACILITY,{**FACILITY,'id':'node/2'}],[ROUTE],max_candidates=1)
        self.assertTrue(result['candidate_limit_reached']); self.assertFalse(result['search_complete'])

    def test_time_budget_exposes_incomplete_search(self):
        with patch.object(optimizer.time,'monotonic',side_effect=[0,100]), patch.object(optimizer,'get_route',return_value=ROUTE), patch.object(optimizer,'get_resources_along_route',return_value=[FACILITY]):
            result=optimizer.find_best_route(40,-74,40,-74.01,'Trash Bin')
        self.assertEqual(result['candidates_attempted'],0)
        self.assertTrue(result['candidate_limit_reached'])
        self.assertFalse(result['search_complete'])

    def test_radius_scales(self):
        _,a=self.run_optimizer([],[],max_detour_minutes=1); _,b=self.run_optimizer([],[],max_detour_minutes=20)
        self.assertGreater(b.call_args.kwargs['radius'],a.call_args.kwargs['radius'])

    @patch.object(optimizer,'get_route',return_value=ROUTE)
    @patch.object(optimizer,'get_resources_along_route',side_effect=services.ServiceError('Overpass failed'))
    def test_overpass_failure_direct_fallback(self,_a,_b):
        result=optimizer.find_best_route(40,-74,40,-74.01,'Trash Bin')
        self.assertEqual(result['direct_route'],ROUTE); self.assertEqual(result['candidate_failures'],1)

    @patch.object(optimizer,'get_route',return_value=None)
    def test_no_direct_route(self,_mock): self.assertIsNone(optimizer.find_best_route(40,-74,40,-74.01,'Trash Bin'))

    def test_optimization_http_schema(self):
        result,_=self.run_optimizer([FACILITY],[{**ROUTE,'duration':650}])
        with patch.object(main,'find_best_route',return_value=result):
            actual=TestClient(main.app).post('/optimized-route',json=PAYLOAD)
        self.assertEqual(actual.status_code,200)
        for key in ('direct_route','optimized_route','facility','summary','detour_seconds','warnings','candidates_evaluated'): self.assertIn(key,actual.json())


if __name__=='__main__': unittest.main()
