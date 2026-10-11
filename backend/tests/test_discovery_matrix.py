"""Offline discovery contract and timeout stress checks; no public-service load."""
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from backend.main import app
from backend import osm_service as osm
from backend.services import ServiceError

ELEMENT={'type':'node','id':91,'lat':40.,'lon':-74.,'tags':{'amenity':'waste_basket','access':'yes'}}

class DiscoveryMatrixTests(unittest.TestCase):
    def setUp(self):
        combined = patch.dict('os.environ', {'OVERPASS_COMBINED_ENABLED':'true', 'LOCAL_FACILITIES_ENABLED':'false'})
        combined.start()
        self.addCleanup(combined.stop)
        osm.reset_overpass_state()
        self.client=TestClient(app)
    def tearDown(self):
        osm.reset_overpass_state()

    def test_selected_category_radius_location_matrix(self):
        # Empty valid upstream data tests coverage without invented production facilities.
        with patch.object(osm,'request_json',return_value={'elements':[]}), patch.object(osm.time,'sleep'):
            for latitude,longitude in [(40.,-74.),(0.,179.999),(89.99,0.)]:
                for radius in (1,200,1000,5000):
                    for category in osm.AMENITY_TAGS:
                        with self.subTest(latitude=latitude,radius=radius,category=category):
                            response=self.client.get('/resources',params={'latitude':latitude,'longitude':longitude,'radius':radius,'facility_type':category,'include_metadata':True})
                            self.assertEqual(response.status_code,200,response.text)
                            data=response.json()
                            self.assertEqual(data['facilities'],[])
                            self.assertEqual(set(data['categories']),{category})
                            state=data['categories'][category]
                            self.assertEqual(state['status'],'ok')
                            self.assertEqual(state['count'],0)
                            self.assertEqual(state['searched_radius'],min(radius,200))
                            self.assertEqual(data['partial'],radius>200)

    def test_partial_api_success_and_legacy_explicit_failure(self):
        with patch.object(osm,'fetch_overpass',side_effect=[ServiceError('combined failed'),osm._parse_resources({'elements':[ELEMENT]}),ServiceError('restroom failed'),[]]):
            response=self.client.get('/resources',params={'latitude':40,'longitude':-74,'radius':200,'include_metadata':True})
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertTrue(data['partial'])
        self.assertEqual(len(data['facilities']),1)
        self.assertIsNone(data['categories']['Restroom']['count'])
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('restroom failed')):
            legacy=self.client.get('/resources',params={'latitude':40,'longitude':-74,'radius':200})
        self.assertEqual(legacy.status_code,503)

    def test_concurrent_cold_identical_queries_coalesce(self):
        def upstream(*args,**kwargs):
            time.sleep(.02)
            return {'elements':[ELEMENT]}
        with patch.object(osm,'request_json',side_effect=upstream) as request:
            with ThreadPoolExecutor(max_workers=12) as pool:
                results=list(pool.map(lambda _:osm.fetch_overpass('shared-cold-query'),range(24)))
        self.assertEqual(request.call_count,1)
        self.assertTrue(all(result==results[0] for result in results))
        results[0][0]['metadata']['access']='mutated'
        self.assertEqual(osm.fetch_overpass('shared-cold-query')[0]['metadata']['access'],'yes')

    def test_timeout_is_100_and_remaining_budget_caps_read(self):
        with patch.object(osm,'request_json',return_value={'elements':[]}) as request, patch.object(osm.time,'sleep'):
            osm.fetch_overpass('normal')
            self.assertEqual(request.call_args.kwargs['timeout'],(3,100))
            osm.fetch_overpass('bounded',budget={'remaining':1,'deadline':time.monotonic()+20})
            read=request.call_args.kwargs['timeout'][1]
            self.assertGreater(read,19)
            self.assertLessEqual(read,20)
        for category in osm.AMENITY_TAGS:
            self.assertIn('[timeout:10]' if category == 'Trash Bin' else '[timeout:100]',osm._category_query(40,-74,200,category))
        self.assertIn('[timeout:100]',osm._combined_query(40,-74,200))

    def test_expired_budget_never_calls_upstream(self):
        with patch.object(osm,'request_json') as request:
            with self.assertRaises(ServiceError):
                osm.fetch_overpass('expired',budget={'remaining':6,'deadline':time.monotonic()-1})
        request.assert_not_called()

    def test_every_category_success_failure_combination(self):
        from itertools import product
        for successes in product((False,True),repeat=3):
            osm.reset_overpass_state()
            outcomes=[ServiceError('combined failed')]+[[] if success else ServiceError('category failed') for success in successes]
            with self.subTest(successes=successes), patch.object(osm,'fetch_overpass',side_effect=outcomes):
                response=self.client.get('/resources',params={'latitude':40,'longitude':-74,'radius':200,'include_metadata':True})
                self.assertEqual(response.status_code,200 if any(successes) else 503)
                if any(successes):
                    data=response.json()
                    self.assertEqual(data['partial'],not all(successes))
                    self.assertEqual(len(data['warnings']),successes.count(False))
                    for category,success in zip(osm.AMENITY_TAGS,successes):
                        self.assertEqual(data['categories'][category]['status'],'ok' if success else 'failed')
                        self.assertEqual(data['categories'][category]['count'],0 if success else None)

    def test_concurrent_cold_failures_do_not_multiply_upstream_calls(self):
        with patch.dict('os.environ',{'OVERPASS_ENDPOINTS':'https://offline.invalid/api/interpreter'}), patch.object(osm,'request_json',side_effect=ServiceError('Unavailable',upstream_status=503)) as request:
            def failure(_):
                try:
                    osm.fetch_overpass('shared-failure')
                except ServiceError as error:
                    return error.status
            with ThreadPoolExecutor(max_workers=12) as pool:
                statuses=list(pool.map(failure,range(24)))
        self.assertEqual(statuses,[503]*24)
        self.assertEqual(request.call_count,1)
