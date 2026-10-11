"""Regression tests for endpoint outages, throttling and request coalescing."""
import concurrent.futures
import threading
import unittest
from unittest.mock import patch
from backend import osm_service, services
from backend.tests.test_navigation import ELEMENT, response


class OverpassResilienceTests(unittest.TestCase):
    def setUp(self):
        self.sleep_patch = patch.object(osm_service.time, 'sleep')
        self.sleeper = self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)
        osm_service.reset_overpass_state()
        self.config = patch.dict('os.environ', {'OVERPASS_ENDPOINTS':'https://one.invalid/api/interpreter,https://two.invalid/api/interpreter,https://three.invalid/api/interpreter'})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(osm_service.reset_overpass_state)

    @patch.object(services.requests, 'post', side_effect=[response({},500),response({},503),response({'elements':[ELEMENT]})])
    def test_third_endpoint_recovers_after_two_failures(self, post):
        self.assertEqual(len(osm_service.fetch_overpass('query')),1)
        self.assertEqual(post.call_count,3)
        self.assertEqual(osm_service._preferred,'https://three.invalid/api/interpreter')

    @patch.object(osm_service, 'request_json', side_effect=[services.ServiceError('failed',upstream_status=500),{'elements':[]},{'elements':[ELEMENT]}])
    def test_healthy_endpoint_preferred_for_next_query(self, request):
        self.assertEqual(osm_service.fetch_overpass('first'),[])
        self.assertEqual(len(osm_service.fetch_overpass('second')),1)
        self.assertEqual(request.call_args.args[1],'https://two.invalid/api/interpreter')

    @patch.object(osm_service, 'request_json', side_effect=[{'elements':'bad'},{'elements':[ELEMENT]}])
    def test_schema_failure_also_falls_back(self, request):
        self.assertEqual(len(osm_service.fetch_overpass('query')),1)
        self.assertEqual(request.call_count,2)

    @patch.object(osm_service, 'request_json', side_effect=[{'remark':'timeout','elements':[]},{'elements':[ELEMENT]}])
    def test_runtime_failure_also_falls_back(self, request):
        self.assertEqual(len(osm_service.fetch_overpass('query')),1)
        self.assertEqual(request.call_count,2)

    @patch.object(osm_service, 'request_json', side_effect=[{'elements':[{'type':'node','tags':[]} ]},{'elements':[ELEMENT]}])
    def test_invalid_individual_facility_falls_back(self, request):
        self.assertEqual(len(osm_service.fetch_overpass('query')),1)
        self.assertEqual(request.call_count,2)

    @patch.object(osm_service, 'request_json', return_value={'elements':[]})
    def test_successful_empty_result_is_cached(self, request):
        self.assertEqual(osm_service.fetch_overpass('query'),[])
        self.assertEqual(osm_service.fetch_overpass('query'),[])
        self.assertEqual(request.call_count,1)

    @patch.object(osm_service, 'request_json', side_effect=services.ServiceError('failed',upstream_status=500))
    def test_all_failures_are_not_empty_and_do_not_trigger_retry_storm(self, request):
        for _ in range(2):
            with self.assertRaises(services.ServiceError): osm_service.fetch_overpass('query')
        self.assertIsNone(osm_service.cache.get('query'))
        self.assertEqual(request.call_count,3)
        with self.assertRaises(services.ServiceError): osm_service.fetch_overpass('different query')
        self.assertEqual(request.call_count,3)

    @patch.object(osm_service, 'request_json', side_effect=[services.ServiceError('rate limited',upstream_status=429,retry_after='120'),{'elements':[]}])
    def test_retry_after_cooldown_honored(self, request):
        with patch.object(osm_service.time,'monotonic',return_value=100):
            self.assertEqual(osm_service.fetch_overpass('query'),[])
        self.assertEqual(osm_service._cooldowns['https://one.invalid/api/interpreter'],220)
        self.assertEqual(request.call_count,2)

    def test_concurrent_identical_searches_make_one_request(self):
        entered, release = threading.Event(), threading.Event()
        def upstream(*args,**kwargs):
            entered.set(); release.wait(3); return {'elements':[ELEMENT]}
        with patch.object(osm_service,'request_json',side_effect=upstream) as request, concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(osm_service.fetch_overpass,'query')
            self.assertTrue(entered.wait(2))
            b=pool.submit(osm_service.fetch_overpass,'query')
            release.set()
            self.assertEqual(a.result(),b.result())
            self.assertEqual(request.call_count,1)

    def test_legacy_host_migrates_and_deduplicates(self):
        with patch.dict('os.environ',{'OVERPASS_ENDPOINTS':'https://overpass.kumi.systems/api/interpreter,https://overpass.private.coffee/api/interpreter'}):
            self.assertEqual(osm_service._endpoints(),['https://overpass.private.coffee/api/interpreter'])

    def test_diagnostics_do_not_expose_path_keys_credentials_or_body(self):
        with patch.dict('os.environ',{'OVERPASS_ENDPOINTS':'https://user:secret@one.invalid/private-key/api?token=secret'}), patch.object(osm_service,'request_json',side_effect=services.ServiceError('body secret',upstream_status=500)), self.assertLogs(osm_service.logger,level='WARNING') as logs:
            with self.assertRaises(services.ServiceError) as error: osm_service.fetch_overpass('query')
        output=str(error.exception)+' '.join(logs.output)
        for forbidden in ['secret','private-key','token=','user:']: self.assertNotIn(forbidden,output)
        self.assertIn('one.invalid',output); self.assertIn('HTTP 500',output)

    @patch.object(osm_service, 'request_json', return_value={'elements':[ELEMENT]})
    def test_endpoint_recovers_after_cooldown(self, request):
        osm_service._cooldowns['https://one.invalid/api/interpreter']=100
        with patch.object(osm_service.time,'monotonic',return_value=101):
            self.assertEqual(len(osm_service.fetch_overpass('query')),1)
        self.assertEqual(request.call_args.args[1],'https://one.invalid/api/interpreter')



