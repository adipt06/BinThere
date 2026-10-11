# Facility discovery investigation

## Findings from limited live requests

All probes used public test coordinates near Central Park (40.7681, -73.9819), modest radii, and no credentials. No facilities were fabricated. The running FastAPI API was tested on port 8000.

| Endpoint | Actual result |
|---|---|
| `https://overpass-api.de/api/interpreter` | DNS resolved to IPv4 addresses, but TCP connection was refused (`Errno 61`); no HTTP status received. No requests proxy environment was configured. This does not establish whether the refusal originated at the server or an intervening network policy. |
| `https://overpass.kumi.systems/api/interpreter` | Tiny valid POST query returned **HTTP 500**, HTML generic Apache “internal error or misconfiguration.” |
| `https://overpass.private.coffee/api/interpreter` | Descriptive-User-Agent, single-category 200-meter node and nwr queries returned **HTTP 200 with 10 real bins**. Three-category 200/500-meter union queries and the 500-meter bbox query returned **HTTP 500**, generic Apache HTML. A GET transport probe also returned 500, so changing POST to GET did not solve it. |
| `https://maps.mail.ru/osm/tools/overpass/api/interpreter` | Additional global-instance probe with a tiny query reached a **read timeout**; no HTTP status received. Not added as an automatic default because it did not prove healthy. |

Diagnostic requests using Python's default User-Agent received **HTTP 429** with `Retry-After: 60` and a request for a meaningful User-Agent. Production requests already supplied an app identifier; the updated identifier is more descriptive and configurable. The successful small queries used that identifier. The 429 is distinct from the production three-category HTTP 500 failure.

The [OSM public-instance list](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances) identifies Private.coffee as the current name of the former Kumi service. Both hostnames resolve to the same IPv4 address in this environment, but their HTTP behavior differs. Defaults now use the current hostname; old Kumi configuration is migrated automatically.

Query construction is valid according to the [Overpass QL reference](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL). Small node/nwr queries actually succeeded. Form-encoded POST uses `data=<encoded query>`, latitude/longitude ordering is correct, union syntax is valid, and `out center` includes tags and coordinates/area centers. The generic Apache errors did not provide an Overpass parse error, timeout remark, or enough information to prove overload versus server misconfiguration. They should not be represented as successful empty searches.

The minimal successful query was:

```overpass
[out:json][timeout:5];
node["amenity"="waste_basket"](around:200,40.7681,-73.9819);
out body;
```

Nearby discovery now performs one indexed bbox scan using an anchored amenity regex, followed by exact haversine distance filtering. This preserves all three categories and the requested circular radius. The bounding box correctly handles poles and the date line. Full-geometry route-corridor queries are preserved. The new bbox query also encountered HTTP 500 during this investigation; it is an efficiency improvement, not a claim that public-service failure is eliminated.

## Implemented recovery and protection

- Default primary: Private.coffee; default fallback: overpass-api.de.
- `OVERPASS_ENDPOINTS` optionally replaces this pair with up to three ordered compatible endpoints. Existing primary/fallback variables remain supported.
- Try each available endpoint once per cache miss, continuing after HTTP/network/runtime/schema failures, including malformed individual facilities.
- Prefer the last successful endpoint and skip failed endpoints during cooldown. Transport/service failures cool down for 30 seconds; nearby HTTP 500/runtime failures instead cool down the exact endpoint/query for 30 seconds, allowing smaller category queries; throttling for at least 60 seconds, respecting numeric or HTTP-date Retry-After up to one hour.
- Serialize cache misses, coalesce concurrent duplicate queries, and space upstream requests at least one second apart. No rapid retry loops or parallel fan-out to public servers.
- Cache valid results, including empty lists, for 90 seconds by default. Separately memoize failures for five seconds; never substitute an empty list for failure.
- Safe diagnostics log hostname, upstream HTTP status/error category, elapsed time, query digest and query length. URL credentials, paths/API keys, raw bodies, query coordinates and tokens are not logged.
- If all providers fail or cool down, `/resources` returns a sanitized **503**, identifying their last statuses/categories; the frontend retains an actual service error and retry control.

These controls are process-local. Multiple production workers/replicas require a shared cache/rate limiter or a dedicated provider to coordinate aggregate traffic.

## Verification and remaining live limitation

- **63 backend tests passed**, including third-endpoint success, runtime/schema fallback, cooldown recovery, Retry-After, healthy-provider preference, cached empty results, failure memoization, concurrent coalescing, request pacing, safe diagnostics, bbox circle filtering and pole/date-line handling.
- **26 Chrome browser tests passed**: actual frontend rendering and FastAPI proxy integration use deterministic upstream fixtures. They confirm facility cards/markers render when `/resources` succeeds and failures remain errors with recovery controls. A live three-category browser result could not be verified because the live API request failed.
- Live `/resources?latitude=40.7681&longitude=-73.9819&radius=500`: **503**, reporting Private.coffee HTTP 500 and overpass-api.de connection failure. Nonempty live **single-category** queries worked, but live three-category discovery remains externally blocked.
- Optimizer and frontend navigation logic were preserved. No generated/sample facilities are used by production code.

