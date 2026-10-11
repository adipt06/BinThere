"""Deterministic fixtures only; production snapshots are acquired separately."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import local_facilities as local, osm_service as osm, optimizer
from backend.main import app
from backend.scripts.build_snapshot import xml_elements
from backend.services import ServiceError


def snapshot():
    return {'schema_version':1,'name':'Explicit test fixture','bbox':[-74.1,39.9,-73.9,40.1],
            'categories':list(local.TYPES),'retrieved_at':'2026-01-01T00:00:00+00:00',
            'data_timestamp':'2025-12-31T23:00:00Z','license':'ODbL-1.0',
            'source':{'kind':'osm_extract','url':'https://example.invalid/test.osm','sha256':'a'*64},
            'facilities':[{'id':f'node/{index+1}','name':f'Test {category}','type':category,
                           'latitude':40.,'longitude':-74.+index*.0001,'metadata':{'access':'yes'},
                           'coordinate_source':'node','access_verified':False} for index,category in enumerate(local.TYPES)]}


class LocalFacilitiesTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'snapshot.json'
        self.data=snapshot()
        self.save()
        env=patch.dict('os.environ',{'LOCAL_FACILITIES_ENABLED':'true','LOCAL_FACILITIES_PATH':str(self.path),
                                   'OVERPASS_COMBINED_ENABLED':'false','FACILITY_DATA_MODE':'live_first'})
        env.start(); self.addCleanup(env.stop)
        osm.reset_overpass_state()
        self.addCleanup(osm.reset_overpass_state)
    def save(self): self.path.write_text(json.dumps(self.data))

    def test_failed_live_search_uses_verified_data_and_discloses_source(self):
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('upstream HTTP 500')):
            response=TestClient(app).get('/resources',params={'latitude':40,'longitude':-74,'radius':200,'include_metadata':True})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(len(data['facilities']),3)
        self.assertTrue(data['complete'])
        self.assertFalse(data['partial'])
        self.assertEqual(data['facilities'][0]['source']['kind'],'local_snapshot')
        self.assertIn('2026-01-01', ' '.join(data['warnings']))
        self.assertIn('stale', ' '.join(data['warnings']))
        self.assertEqual(data['categories']['Restroom']['source']['kind'],'local_snapshot')

    def test_live_success_is_preferred_even_if_successfully_empty(self):
        with patch.object(osm,'fetch_overpass',return_value=[]):
            result=osm.get_resources_report(40,-74,200)
        self.assertEqual(result['facilities'],[])
        self.assertEqual(result['warnings'],[])

    def test_partial_live_categories_are_preserved(self):
        live={**self.data['facilities'][0],'id':'node/999'}
        with patch.object(osm,'fetch_overpass',side_effect=[[live],ServiceError('failed'),[]]):
            result=osm.get_resources_report(40,-74,200)
        self.assertEqual({f['id'] for f in result['facilities']},{'node/999','node/2'})
        self.assertEqual(result['categories']['Recycling Location']['count'],0)

    def test_snapshot_does_not_pollute_live_success_cache(self):
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')):
            self.assertEqual(len(osm.get_resources_report(40,-74,200)['facilities']),3)
        osm._snapshot_fallback_until = 0  # Live requests resume after the fallback cooldown.
        with patch.object(osm,'fetch_overpass',return_value=[]) as fetch:
            self.assertEqual(osm.get_resources_report(40,-74,200)['facilities'],[])
        self.assertEqual(fetch.call_count,3)

    def test_partial_snapshot_discloses_incomplete_search_and_outside_fails(self):
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')):
            with self.assertRaises(ServiceError): osm.get_resources_report(41,-74,200)
            for latitude,longitude,radius in [(40,-74.0999,200),(40,-74,20000)]:
                result=osm.get_resources_report(latitude,longitude,radius)
                self.assertTrue(result['partial']); self.assertFalse(result['complete'])
                self.assertEqual(result['coverage'],'partial')
        self.assertIsNone(local.covering((0,179,1,-179)))

    def test_fallback_disabled_or_malformed_remains_failure(self):
        with patch.dict('os.environ',{'LOCAL_FACILITIES_ENABLED':'false'}), patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')):
            with self.assertRaises(ServiceError): osm.get_resources_report(40,-74,200)
        self.data['facilities'][0]['id']='invented'
        self.save()
        with self.assertLogs(local.logger,level='WARNING'), patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')):
            with self.assertRaises(ServiceError): osm.get_resources_report(40,-74,200)

    def test_corrupt_and_duplicate_snapshot_rejected(self):
        for mutate in [lambda d:d['facilities'].append(copy.deepcopy(d['facilities'][0])),
                       lambda d:d.update(retrieved_at='invalid'),lambda d:d['source'].update(sha256=''),
                       lambda d:d['facilities'][0].update(latitude=float('nan')),lambda d:d.update(categories=['Trash Bin'])]:
            data=snapshot(); mutate(data)
            with self.assertRaises((ValueError,TypeError)): local.validate_snapshot(data)

    def test_radius_and_category_filtering_and_legacy_array(self):
        self.data['facilities'][1]['latitude']=40.05
        self.save()
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')):
            report=osm.get_resources_report(40,-74,200,'Restroom')
            self.assertEqual(report['facilities'],[])
            self.assertEqual(report['categories']['Restroom']['count'],0)
            legacy=osm.get_resources(40,-74,200)
        self.assertIsInstance(legacy,list)
        self.assertEqual(len(legacy),2)

    def test_corridor_only_selected_category_and_full_buffer_coverage(self):
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')):
            result=osm.get_resources_along_route([[-74.001,40],[-73.999,40]],200,'Restroom')
            self.assertEqual([f['id'] for f in result],['node/2'])
            self.assertIn('not live',' '.join(result.warnings))
            partial=osm.get_resources_along_route([[-74.1,40],[-73.999,40]],200,'Restroom')
            self.assertFalse(partial.complete)
            self.assertIn('outside saved',' '.join(partial.warnings))

    def test_optimizer_uses_saved_facility_but_keeps_real_route_contract(self):
        direct={'duration':600,'distance':1000,'geometry':{'type':'LineString','coordinates':[[-74.001,40],[-73.999,40]]}}
        alternative={**direct,'duration':660,'distance':1100}
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')), patch.object(optimizer,'get_route',side_effect=[direct,alternative]):
            result=optimizer.find_best_route(40,-74.001,40,-73.999,'Restroom',max_detour_minutes=1)
        self.assertEqual(result['facility']['id'],'node/2')
        self.assertEqual(result['detour_seconds'],60)
        self.assertIn('saved OpenStreetMap',' '.join(result['warnings']))
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')), patch.object(optimizer,'get_route',side_effect=[direct,alternative]):
            result=optimizer.find_best_route(40,-74.001,40,-73.999,'Restroom',max_detour_minutes=0)
        self.assertIsNone(result['facility'])

    def test_default_discovery_uses_proven_node_body_query(self):
        with patch.object(osm,'fetch_overpass',return_value=[]) as fetch:
            osm.get_resources_report(40,-74,200)
        self.assertEqual(fetch.call_count,3)
        query=fetch.call_args_list[0].args[0]
        self.assertEqual(query,'[out:json][timeout:10];node["amenity"="waste_basket"](around:200,40,-74);out body;')

    def test_xml_import_preserves_area_metadata(self):
        source=Path(self.directory.name)/'extract.osm'
        source.write_text('<osm><node id="1" lat="40" lon="-74"/><node id="2" lat="40.001" lon="-74.001"/><way id="3"><nd ref="1"/><nd ref="2"/><tag k="amenity" v="toilets"/><tag k="wheelchair" v="yes"/></way></osm>')
        elements=xml_elements(source)
        self.assertEqual(elements[0]['type'],'way')
        self.assertEqual(elements[0]['center']['lat'],40.0005)
        self.assertEqual(elements[0]['tags']['wheelchair'],'yes')

    def test_old_extract_is_stale_even_if_recently_imported(self):
        from datetime import datetime, timezone
        self.data['retrieved_at']=datetime.now(timezone.utc).isoformat()
        self.data['data_timestamp']='2020-01-01T00:00:00Z'
        self.assertIn('stale',' '.join(local.warnings(self.data)))

    def test_download_failure_does_not_overwrite_existing_snapshot(self):
        from argparse import Namespace
        from backend.scripts.build_snapshot import build
        before=self.path.read_bytes()
        args=Namespace(bbox=[-74.01,39.99,-73.99,40.01],name='Test',output=str(self.path),input=None,source_url=None,data_timestamp=None)
        response=type('Response',(),{'status_code':500})()
        with patch('backend.scripts.build_snapshot.requests.post',return_value=response):
            with self.assertRaises(ValueError):build(args)
        self.assertEqual(self.path.read_bytes(),before)

    def test_committed_snapshot_matches_retained_source_checksum(self):
        import gzip, hashlib
        directory=Path(__file__).resolve().parents[1]/'data'
        data=local.validate_snapshot(json.loads((directory/'rutgers.json').read_text()))
        with gzip.open(directory/'rutgers.source.json.gz','rt') as handle:
            archive=json.load(handle)
        raw=b'\n'.join(payload.encode() for payload in archive['downloaded_payloads'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),data['source']['sha256'])
        extracted=json.loads(archive['downloaded_payloads'][0])
        original_ids={f"{e['type']}/{e['id']}" for e in extracted['elements']}
        self.assertEqual({f['id'] for f in data['facilities']},original_ids)
        self.assertEqual(extracted['sha256'],data['source']['extract_sha256'])
