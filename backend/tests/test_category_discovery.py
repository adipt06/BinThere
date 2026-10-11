import unittest
from unittest.mock import patch
from backend import osm_service as osm
from backend.services import ServiceError
from backend.main import app
from fastapi.testclient import TestClient

BIN = {'id':'node/7','type':'Trash Bin','name':'Test bin','latitude':40.,'longitude':-74.,'metadata':{'access':'yes'}}

class CategoryDiscoveryTests(unittest.TestCase):
    def setUp(self):
        combined = patch.dict('os.environ', {'OVERPASS_COMBINED_ENABLED':'true', 'LOCAL_FACILITIES_ENABLED':'false'})
        combined.start()
        self.addCleanup(combined.stop)
        osm.reset_overpass_state()
    def tearDown(self):
        osm.reset_overpass_state()

    def test_partial_success_dedup_metadata_and_failed_not_empty(self):
        with patch.object(osm, 'fetch_overpass', side_effect=[ServiceError('HTTP 500'), [BIN, BIN], ServiceError('HTTP 500'), []]) as fetch:
            report = osm.get_resources_report(40., -74., 200)
        self.assertEqual(len(fetch.call_args_list), 4)
        self.assertEqual(report['facilities'], [BIN])
        self.assertEqual(report['categories']['Restroom']['status'], 'failed')
        self.assertIsNone(report['categories']['Restroom']['count'])
        self.assertEqual(report['categories']['Recycling Location']['count'], 0)
        self.assertTrue(report['partial'])
        self.assertIn('Restroom', report['warnings'][0])

    def test_total_failure(self):
        with patch.object(osm, 'fetch_overpass', side_effect=ServiceError('unavailable')):
            with self.assertRaises(ServiceError) as error:
                osm.get_resources_report(40., -74., 200)
        self.assertEqual(error.exception.status, 503)

    def test_selected_category_and_success_cache(self):
        with patch.object(osm, 'fetch_overpass', return_value=[BIN]) as fetch:
            first = osm.get_resources_report(40., -74., 200, 'Trash Bin')
            second = osm.get_resources_report(40., -74., 200, 'Trash Bin')
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('"waste_basket"', fetch.call_args.args[0])
        self.assertNotIn('toilets', fetch.call_args.args[0])

    def test_large_radius_bounded_and_successful_categories_cached(self):
        with patch.object(osm, 'fetch_overpass', side_effect=[[BIN], ServiceError('unavailable'), []]) as fetch:
            report = osm.get_resources_report(40., -74., 5000)
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(all('(around:200,' in call.args[0] for call in fetch.call_args_list))
        self.assertTrue(report['partial'])
        with patch.object(osm, 'fetch_overpass', return_value=[]) as fetch:
            osm.get_resources_report(40., -74., 5000)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('toilets', fetch.call_args.args[0])

    def test_query_500_allows_smaller_query_but_429_cools_endpoint(self):
        with patch.dict('os.environ', {'OVERPASS_ENDPOINTS':'https://example.invalid/api/interpreter'}), patch.object(osm.time, 'sleep'), patch.object(osm, 'request_json', side_effect=[ServiceError('500', upstream_status=500), {'elements':[]}]) as request:
            with self.assertRaises(ServiceError):
                osm.fetch_overpass('combined', query_specific=True)
            self.assertEqual(osm.fetch_overpass('small', query_specific=True), [])
            self.assertEqual(request.call_count, 2)
        osm.reset_overpass_state()
        with patch.dict('os.environ', {'OVERPASS_ENDPOINTS':'https://example.invalid/api/interpreter'}), patch.object(osm, 'request_json', side_effect=ServiceError('429', upstream_status=429)) as request:
            for query in ('combined', 'small'):
                with self.assertRaises(ServiceError):
                    osm.fetch_overpass(query, query_specific=True)
            self.assertEqual(request.call_count, 1)

    def test_metadata_mode_api_and_legacy_array(self):
        client = TestClient(app)
        with patch.object(osm, 'fetch_overpass', return_value=[BIN]):
            response = client.get('/resources', params={'latitude':40,'longitude':-74,'radius':200,'include_metadata':'true'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['facilities'], [BIN])
            response = client.get('/resources', params={'latitude':40,'longitude':-74,'radius':200})
            self.assertEqual(response.json(), [BIN])

    def test_shared_budget_stops_before_another_upstream_request(self):
        import time
        budget = {'remaining': 1, 'deadline': time.monotonic() + 45}
        with patch.dict('os.environ', {'OVERPASS_ENDPOINTS':'https://example.invalid/api/interpreter'}), patch.object(osm.time, 'sleep'), patch.object(osm, 'request_json', return_value={'elements':[]}) as request:
            self.assertEqual(osm.fetch_overpass('first', query_specific=True, budget=budget), [])
            with self.assertRaises(ServiceError):
                osm.fetch_overpass('second', query_specific=True, budget=budget)
            self.assertEqual(request.call_count, 1)
