# Reliable facility discovery delivery — 2026-10-11

## Root-cause evidence

An exact internal upstream root cause is **not established**. The requested previously successful query was tested once against the configured primary (Private.coffee), form-encoded POST, application User-Agent, connect3/read15 seconds. It returned HTTP200 in0.713 seconds with10 genuine mapped bins and JSON content. No alternate was probed after that success.

```overpass
[out:json][timeout:10];
node["amenity"="waste_basket"](around:200,40.7681,-73.9819);
out body;
```

A larger Rutgers snapshot acquisition request subsequently returned generic HTTP500 in0.51s, and the importer stopped without writing anything. A later small application/browser search also failed: Private.coffee500, overpass-api.de504, API503 in12.149s. Previous GET/POST, node/nwr and timeout comparisons are preserved in the earlier diagnostics. Subsecond generic server errors do not establish a QL timeout or parse error. The fact that identical semantics work intermittently is consistent with unstable provider/gateway behavior, but a specific server-side cause is unknown. Valid JSON facility responses are parsed as successes, valid empties stay empty, and failed requests remain failures. Caches/cooldowns are short-lived and do not account for direct uncached HTTP failures.

## Changes

- Default nearby discovery uses three independent exact-tag queries instead of the more expensive combined query. Bins use node-only/out body with the proven10-second QL execution limit; restroom/recycling retain nwr/area-center handling. Existing100-second HTTP allowance, request budget, pacing, bounded failover and cache behavior remain. Route discovery also uses a100-second aggregate budget across at most three endpoint attempts before falling back. Combined queries remain opt-in through `OVERPASS_COMBINED_ENABLED`.
- `backend/local_facilities.py` validates optional genuine JSON snapshots. On live category failure, it serves saved facilities only when the whole requested circle fits inside one snapshot. Successful live categories are preserved, including empty ones. Route fallback requires the full original route plus corridor buffer within coverage and filters saved facilities by distance to segments and selected category.
- Snapshot fallback does not poison the live-success cache; new live attempts can recover subject to the existing cooldowns. Files are reloaded on fallback so refreshes take effect without restart. `LOCAL_FACILITIES_ENABLED`, `LOCAL_FACILITIES_PATH` and `LOCAL_FACILITIES_STALE_DAYS` configure behavior.
- Added additive facility/category source fields, retrieval/data timestamps, licensing and source/stale warnings. Complete coverage with saved data can still have warnings; legacy arrays remain available for fully covered results. Frontend cards/details label saved data; facility/route warnings show provenance and age. Existing map, searches, comparisons, cancellation and marker cleanup remain.
- Candidate-route evaluation reserves its45-second budget after discovery so a slow failed live search cannot consume all time before snapshot candidates are evaluated. Optimized-route browser requests allow180s, other API calls110s. Mapbox walking routing, detour enforcement and optimization ranking are retained.
- `backend/scripts/build_snapshot.py` acquires three paced small-area Overpass searches, or imports authorized complete OSM XML/JSON/PBF extracts. Only validated data is atomically published. Failed imports preserve the previous snapshot. Optional PBF parsing uses build-only pyosmium; no runtime dependency was added to FastAPI.

## Genuine snapshot obtained

`backend/data/rutgers.json` and its compressed retained source payload are included. The New Jersey extract was downloaded from:
https://download.geofabrik.de/north-america/us/new-jersey-261009.osm.pbf

The resumed download matched Geofabrik's published MD5 (`42ddf6a5f18c42447f5f5fa53f690d58`). PBF header timestamp was2026-10-09T20:21:04Z. Snapshot/source payload checksums and original-extract SHA256 are retained. Optional pyosmium4.3.1 was used in an isolated Python3.9 tool environment because Python3.15 currently has no compatible binary wheel. FastAPI still uses the original project environment.

Snapshot generated: `2026-10-11T05:14:51.584141+00:00`.

| Category | Actual downloaded facilities |
|---|---:|
| Trash Bin | 26 |
| Restroom | 6 |
| Recycling Location | 12 |

Coverage: west-74.48, south40.475, east-74.415, north40.535, a rectangle wholly within New Jersey around Rutgers/New Brunswick. This is not Manhattan, all New Jersey or every Rutgers campus. All requested search/corridor bounds must fit inside it. OSM mapping, entrance positions, accessibility and opening hours are not independently ground-truthed. This is genuine OSM data, not invented sample locations. Licensing: © OpenStreetMap contributors, ODbL1.0; preserve attribution/source/license.

