# ReRoute — Smart Navigation

A FastAPI + vanilla JavaScript/Vite application with a full-screen Mapbox map. Discover real OpenStreetMap trash bins, recycling locations, and restrooms; compare direct walking directions with a route through a requested facility.

## Reliable 10-mile facility discovery

The included [resources_10mi.json](backend/data/resources_10mi.json) contains **273 genuine OSM facilities: 128 trash bins, 60 restrooms, 85 recycling locations**. Its coverage is a circle of radius **16,093.44 meters** centered at **40.53399, -74.45793**, an **approximate Society Hill / Piscataway center, not verified current GPS**. The bounding rectangle is an envelope, not additional coverage. Data timestamp: `2026-10-09T20:21:04Z`; generated/retrieved: `2026-10-11T05:29:10.261149+00:00`. See [dataset provenance](backend/data/README.md) and [verification report](TEN_MILE_FACILITIES_REPORT.md).

Set `FACILITY_DATA_MODE=local_first` in `backend/.env` for the demo, or `local_only` to disable Overpass entirely. Restart FastAPI after changing environment settings. Mapbox Directions and the map still require network access and valid configured tokens. The frontend offers a 10-mile search radius, saved-data notices, expandable source/coverage details and partial-coverage warnings. `/resources` and `/nearest-bin` accept radii up to 20,000 meters. Existing API fields, frontend features and optimization ranking remain intact.

Regenerate from the repository root using a Python environment with the optional PBF importer installed:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-snapshot.txt
python -m backend.scripts.generate_resources --latitude 40.53399 --longitude -74.45793 --radius-miles 10
# Force a fresh, checksum-verified regional download:
python -m backend.scripts.generate_resources --latitude 40.53399 --longitude -74.45793 --radius-miles 10 --refresh
```

The command downloads the authentic Geofabrik New Jersey PBF and boundary automatically if needed, or reuses a cached extract. New downloads are validated against provider MD5 and the embedded PBF timestamp; generation parses geometry, filters representative coordinates by haversine radius, preserves tags/IDs, validates counts and atomically replaces output files. The complete circle must lie inside the source polygon; other locations may need `--source-url`, `--source-polygon-url` or `--coverage-polygon` for another complete regional extract. Arbitrary filtered extracts do not establish complete coverage. `--extract`, `--output` and `--name` are configurable. `--refresh` is required to obtain newer source data; rebuilding from cache does not make the OSM data newer. Pyosmium wheels may be unavailable for Python 3.15: use Python 3.12 (or the compatible existing `/tmp/reroute-snapshot-tools/bin/python` in this workspace) for generation; the FastAPI runtime needs no osmium package.

All nodes, relevant ways and multipolygon facility relations are parsed. Area coordinates are geometry bounding-box centers, **not entrances**. Dataset completeness means the extract was searched within that boundary; it does not establish that OSM maps every real facility or verify access, accessibility or opening hours. Original relevant tags are retained as `osm_tags`; absent tags imply nothing. Legacy `rutgers.json` remains usable; the loader prefers a fully covering snapshot, newest first, before falling back to partial coverage.

To reproduce the real saved-data browser check, run a local-only backend on a spare port:

```sh
FACILITY_DATA_MODE=local_only .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8012
# In another terminal:
cd frontend
REROUTE_LOCAL_ONLY_SMOKE=true REROUTE_SMOKE_API=http://127.0.0.1:8012 node tests/live-facilities.mjs
```

## Run locally

Use Python 3.11+ and a Node release supported by Vite 8 (Node 22.12+ or 24 recommended).

From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env
```

Edit both environment files with your own Mapbox tokens. Do not overwrite existing configured `.env` files. Run the backend from the root:

