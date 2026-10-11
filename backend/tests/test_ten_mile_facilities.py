"""Small explicit fixtures exercise offline behavior; committed data verifies provenance only."""
import copy
import gzip
import hashlib
import json
import unittest
import sys
from types import SimpleNamespace
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import local_facilities as local, osm_service as osm, optimizer
from backend.main import app
from backend.scripts.build_snapshot import build, xml_elements
from backend.scripts.generate_resources import obtain_extract, verify_source_coverage
from backend.services import ServiceError
from backend.tests import test_local_facilities as fixtures


class TenMileTests(unittest.TestCase):
    save = fixtures.LocalFacilitiesTests.save
    def setUp(self):
        fixtures.LocalFacilitiesTests.setUp(self)
        self.data['coverage']={'type':'circle','center':{'latitude':40.,'longitude':-74.},'radius_meters':1000,'approximate_center':True}
        self.save()

    def test_circle_classifies_full_partial_outside_and_bbox_corner(self):
        for lon,radius,wanted in [(-74,999,'full'),(-74,1001,'partial'),(-73.99,500,'partial'),(-73.9,100,'outside')]:
            self.assertEqual(local.nearby_coverage(self.data,40,lon,radius),wanted)
        self.assertIsNone(local.covering((40.008,-74.01,40.009,-74.009)))

    def test_local_modes_make_no_overpass_requests_in_full_coverage(self):
        for mode in ('local_first','local_only'):
            with patch.dict('os.environ',{'FACILITY_DATA_MODE':mode}), patch.object(osm,'fetch_overpass',side_effect=AssertionError('unexpected network')):
                data=osm.get_resources_report(40,-74,200)
                self.assertEqual(len(data['facilities']),3)
                self.assertTrue(data['complete']); self.assertEqual(data['data_mode'],mode)
                self.assertEqual(osm.get_resources_report(40,-74,200,'Restroom')['facilities'][0]['id'],'node/2')
                result=osm.get_resources_along_route([[-74.001,40],[-73.999,40]],200,'Restroom')
                self.assertTrue(result.complete); self.assertEqual(len(result),1)

    def test_local_only_partial_api_and_legacy_compatibility(self):
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only'}), patch.object(osm,'fetch_overpass',side_effect=AssertionError('network')):
            client=TestClient(app)
            result=client.get('/resources?latitude=40&longitude=-74&radius=1100&include_metadata=true').json()
            self.assertEqual(result['coverage'],'partial'); self.assertFalse(result['complete'])
            self.assertEqual(result['categories']['Restroom']['status'],'partial')
            self.assertEqual(len(result['facilities']),3)
            self.assertEqual(client.get('/resources?latitude=40&longitude=-74&radius=1100').status_code,503)
            self.assertIsInstance(client.get('/resources?latitude=40&longitude=-74&radius=200').json(),list)
            outside=client.get('/resources?latitude=41&longitude=-74&include_metadata=true')
            self.assertEqual(outside.status_code,503); self.assertEqual(outside.json()['coverage'],'outside')

    def test_local_only_missing_dataset_is_unavailable(self):
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only','LOCAL_FACILITIES_PATH':str(self.path)+'missing'}),patch.object(osm,'fetch_overpass',side_effect=AssertionError('network')):
            response=TestClient(app).get('/resources?latitude=40&longitude=-74&include_metadata=true')
            self.assertEqual(response.status_code,503);self.assertEqual(response.json()['coverage'],'unavailable')

    def test_fallback_cooldown_survives_different_location(self):
        with patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')) as fetch:
            osm.get_resources_report(40,-74,200)
            count=fetch.call_count
            data=osm.get_resources_report(40.0001,-74,200)
            self.assertEqual(fetch.call_count,count); self.assertEqual(len(data['facilities']),3)

    def test_partial_local_first_attempts_live_then_keeps_saved(self):
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_first'}), patch.object(osm,'fetch_overpass',side_effect=ServiceError('failed')) as fetch:
            data=osm.get_resources_report(40,-74,1100)
            self.assertTrue(fetch.called); self.assertEqual(len(data['facilities']),3)
            self.assertFalse(data['complete'])

    def test_route_crossing_circle_with_both_endpoints_outside(self):
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only'}),patch.object(osm,'fetch_overpass',side_effect=AssertionError('network')):
            data=osm.get_resources_along_route([[-74.02,40],[-73.98,40]],200,'Restroom')
            self.assertFalse(data.complete);self.assertEqual(len(data),1)
            with self.assertRaises(ServiceError):osm.get_resources_along_route([[-75,41],[-75.01,41.01]],200,'Restroom')

    def test_partial_optimizer_never_claims_complete(self):
        direct={'duration':600,'distance':1000,'geometry':{'type':'LineString','coordinates':[[-74.02,40],[-73.98,40]]}}
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only'}),patch.object(osm,'fetch_overpass',side_effect=AssertionError('network')),patch.object(optimizer,'get_route',return_value=direct):
            result=optimizer.find_best_route(40,-74.02,40,-73.98,'Restroom',1)
        self.assertIsNotNone(result['facility']);self.assertFalse(result['search_complete'])
        self.assertFalse(result['facility_search_complete']);self.assertEqual(result['coverage'],'partial')

    def test_nearest_local_bin_preserves_source_and_coverage(self):
        route={'duration':100,'distance':120,'geometry':{'type':'LineString','coordinates':[[-74.001,40],[-74,40]]}}
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only'}),patch('backend.main.get_route',return_value=route),patch.object(osm,'fetch_overpass',side_effect=AssertionError('network')):
            data=TestClient(app).get('/nearest-bin?latitude=40&longitude=-74&radius=200').json()
            self.assertEqual(data['facility']['id'],'node/1');self.assertEqual(data['coverage'],'full')
            self.assertEqual(data['facility']['source']['kind'],'local_snapshot')

    def test_no_eligible_local_facilities_is_valid_complete(self):
        self.data['facilities']=[];self.save()
        direct={'duration':600,'distance':1000,'geometry':{'type':'LineString','coordinates':[[-74.001,40],[-73.999,40]]}}
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only'}),patch.object(optimizer,'get_route',return_value=direct):
            result=optimizer.find_best_route(40,-74.001,40,-73.999,'Restroom',1)
        self.assertIsNone(result['facility']);self.assertTrue(result['search_complete'])

    def test_circle_rejects_outside_records_and_false_counts(self):
        for mutate in (lambda d:d['facilities'][0].update(latitude=40.05),lambda d:d.update(record_count=100),lambda d:d.update(counts={}),lambda d:d['coverage'].update(radius_meters=float('nan')),lambda d:d['facilities'][0].update(osm_tags={'amenity':'toilets'}),lambda d:d['facilities'][0].update(coordinate_source='area_center')):
            data=copy.deepcopy(self.data);mutate(data)
            with self.assertRaises(ValueError):local.validate_snapshot(data)

    def test_build_xml_nodes_ways_relations_tags_radius_and_dedup(self):
        source=Path(self.directory.name)/'fixture.osm'
        source.write_text('''<osm><node id="1" lat="40" lon="-74"><tag k="amenity" v="waste_basket"/></node><node id="2" lat="40.001" lon="-74.001"/><node id="4" lat="40.05" lon="-74"><tag k="amenity" v="recycling"/></node><way id="3"><nd ref="1"/><nd ref="2"/><tag k="amenity" v="toilets"/><tag k="access" v="customers"/><tag k="opening_hours" v="24/7"/></way><relation id="5"><member type="way" ref="3" role="outer"/><tag k="amenity" v="recycling"/><tag k="recycling:glass" v="yes"/><tag k="operator" v="Fixture"/></relation></osm>''')
        args=Namespace(bbox=self.data['bbox'],name='Explicit fixture',output=str(self.path),input=str(source),source_url='https://example.invalid/fixture.osm',data_timestamp='2026-01-01T00:00:00Z',center=[40,-74],radius_meters=1000)
        result=build(args)
        self.assertEqual({f['id'] for f in result['facilities']},{'node/1','way/3','relation/5'})
        relation=next(f for f in result['facilities'] if f['id']=='relation/5')
        self.assertEqual(relation['coordinate_source'],'area_center')
        self.assertEqual(relation['osm_tags']['recycling:glass'],'yes')
        self.assertEqual(relation['metadata']['operator'],'Fixture')
        elements=xml_elements(source)
        self.assertEqual(len(osm._parse_resources({'elements':elements+elements})),4)

    def test_extract_boundary_rejects_incomplete_circle(self):
        poly=Path(self.directory.name)/'fixture.poly'
        poly.write_text('Fixture\n1\n -74.1 39.9\n -73.9 39.9\n -73.9 40.1\n -74.1 40.1\n -74.1 39.9\nEND\nEND\n')
        verify_source_coverage(poly,40,-74,1000)
        with self.assertRaises(ValueError):verify_source_coverage(poly,40,-74,20000)
        with self.assertRaises(ValueError):verify_source_coverage(poly,41,-74,100)

    def test_committed_ten_mile_dataset_integrity_and_real_coordinate_optimizer(self):
        path=Path(__file__).resolve().parents[1]/'data'/'resources_10mi.json'
        data=local.validate_snapshot(json.loads(path.read_text()))
        self.assertEqual(data['record_count'],273)
        self.assertEqual(data['counts'],{'Trash Bin':128,'Restroom':60,'Recycling Location':85})
        self.assertEqual(data['coverage']['radius_meters'],16093.44)
        with gzip.open(path.with_suffix('.source.json.gz'),'rt') as handle:archive=json.load(handle)
        raw=b'\n'.join(p.encode() for p in archive['downloaded_payloads'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),data['source']['sha256'])
        original=json.loads(archive['downloaded_payloads'][0])
        self.assertTrue({f['id'] for f in data['facilities']} <= {f"{e['type']}/{e['id']}" for e in original['elements']})
        rest=next(f for f in data['facilities'] if f['type']=='Restroom' and f['metadata'].get('access') not in ('private','no'))
        lon,lat=rest['longitude'],rest['latitude']
        direct={'duration':600,'distance':1000,'geometry':{'type':'LineString','coordinates':[[lon-.001,lat],[lon+.001,lat]]}}
        with patch.dict('os.environ',{'FACILITY_DATA_MODE':'local_only','LOCAL_FACILITIES_PATH':str(path)}),patch.object(optimizer,'get_route',return_value=direct),patch.object(osm,'fetch_overpass',side_effect=AssertionError('network')):
            result=optimizer.find_best_route(lat,lon-.001,lat,lon+.001,'Restroom',1)
        self.assertIsNotNone(result['facility']);self.assertFalse(result['globally_optimal'])


    def test_incomplete_extract_download_preserves_previous_file(self):
        path=Path(self.directory.name)/'cached.osm.pbf';path.write_bytes(b'previous verified extract')
        response=SimpleNamespace(headers={'Content-Length':'100'},raise_for_status=lambda:None,iter_content=lambda n:iter([b'truncated']))
        with patch.dict(sys.modules,{'osmium':SimpleNamespace()}),patch('backend.scripts.generate_resources.requests.get',return_value=response):
            with self.assertRaises(ValueError):obtain_extract(path,'https://example.invalid/source.osm.pbf',refresh=True)
        self.assertEqual(path.read_bytes(),b'previous verified extract')
        self.assertFalse(path.with_name(path.name+'.download.osm.pbf').exists())

    def test_cached_pbf_requires_no_download(self):
        path=Path(self.directory.name)/'cached.osm.pbf';path.write_bytes(b'explicit fixture')
        reader=SimpleNamespace(header=lambda:{'osmosis_replication_timestamp':'2026-01-01T00:00:00Z'},close=lambda:None)
        module=SimpleNamespace(io=SimpleNamespace(Reader=lambda path:reader))
        with patch.dict(sys.modules,{'osmium':module}),patch('backend.scripts.generate_resources.requests.get',side_effect=AssertionError('download')):
            actual,stamp,metadata=obtain_extract(path,'https://example.invalid/source.osm.pbf')
        self.assertEqual(actual,path);self.assertEqual(stamp,'2026-01-01T00:00:00Z')