## Actual production fallback

The running user API on port8000 was called once with no mocked network boundary:

```text
GET /resources?latitude=40.5008&longitude=-74.4474&radius=1000&include_metadata=true
```

It returned HTTP200 in16.385s. Trash-bin live discovery succeeded empty within its bounded200m radius; restroom/recycling live searches failed (Private.coffee500, overpass-api.de504) and automatically used the saved snapshot. One genuine saved restroom was returned. Recycling was genuinely empty within1000m. Because live bin coverage was200m of the requested1000m, the report correctly remained partial with an explicit coverage warning. The six saved bins within1000m were not substituted for the successful200m live empty search; live preference and coverage limits are deliberate and disclosed.

## Actual saved-data + Mapbox verification

A separate test server (port8012) deliberately disabled **only Overpass**, making no Overpass requests. Facility records came from the real included snapshot; Mapbox was not mocked. This is not a fully live Overpass test.

- saved nearby all categories: HTTP200 in0.017s; parameters `{"latitude": 40.5008, "longitude": -74.4474, "radius": 1000, "include_metadata": "true"}`.
- walking-time nearest saved bin: HTTP200 in0.647s; parameters `{"latitude": 40.4986, "longitude": -74.4301, "radius": 200}`.
  Selected genuine OSM ID `node/13009393596`.
- real Mapbox direct route: HTTP200 in0.088s; parameters `{"start_lat": 40.5085, "start_lon": -74.447, "end_lat": 40.5094, "end_lon": -74.4455}`.
- real Mapbox route through saved restroom: HTTP200 in0.141s; parameters `{"start_lat": 40.5085, "start_lon": -74.447, "end_lat": 40.5094, "end_lon": -74.4455, "facility_type": "Restroom", "max_detour_minutes": 5}`.
  Selected genuine OSM ID `way/475732039`.
- outside snapshot coverage: HTTP503 in0.002s; parameters `{"latitude": 40.7681, "longitude": -73.9819, "radius": 200, "include_metadata": "true"}`.

The real Mapbox optimized route through restroom `way/475732039` was420.569m,301.754s (5.03min), with zero additional walking time and one candidate evaluated. The intermediate Mapbox waypoint was9.688m from the OSM area center, within the existing snap threshold. This validates routing via the mapped representative point, not a verified physical entrance. Nearest-bin selection compared six actual walking routes and selected `node/13009393596`.

Actual Mapbox/WebGL frontend + saved-data API displayed7 facility cards and8 total markers (7 facilities plus the start), with persistent source/licensing warnings. Screenshot: `/tmp/reroute-snapshot-facilities.png`. Start coordinates were deliberately supplied for repeatability. The API response was real saved OSM data from the test server, not fabricated facility fixtures.

## Automated checks

97 backend tests passed, including snapshot boundaries, disabled/invalid/missing data, source checksums, freshness, radius/category filtering, successful empty live preference, recovery, legacy arrays, corridor selection, detour enforcement, import failure preservation and existing cache/cooldown/routing tests. Existing suite coverage also includes36 search combinations and all category success/failure subsets.7 frontend unit tests and28 Chrome browser integration tests passed. Lint and Vite production build passed; the existing Mapbox bundle-size warning remains.

Deterministic browser tests use explicit fixtures and are not live evidence. The source-checksum test compares the committed normalized IDs with the actual retained extracted payload.

## Remaining limits

Public Overpass still fails intermittently; the query change is not a universal upstream fix. Default live fallback radius remains200m with warnings; successful reduced-radius categories are not supplemented with saved data. There is no included Manhattan snapshot. Saved OSM may miss facilities or describe inaccessible/closed ones. Area centers may differ from entrances. A request near a coverage edge or a long route leaving the region cannot use this snapshot and will still fail if live sources are down. More regions need independently acquired, validated snapshots or a reliable provider. Rate controls remain process-local, not shared across replicas. A fresh import of old data still produces an age warning based on the extract timestamp. Refresh scripts require the operator to confirm complete input-region/category coverage; arbitrary filtered files cannot prove completeness.

See README for startup, configuration, live/forced-outage checks and refresh commands. No destructive Git operations or frontend rewrite were performed.
