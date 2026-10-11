"""Explicit local smoke server: genuine saved OSM and real Mapbox, forced Overpass failure.
Run only for verification: python -m backend.tests.snapshot_smoke_server (port8012).
This is not a fully live Overpass test. No facilities or Mapbox routes are mocked.
"""
from unittest.mock import patch
import uvicorn
from backend import main, osm_service
from backend.services import ServiceError

if __name__ == '__main__':
    with patch.object(osm_service,'fetch_overpass',side_effect=ServiceError('Overpass deliberately disabled for snapshot smoke test.',503)):
        uvicorn.run(main.app,host='127.0.0.1',port=8012,log_level='warning')
