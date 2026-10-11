# ReRoute: genuine 10-mile facility discovery

Implemented and verified on 2026-10-11. The existing snapshot loader, API, optimizer, Vite UI and Mapbox routing are retained.

## Actual acquisition and coverage

Reused the previously downloaded authentic Geofabrik New Jersey extract at `/tmp/reroute-new-jersey.osm.pbf`; no additional 156.6 MiB download was necessary. Original source: https://download.geofabrik.de/north-america/us/new-jersey-261009.osm.pbf . Its 164,165,911 bytes and MD5 `42ddf6a5f18c42447f5f5fa53f690d58` were verified against the provider checksum during acquisition. Embedded timestamp: `2026-10-09T20:21:04Z`. This task downloaded the authentic https://download.geofabrik.de/north-america/us/new-jersey.poly boundary and verified that the entire requested circle lies within it.

Generated `backend/data/resources_10mi.json` and `backend/data/resources_10mi.source.json.gz` using:

```sh
/tmp/reroute-snapshot-tools/bin/python -m backend.scripts.generate_resources --latitude 40.53399 --longitude -74.45793 --radius-miles 10
```

Validation confirmed **273 facilities: 128 Trash Bin, 60 Restroom, 85 Recycling Location**. All categories contain usable mapped coordinates. No facilities were fabricated. Original tags/IDs and source checksums are retained for audit. Dataset retrieval/build time: `2026-10-11T05:29:10.261149+00:00`; the source data remains dated October 9.

Coverage is the circle centered at approximate **latitude 40.53399, longitude -74.45793**, radius **16,093.44 meters / 10 miles**. This supplied Society Hill / Piscataway center is not verified current GPS. Envelope west/south/east/north: `[-74.64836155433552, 40.389258216944434, -74.26749844566449, 40.67872178305557]`. The rectangle's corners are not covered by the circle.

## Behavior

- `live_first`: existing paced, bounded live queries and per-category caching; failed categories fall back to genuine saved data without discarding successful live categories. Successful empty live searches remain empty successes. A 30-second saved-fallback cooldown prevents repeated live calls for fully covered searches after failure.
- `local_first`: immediately use saved data for full coverage; otherwise attempt live discovery and preserve useful partial saved results on failure. Configured in this workspace's backend `.env` and the example configuration.
- `local_only`: no Overpass requests. Full coverage is complete, overlap returns explicitly partial results, and outside/missing coverage returns 503 with `coverage: outside/unavailable`.
- Legacy `/resources` arrays remain available for complete searches. Incomplete searches require `include_metadata=true`, which the frontend already uses, rather than silently misleading old clients.
- Nearby and nearest-bin APIs support radii through 20,000 meters; frontend includes a 10-mile option. Facilities filter by actual distance and category, preserving metadata and provenance.
- Route corridor discovery shares the same validated dataset and handles full, partial, outside and crossing-circle routes. Optimizer queries only the requested category, keeps its ranking, live Mapbox candidate evaluation and detour constraint, and exposes incomplete coverage. It never claims global optimality.
- Saved cards/markers/details show their source; a concise notice and optional retrieval/coverage details distinguish saved from live. Empty saved searches retain source details. Partial results remain visible. Total failure deduplicates repeated upstream error text.
- Generator reuses cached extracts, downloads automatically when needed, verifies new download length/MD5/PBF timestamp, checks the source polygon, preserves real node/way/multipolygon relation records, filters by haversine radius, validates output and publishes via temporary files and atomic replacement. Download failure leaves existing datasets intact.

## Deterministic verification

Executed successfully:

```sh
.venv/bin/python -m unittest discover -s backend/tests
npm --prefix frontend test
npm --prefix frontend run test:browser
npm --prefix frontend run lint
npm --prefix frontend run build
```

Results: **113 backend tests**, **7 frontend unit tests**, **30 Chrome browser tests** passed; lint passed; production build passed. The build retains the existing large Mapbox bundle advisory. Tests cover fixture parsing/classification, nodes/ways/relations, tag preservation, radius/category filtering, deduplication, invalid metadata/counts/coordinates, retained source integrity, full/partial/outside circle and route coverage, missing data, all modes, no local-only Overpass calls, live recovery/cooldown, legacy compatibility, nearest-bin selection, no eligible facility, optimizer integration using actual dataset coordinates and mocked routing, stale-data warnings, failed download preservation and cached-extract reuse. Browser tests retain desktop/mobile navigation and add saved circle details, partial results and successfully empty saved searches. Tests do not download the regional PBF.

## Genuine API and Mapbox smoke tests

Started an unmocked backend, using configured real Mapbox credentials:

```sh
FACILITY_DATA_MODE=local_only .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8012 --log-level warning
```

