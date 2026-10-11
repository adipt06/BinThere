# BinThere intensive verification — 2026-10-11

Production code was unchanged during this run. Added `backend/tests/test_discovery_matrix.py` for broader offline verification. No credentials were logged and no production facilities were fabricated.

## Automated results

- 82 backend unittest tests passed, including 36 location/radius/category subcases (equatorial/date-line, New York, near-pole; radii1/200/1000/5000m; all three categories), all eight category success/failure combinations, partial API contracts and legacy explicit failure.
- 24 simultaneous identical cold-cache queries coalesced to one mocked upstream request. Another24 identical failing queries also made only one mocked upstream request. Cached objects remained isolated from caller mutation.
- Confirmed100-second default Overpass read timeout, remaining-budget clipping,100-second QL queries and no network attempt after budget exhaustion.
- Existing failure, schema, retry/cooldown, deduplication, metadata, geometry/corridor, optimizer, validation and caching tests passed.
- 7 frontend unit tests passed.
- 27 Chrome browser tests passed, including navigation, location selection, cancellation, stale response handling, category filtering, partial markers/cards, failures, mobile behavior and FastAPI integration. These browser facility/route checks use declared fixtures.
- Production build and lint passed. Existing nonfatal Mapbox bundle-size warning remains.
- Real Mapbox/WebGL browser smoke passed: map loaded, GPS denial left manual selection enabled. Screenshot: `/tmp/reroute-live-map.png`. This smoke does not claim live facility rendering.

## Limited real API checks

Target: running user backend `http://127.0.0.1:8000`. Requests were sequential; no public-service load test. Warm-cache/concurrency/legacy/selected-category live checks were conditional on successful initial discovery and were skipped after failure. A live optimized-route call was also skipped to avoid an additional expensive corridor query during upstream failure; mocked optimization coverage passed.

| Check | API status | Elapsed |
|---|---|---|
| health | 200 | 0.01s |
| invalid resources | 422 | 0.003s |
| invalid resources | 422 | 0.001s |
| invalid resources | 422 | 0.001s |
| invalid resources | 422 | 0.001s |
| live discovery | 503 | 14.595s |
| live direct walking route | 200 | 0.177s |
| live address search | 200 | 0.268s |

Exact request parameters and relevant outcomes:

- `/health` parameters: `null`. 
- `/resources` parameters: `{"latitude": 91, "longitude": -74}`. 
- `/resources` parameters: `{"latitude": 40, "longitude": -181}`. 
- `/resources` parameters: `{"latitude": 40, "longitude": -74, "radius": 0}`. 
- `/resources` parameters: `{"latitude": 40, "longitude": -74, "radius": 5001}`. 
- `/resources` parameters: `{"include_metadata": "true", "latitude": 40.7681, "longitude": -73.9819, "radius": 200}`. All requested facility categories failed. Trash Bin could not be loaded: Facility service unavailable (overpass-api.de: HTTP 504 (cooling down); overpass.private.coffee: HTTP 500). Please retry shortly. Restroom could not be loaded: Facility service unavailable (overpass-api.de: HTTP 504 (cooling down); overpass.private.coffee: HTTP 500). Please retry shortly. Recycling Location could not be loaded: Facility service unavailable (overpass-api.de: HTTP 504 (cooling down); overpass.private.coffee: HTTP 500). Please retry shortly.
- `/route` parameters: `{"end_lat": 40.7715, "end_lon": -73.9788, "start_lat": 40.7681, "start_lon": -73.9819}`. Distance 576.911m; duration 397.948s; valid LineString with 54 coordinates.
- `/search` parameters: `{"latitude": 40.7681, "longitude": -73.9819, "q": "Columbus Circle New York"}`. 5 real search results.

The facility API returned503 in14.595 seconds, reporting Private.coffee HTTP500 for every category and overpass-api.de HTTP504/cooldown. These upstream outcomes are reported by the real backend; this run did not independently instrument the exact upstream request count or timings. The prior live200 with10 bins and5 restrooms is historical and was not reproduced in this run. A100-second timeout therefore does not by itself guarantee service availability. No automatic repeated live probes were made after this failure.

## Remaining limits

Current live facility availability is intermittent, so end-to-end live optimization and live facility markers could not be confirmed in this run. Offline tests cannot establish public-service uptime. Cache/cooldown coordination is process-local; multiple production workers need shared coordination.100-second request timeouts can leave UI requests waiting a long time; concurrent callers may also wait for the serialized upstream lock. Tests verify bounds and stale-result handling, not a production throughput guarantee.
