"""Local browser integration server. External service boundaries are deterministic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest.mock import patch
import uvicorn
from backend import main, routing, osm_service


def mapbox(_method, _url, **kwargs):
    # Exercise real route parsing, snapping checks, cache and optimizer.
    text = _url.rsplit('/', 1)[-1]
    coordinates = [[float(n) for n in point.split(',')] for point in text.split(';')]
    via = len(coordinates) == 3
    return {'code':'Ok','routes':[{'distance':1100 if via else 1000,'duration':660 if via else 600,
            'geometry':{'type':'LineString','coordinates':coordinates}}],
            'waypoints':[{'distance':1,'location':p} for p in coordinates]}


def overpass(_method, _url, **kwargs):
    return {'elements':[{'type':'node','id':1,'lat':40.5005,'lon':-74.0005,
                         'tags':{'amenity':'waste_basket','name':'Integrated Campus Bin','access':'yes'}}]}


if __name__ == '__main__':
    with patch.object(routing,'MAPBOX_TOKEN','integration-placeholder'), patch.object(routing,'request_json',side_effect=mapbox), patch.object(osm_service,'request_json',side_effect=overpass):
        uvicorn.run(main.app,host='127.0.0.1',port=8011,log_level='error')