To repeat one API smoke request after cooldown:

```sh
.venv/bin/python -m backend.tests.resources_smoke
```

Add `--repeat-cache` only after service recovery to verify repeated results without another upstream search. Use `--latitude`, `--longitude`, and `--radius` to test another real location.

For a predictable demo, configure a reachable compatible managed Overpass endpoint with global/NY–NJ coverage or a self-hosted regional Overpass instance using a real OSM extract. The public-instance list links managed providers. Do not use a region-limited provider that lacks the demo area: it can return a misleading valid empty result. A paid provider may embed a key in its URL; keep that URL in backend `.env` only. Alternatively, wait for public-service recovery and warm the short-lived cache with a small real search immediately before presenting. Caching cannot create results for an area that has never been fetched successfully.


## Category fallback update — 2026-10-11

Nearby discovery now tries the combined bbox query only for requests up to 1,000 m, then independently queries exact amenity tags on failure. Larger requests go directly to bounded category queries. Category fallback searches at most 200 m by default (configurable up to 1,000 m); reduced coverage is explicitly warned about. Each discovery has a six-upstream-request budget and a 45-second deadline for starting requests, with existing serialization, one-second pacing and endpoint cooldowns. A running request can finish after that deadline within its bounded connect/read timeout. Combined failures are remembered for 60 seconds, successful categories for 90 seconds by exact location/requested radius/category. Empty successful responses remain cached successes; failures retain status `failed` and `count: null`.

`GET /resources?...&include_metadata=true` returns `facilities`, `categories`, `warnings`, `partial`, `complete`, and `requested_radius`. Optional `facility_type` restricts the search. The frontend uses this mode, retains successful cards/markers and shows persistent category/coverage warnings. Legacy mode retains its array schema for complete results and returns an explicit 503 for incomplete results; legacy consumers should adopt metadata mode to use partial results. Nearest-bin discovery now queries only Trash Bin and forwards coverage warnings. The optimizer's existing selected-category route-corridor query and algorithm are preserved.

Latest live smoke test invoked the real FastAPI `/resources` route through TestClient with real HTTP upstream requests (no network mocks), restricted to the previously healthy `https://overpass.private.coffee/api/interpreter` to limit traffic. All requests were form-encoded POST with the application User-Agent. At latitude 40.7681, longitude -73.9819, radius 200:

1. HTTP 500 in 0.36 s: `[out:json][timeout:5];nwr["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;`
2. HTTP 500 in 0.35 s: `[out:json][timeout:10];nwr["amenity"~"^(waste_basket|toilets|recycling)$"](40.76630136,-73.98427489,40.76989864,-73.97952511);out center;`
3. HTTP 500 in 0.36 s: `[out:json][timeout:5];nwr["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;`
4. HTTP 500 in 0.38 s: `[out:json][timeout:5];nwr["amenity"="toilets"](around:200,40.7681,-73.9819);out center;`
5. HTTP 500 in 0.37 s: `[out:json][timeout:5];nwr["amenity"="recycling"](around:200,40.7681,-73.9819);out center;`

The first API request selected only Trash Bin and returned 503. The next all-category request attempted combined then all three categories and returned 503. Caches were reset once between these two tests to independently exercise combined fallback. An immediate repeat of the all-category API request returned 503 without any new upstream request (five actual upstream calls total). No real facilities were returned in this new run; the earlier 10-bin success remains historical evidence, not a claim of current availability. The other previously failed endpoints were not reprobed in this limited run.

The valid single-category syntax and prior success rule out a consistently invalid query as the explanation. Current rapid HTTP 500 responses even for small requests show availability varies; they do not establish whether the root cause is server overload, a gateway, or server configuration. Reliable demos still need a managed compatible endpoint or self-hosted regional OSM instance if public availability does not recover.

Validation: 70 backend tests, 7 frontend unit tests, 27 Chrome browser tests, frontend production build and lint passed. Browser validation includes partial cards/markers, failed-category filtering and persistent warnings using explicit test fixtures, not fabricated production locations.


Latest follow-up: [Git regression comparison and targeted corrections](OVERPASS_REGRESSION.md). This supersedes earlier descriptions of bbox queries, full-geometry transport and short timeouts; historical live outcomes above remain unchanged.


Latest implementation and genuine snapshot verification: [FACILITY_RECOVERY_REPORT.md](FACILITY_RECOVERY_REPORT.md). Earlier live results remain historical; nearby query defaults and snapshot fallback are described in the new report.