```sh
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Backend docs: http://localhost:8000/docs. Launching `uvicorn main:app` from `backend/` also works.

## Configuration and deployment

- `MAPBOX_TOKEN`: backend token for Directions and Search Box API. An account/token with access to those APIs is required. Keep it on the backend; use token restrictions appropriate to server requests.
- `VITE_MAPBOX_TOKEN`: public `pk.` token for map/style loading. Allow the development, LAN, and deployed frontend URLs in its URL restrictions. Never put a secret token into a `VITE_` variable.
- `VITE_API_BASE_URL`: defaults to `/api`. Vite proxies it to port 8000 during development and preview. For production, configure your hosting reverse proxy to send `/api/*` to FastAPI with the `/api` prefix removed, or build with an absolute HTTPS backend URL.
- `CORS_ORIGINS`: comma-separated frontend origins. Defaults cover localhost development and preview. Add the deployed frontend origin for a separate backend. The same-origin Vite proxy does not require adding LAN origins.
- Overpass URL, fallback URL, cache TTL, snapping tolerance, candidate limits, corridor cap, and optimizer time budget are documented in `backend/.env.example`.
- Environment changes require restarting the backend/Vite; frontend variables are embedded at build time.

For phone testing, visit `http://YOUR_COMPUTER_LAN_IP:5173` on the same Wi-Fi. Vite binds all interfaces and proxies API requests through the computer. Plain HTTP on a LAN generally cannot use browser GPS: manual map selection/address search remain available. Use an HTTPS development tunnel or trusted local HTTPS for phone GPS. Ensure the firewall permits the Vite port.

Build with `npm run build` inside `frontend`. Serve `frontend/dist` with SPA/static hosting and the API configuration described above. `npm run preview` tests the build locally; it is not the production server.

## Navigation

1. Use GPS, pick a blue start marker on the map, or submit a starting address/place search.
2. Select a red destination with map selection or a separate destination search.
3. Get a direct walking route (blue), or select a desired stop and detour limit to optimize (green).
4. Inspect facility details, OSM metadata, route comparison, and search warnings. An orange marker highlights the recommendation.
5. Clear displayed route retains trip locations. Clear destination removes its marker and route. Reset trip cancels requests and removes all trip/facility markers.

Place search uses Mapbox Search Box `/forward` on explicit form submission, supporting addresses and points of interest. Results are used in the current interface only, not persisted or cached. Coverage depends on Mapbox's supported regions. Nearby-facility text filtering is a separate control.

## API contracts

Existing endpoints are preserved:

- `GET /health`: status and `mapbox_configured` (configuration presence, not upstream readiness).
- `GET /resources?latitude=…&longitude=…&radius=1000`: array with existing `id/name/type/latitude/longitude` fields, plus `metadata`, `coordinate_source`, and `access_verified: false`.
- `GET /route?start_lat=…&start_lon=…&end_lat=…&end_lon=…`: distance in meters, duration in seconds, GeoJSON LineString, waypoints, and warnings.
- `POST /optimized-route`: existing start/end fields, exact facility type (`Trash Bin`, `Restroom`, `Recycling Location`), and `max_detour_minutes` (0–30). Existing summary/direct/optimized/facility fields remain. Added warnings, attempted/found/failure counts, search radius, completeness flags, and `globally_optimal: false`.
- `GET /search?q=…`: address/POI results and attribution; optional latitude/longitude proximity.
- `GET /nearest-bin?latitude=…&longitude=…&radius=1000`: shortest walking time among a bounded set of nearby bin candidates, returned route, and limitations.

Expected errors are sanitized JSON `detail` messages: 422 invalid inputs, 404 no walking route, 502 upstream/schema failure, 503 missing/rejected credentials, 504 timeout. An optimization with a valid direct route can return HTTP 200 with explicit warnings and that direct route when the facility search fails. This is distinguished from a successful empty facility search.

## Optimization limits

The optimizer keeps every route vertex in its Overpass corridor, scales corridor width with detour time, and interleaves candidates ranked by distance to the path and approximate start–facility–destination distance. It checks actual walking routes, skips private/no-access facilities, rejects excessive snapping, and selects minimum duration among eligible evaluated candidates. Defaults: up to 8 candidates (configurable), 45-second approximate total budget, 2 km corridor cap. A currently running upstream request can extend the approximate deadline by connection/read overhead. Large routes above 20,000 vertices are explicitly declined for optimization, retaining the direct route.

This is a bounded heuristic, not a global optimum or exhaustive accessibility check. OSM coverage, area centers, barriers, entrances, opening hours, and access metadata can be incomplete or outdated. Snapping within 50 meters does not establish entrance accessibility. Unroutable candidates, limits, and service failures are exposed in results. Extra distance is a signed difference; a faster/shorter alternative can differ from the original direct result. Time detour is clamped at zero.

Caches are short-lived, bounded, per-process memory caches; they do not persist between restarts or coordinate separate workers. Browser cancellation prevents stale rendering but cannot forcibly stop synchronous upstream work already running in FastAPI. Public Overpass services may throttle requests; Private.coffee is the default primary and overpass-api.de is the fallback. Legacy Kumi URLs are migrated to the current hostname. `OVERPASS_ENDPOINTS` optionally replaces this pair with up to three ordered compatible instances. Failed endpoints cool down for 30 seconds (at least 60 seconds for throttling, honoring Retry-After), and the last successful endpoint is preferred. Cache misses are serialized, duplicate requests are coalesced, and outgoing requests are spaced at least one second apart. Failures are briefly memoized separately from valid empty results. Nearby queries use independent exact-tag category requests by default (the circular union is opt-in), followed by an exact distance postfilter; route queries simplify within a 10 m local-plane tolerance, pad the radius by 10 m, and cap at 256 vertices. Routing and ranking retain the full geometry. See [OVERPASS_DIAGNOSTICS.md](OVERPASS_DIAGNOSTICS.md) for live investigation results.

## Tests

```sh
.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend
npm test
npm run lint
npm run build
npx playwright install chromium
npm run test:browser
```

Alternatively use installed Chrome: `PLAYWRIGHT_CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:browser`.

Backend tests mock external APIs. Browser tests run the actual DOM and frontend application in Chrome/Chromium with a deterministic Mapbox adapter and mocked HTTP responses; they do **not** verify real Mapbox tiles, WebGL, or live pedestrian paths. They require no real token and do not query public mapping services. Node tests cover request invalidation, coordinates, route validation, and filtering. See `IMPLEMENTATION.md` for executed results and audit mapping.

## Manual demo checklist

- Load real map tiles; test both allowed and denied GPS, then select a manual start.
- Search a starting address and destination; also test map selection and Cancel.
- Check all three OSM categories, radii, name filtering, card/marker details, and facility walking directions.
- Compare direct versus optimized routes; test zero, small, and large detour limits and a no-facility corridor.
- Change endpoints/radius during requests; confirm old responses never draw or repopulate results.
- Clear route, clear destination, reset, and request GPS again; verify marker cleanup.
- Simulate offline/API failures and retry; verify loading controls recover.
- On a phone, collapse/expand the panel, cancel map selection, pan/zoom, and inspect fitted routes.


Facility discovery supports `/resources?latitude=...&longitude=...&radius=...&include_metadata=true` for partial results and explicit per-category failure/coverage warnings. Optional `facility_type=Trash%20Bin` selects one category. The frontend uses metadata mode. Complete legacy responses remain arrays; incomplete legacy searches return 503 rather than silently presenting partial coverage as complete. Nearby fallback searches default to a bounded 200 m radius and disclose reduced coverage. See [live diagnostics](OVERPASS_DIAGNOSTICS.md) for exact requests and current public-service limitations.

## Genuine OSM snapshot fallback

`FACILITY_DATA_MODE` selects `live_first` (the code default), `local_first` (the supplied example and this workspace’s demo setting), or `local_only`. In live-first mode, nearby discovery uses independent category requests by default. Trash bins use the proven `node["amenity"="waste_basket"](around:...)` / `out body` form with a10-second Overpass execution limit; HTTP read allowance remains100 seconds. Restrooms/recycling retain `nwr` and area centers. Set `OVERPASS_COMBINED_ENABLED=true` to opt into the original combined query. Category fallback still defaults to200m and warns about reduced live coverage.

If a category's live request fails, the backend uses a validated local snapshot when coverage overlaps. Successful live categories (including successful empty responses) are preserved. Full-circle coverage is required for `complete: true`; overlapping searches return useful partial records with warnings. Route corridors use the same full/partial/outside distinction, including routes crossing the saved circle with endpoints outside it. Entirely uncovered local-only searches return 503 with `coverage: outside` (or `unavailable` for missing data), rather than a misleading empty success. Local-first uses saved data immediately for full coverage, and otherwise attempts live discovery before partial fallback. Local-only never contacts Overpass. After live failure, fully covered searches use saved results during a 30-second cooldown. The optimizer and walking-time nearest-bin selection still use Mapbox walking routes; candidate evaluation has a separate45-second budget after facility discovery.

Saved facilities and category states include source information, OSM IDs, metadata, retrieval timestamps and coverage. The frontend labels saved cards/details and displays source, upstream-failure and stale-data warnings. `complete`/`partial` describe geographic/category coverage, not whether data is current. A complete snapshot response may therefore have warnings. Legacy `/resources` keeps its array response for fully covered searches, with additive per-facility source metadata; use `include_metadata=true` to receive full warning details. Total live failure without valid local coverage remains503, never a fabricated empty list.

Configuration (backend `.env`, examples in `backend/.env.example`):

```dotenv
FACILITY_DATA_MODE=local_first
LOCAL_FACILITIES_ENABLED=true
# Omit to use backend/data automatically; relative paths resolve from repository root.
LOCAL_FACILITIES_PATH=backend/data
LOCAL_FACILITIES_STALE_DAYS=7
OVERPASS_COMBINED_ENABLED=false
```

Only successfully acquired data is published. Snapshot files contain `bbox` in west/south/east/north order, all three category searches, source URL/checksums, OSM data/retrieval dates, attribution and license. Source payloads are retained in a compressed companion file for review. The runtime validates files and ignores malformed ones. Files are reread during fallback so a refreshed snapshot takes effect without a restart; saved data is not put into the live-success cache.

To refresh a **small area** while Overpass is healthy (three paced requests, no retries; stops on the first failure):

```sh
.venv/bin/python -m backend.scripts.build_snapshot \
  --bbox -74.48 40.475 -74.415 40.535 \
  --name 'Rutgers and New Brunswick' --output backend/data/rutgers.json
```

If public Overpass fails, download a legitimate regional extract from [Geofabrik](https://download.geofabrik.de/north-america/us/new-jersey.html). `.osm`/`.xml` and complete Overpass JSON imports use existing dependencies. PBF imports require the **optional build-only** `osmium` package:

```sh
# Use a Python version with a published osmium wheel (e.g. Python3.12); current Python3.15 may lack one.
python3.12 -m venv /tmp/reroute-snapshot-tools
/tmp/reroute-snapshot-tools/bin/pip install -r backend/requirements.txt -r backend/requirements-snapshot.txt
curl -L --fail --output /tmp/new-jersey.osm.pbf \
  https://download.geofabrik.de/north-america/us/new-jersey-latest.osm.pbf
# Read the extract's actual timestamp; do not assume it equals today's date.
/tmp/reroute-snapshot-tools/bin/python -c "import osmium; r=osmium.io.Reader('/tmp/new-jersey.osm.pbf'); print(r.header().get('osmosis_replication_timestamp')); r.close()"
/tmp/reroute-snapshot-tools/bin/python -m backend.scripts.build_snapshot \
  --input /tmp/new-jersey.osm.pbf --source-url https://download.geofabrik.de/north-america/us/new-jersey-latest.osm.pbf \
  --data-timestamp REPLACE_WITH_EXTRACT_TIMESTAMP \
  --bbox -74.48 40.475 -74.415 40.535 \
  --name 'Rutgers and New Brunswick' --output backend/data/rutgers.json
```

For any imported extract, the operator must verify the declared bbox is fully inside the extract's actual coverage and that the input includes every category, referenced node geometry and relation members. Arbitrary filtered files cannot establish complete coverage. The script validates resulting records, rejects malformed/incomplete facility geometry, filters to the bbox, and atomically replaces the snapshot only after successful validation. PBF parsing uses pyosmium to retain real node/way/relation IDs and derive area bounding-box centers, which may differ from entrances. Regional PBF files can be large; retain the download outside Git. If necessary, resume a static versioned download with `curl --continue-at -` and verify the published checksum.

Snapshot data is © OpenStreetMap contributors, under the [Open Database License](https://www.openstreetmap.org/copyright). Preserve this attribution and the license when sharing data. Snapshots represent saved OSM mapping, not verified real-time access/opening hours. New Jersey files do not cover Manhattan. No snapshot is generated when acquisition or validation fails.

Testing a configured backend:

```sh
curl 'http://127.0.0.1:8000/resources?latitude=40.5008&longitude=-74.4474&radius=1000&include_metadata=true'
.venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend test
npm --prefix frontend run test:browser
npm --prefix frontend run lint
npm --prefix frontend run build
```

The deterministic snapshot tests explicitly force upstream failure, test full-circle/corridor boundaries, category/radius filters, stale warnings, live preference/recovery, invalid files, legacy response compatibility and optimization with saved facilities. They do not claim live third-party success. See the latest delivery report for downloaded counts and real integration outcomes.


To reproduce the saved-data workflow without sending Overpass requests, run the explicit verification server in a separate terminal:

```sh
.venv/bin/python -m backend.tests.snapshot_smoke_server
# In another terminal, launch the real Mapbox browser check against that test server:
cd frontend
REROUTE_SNAPSHOT_SMOKE=true REROUTE_SMOKE_API=http://127.0.0.1:8012 node tests/live-facilities.mjs
```

This forces only Overpass failure; it uses the actual included snapshot and real Mapbox. It is a saved-data/real-routing check, not a fully live Overpass success. Stop the test server after verification. Ordinary `.env` and port8000 behavior are unaffected. Route discovery also has a100-second aggregate budget before trying local fallback, so several slow providers cannot delay it indefinitely.

Latest implementation, real-data counts, coverage and test outcomes: [FACILITY_RECOVERY_REPORT.md](FACILITY_RECOVERY_REPORT.md).