All GET requests below used `http://127.0.0.1:8012`, with the exact query strings shown. Times are observed wall-clock seconds; they are not performance guarantees.

| Request | HTTP / seconds | Actual result |
| --- | --- | --- |
| `/resources?latitude=40.53399&longitude=-74.45793&radius=16093&include_metadata=true` | 200 / 0.024 | 273 records, full coverage, saved source |
| `/resources?latitude=40.678&longitude=-74.45793&radius=1000&include_metadata=true` | 200 / 0.003 | 0 records in covered overlap, explicitly partial/incomplete |
| `/resources?latitude=41&longitude=-74.45793&radius=1000&include_metadata=true` | 503 / 0.003 | Explicit outside coverage; not a complete empty success |
| `/nearest-bin?latitude=40.5085&longitude=-74.447&radius=300` | 200 / 0.003 | No mapped bin in this fully covered small radius; zero route candidates |
| `/nearest-bin?latitude=40.4948&longitude=-74.4439&radius=35` | 200 / 0.232 | Real bin `node/4449522017`; two candidates checked using live Mapbox; chosen route 9.883 seconds |

POST `/optimized-route` used this exact JSON:

```json
{"start_lat":40.5085,"start_lon":-74.447,"end_lat":40.5094,"end_lon":-74.4455,"facility_type":"Restroom","max_detour_minutes":5}
```

HTTP **200**, **0.183 seconds**; real saved restroom **`way/475732039`**, latitude **40.50885595**, longitude **-74.4464694**. Live Mapbox returned direct and via-restroom walking routes, each **420.569 meters / 301.754 seconds** (summary 420.57 meters / 5.03 minutes), **zero additional detour**. One candidate evaluated, full corridor coverage, five-minute maximum detour respected. The way coordinate is explicitly an area center, not a verified entrance.

Real Mapbox browser rendering check:

```sh
cd frontend
REROUTE_LOCAL_ONLY_SMOKE=true REROUTE_SMOKE_API=http://127.0.0.1:8012 node tests/live-facilities.mjs
```

HTTP **200** in **0.027 seconds**; **273 cards and 274 markers** (273 facilities plus starting marker), concise saved-OSM notice. Evidence: `/tmp/reroute-snapshot-facilities.json`, screenshot `/tmp/reroute-snapshot-facilities.png`; API smoke records: `/tmp/reroute-ten-mile-live.json`. This uses controlled supplied starting coordinates, genuine saved facilities and real Mapbox, not a GPS verification or live Overpass success.

The user's existing backend on port **8000** was also checked without restarting or stopping it: the same full-area `/resources` request returned **HTTP 200, local_first, 273 facilities, full coverage**. Only the temporary verification server was stopped after testing.

## Refresh and run

From repository root, install the optional generator dependencies in a Python environment with a compatible osmium wheel (Python 3.12 suggested; this workspace's existing `/tmp/reroute-snapshot-tools/bin/python` also works):

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-snapshot.txt
python -m backend.scripts.generate_resources --latitude 40.53399 --longitude -74.45793 --radius-miles 10
# Download a newer authenticated-source extract and rebuild:
python -m backend.scripts.generate_resources --latitude 40.53399 --longitude -74.45793 --radius-miles 10 --refresh
```

`--extract`, `--source-url`, `--source-polygon-url`, `--coverage-polygon`, `--output` and `--name` are supported. A circle outside New Jersey needs a complete larger/different source extract and its authentic coverage boundary; the generator refuses to misrepresent incomplete source coverage. Cache reuse does not refresh the source data timestamp.

Keep existing Mapbox tokens in their `.env` files. Set `FACILITY_DATA_MODE=local_first` (or `local_only`) in backend `.env`. Run:

```sh
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. Full initial environment setup is in the root README.

## Limits

The saved circle is finite and dated. OSM may omit actual infrastructure and may have incomplete access/opening-hours/accessibility tags. Missing tags imply nothing. Geometry centers may be unsuitable entrances; Mapbox snapping cannot verify accessibility. PBF facility relation handling covers multipolygon areas; all matching facility relations in this acquired New Jersey extract were multipolygons. General nested/non-area relations need additional geometry handling for other extracts. Live Mapbox and map tiles still require network access and credentials. Live-first can still wait for the existing bounded upstream discovery budget before fallback; local-first/local-only avoid that delay for covered areas. Existing public Overpass availability was not claimed repaired or repeatedly probed. Multiworker processes have separate short-lived live caches/cooldowns. Outputs are individually atomic files, not a transactional database.

Data © OpenStreetMap contributors, ODbL1.0: https://www.openstreetmap.org/copyright . Preserve attribution and license when sharing.