class NearbyQueryTests(unittest.TestCase):
    def setUp(self):
        combined = patch.dict('os.environ', {'OVERPASS_COMBINED_ENABLED':'true', 'LOCAL_FACILITIES_ENABLED':'false'})
        combined.start()
        self.addCleanup(combined.stop)
        osm_service.reset_overpass_state()

    @patch.object(osm_service,'fetch_overpass',return_value=[])
    def test_nearby_restores_exact_tag_circular_union(self, fetch):
        osm_service.get_resources(40.7681,-73.9819,500)
        query=fetch.call_args.args[0]
        self.assertEqual(query.count('nwr['),2)
        self.assertEqual(query.count('node['),1)
        self.assertEqual(query.count('around:500,40.7681,-73.9819'),3)
        self.assertIn('[timeout:100]', query)
        self.assertNotIn('~', query)
        for tag in ['waste_basket','toilets','recycling']: self.assertIn(tag,query)
        south,west,north,east=osm_service._nearby_bounds(40.7681,-73.9819,500)
        self.assertLess(south,40.7681);self.assertGreater(north,40.7681)
        self.assertLess(west,-73.9819);self.assertGreater(east,-73.9819)

    def test_bounds_wrap_date_line(self):
        south,west,north,east=osm_service._nearby_bounds(0,179.999,500)
        self.assertGreater(west,east)

    def test_bounds_include_all_longitudes_near_pole(self):
        self.assertEqual(osm_service._nearby_bounds(90,0,500)[1::2],(-180,180))

    @patch.object(osm_service,'fetch_overpass',return_value=[{'id':'node/1','type':'Trash Bin','name':'Inside','latitude':40,'longitude':-74},{'id':'node/2','type':'Trash Bin','name':'Outside','latitude':40.004,'longitude':-73.996}])
    def test_bbox_corners_outside_circle_are_filtered(self, fetch):
        self.assertEqual([r['name'] for r in osm_service.get_resources(40,-74,500)],['Inside'])

class RequestRateTests(unittest.TestCase):
    def test_successful_different_queries_are_paced(self):
        osm_service.reset_overpass_state()
        try:
            with patch.object(osm_service,'request_json',return_value={'elements':[]}), patch.object(osm_service.time,'monotonic',return_value=100), patch.object(osm_service.time,'sleep') as sleep:
                osm_service.fetch_overpass('first')
                osm_service.fetch_overpass('second')
                sleep.assert_called_once_with(1)
        finally:
            osm_service.reset_overpass_state()


if __name__ == '__main__':
    unittest.main()
