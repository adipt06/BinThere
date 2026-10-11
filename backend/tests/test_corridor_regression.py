"""Compare committed original queries with bounded current queries, without network."""
import subprocess
import unittest
from unittest.mock import patch
from backend import osm_service as osm
from backend import optimizer
from backend.services import ServiceError

class CorridorRegressionTests(unittest.TestCase):
    def original_query(self, coordinates):
        original = {}
        exec(subprocess.check_output(['git','show','105b902:backend/osm_service.py'], text=True), original)
        queries = []
        original['fetch_overpass'] = lambda query: queries.append(query) or []
        original['get_resources_along_route'](coordinates, 200, 'Restroom')
        return queries[0]

    def test_dense_straight_route_smaller_than_original_and_full_geometry(self):
        points = [[-74+i/100000,40] for i in range(1000)]
        original = self.original_query(points)
        with patch.object(osm,'fetch_overpass',return_value=[]) as fetch:
            osm.get_resources_along_route(points, 200, 'Restroom')
        current = fetch.call_args.args[0]
        self.assertLess(len(current),len(original))
        self.assertEqual(osm._simplify_corridor(points), [points[0],points[-1]])
        self.assertIn('around:210,', current)
        self.assertIn('[timeout:100]', current)
        self.assertNotIn('waste_basket', current)

    def test_original_sampling_misses_sharp_turn_current_preserves_it(self):
        points = [[-74+i/100000,40] for i in range(1000)]
        points[500] = [-73.995,40.01]
        self.assertNotIn('40.01,-73.995', self.original_query(points))
        with patch.object(osm,'fetch_overpass',return_value=[]) as fetch:
            osm.get_resources_along_route(points,200,'Restroom')
        self.assertIn('40.01,-73.995',fetch.call_args.args[0])

    def test_complex_route_rejected_without_network(self):
        points = [[-74+i/100000,40+(i%2)/1000] for i in range(600)]
        with patch.object(osm,'fetch_overpass') as fetch:
            with self.assertRaises(ServiceError): osm.get_resources_along_route(points,200,'Restroom')
        fetch.assert_not_called()

    def test_default_candidate_limit_eight(self):
        route={'duration':600,'distance':1000,'geometry':{'type':'LineString','coordinates':[[-74,40],[-73.99,40]]}}
        facilities=[{'id':f'node/{i}','type':'Restroom','name':'Test','latitude':40,'longitude':-74+i/10000} for i in range(12)]
        with patch.dict('os.environ', {'OPTIMIZER_MAX_CANDIDATES':'8'}), patch.object(optimizer,'get_route',return_value=route), patch.object(optimizer,'get_resources_along_route',return_value=facilities):
            result=optimizer.find_best_route(40,-74,40,-73.99,'Restroom')
        self.assertEqual(result['candidates_attempted'],8)
        self.assertTrue(result['candidate_limit_reached'])

    def test_nearby_union_matches_committed_original(self):
        import re
        original = {}
        exec(subprocess.check_output(['git','show','105b902:backend/osm_service.py'], text=True), original)
        queries = []
        original['fetch_overpass'] = lambda query: queries.append(query) or []
        original['get_resources'](40.7681,-73.9819,200)
        compact = lambda query: re.sub(r'\s+', '', query)
        self.assertEqual(compact(queries[0].replace('[timeout:25]', '[timeout:100]')),compact(osm._combined_query(40.7681,-73.9819,200)))
