# Facility regression investigation — 2026-10-11

Compared current working files against Git HEAD `b74b2da`, whose latest OSM service change is `105b902`. Also inspected initial service `7450dac`. The initial implementation used a 600-second timeout; the later working baseline used 25-second Overpass / 35-second HTTP timeouts. Git records code, not proof of when a successful live route was executed.

| Area | Committed working baseline | Prior current implementation | Targeted change / conclusion |
|---|---|---|---|
| Trash selector | node | nwr | Restore node for bins; restroom/recycling retain nwr. Avoid unnecessary way/relation expansion. Controlled live comparison does not prove this caused HTTP 500. |
| Nearby query | Three exact-tag around selectors in union | bbox + anchored amenity regex | Restore original exact-tag circular union, verified against committed source after whitespace normalization. Category fallback and explicit coverage remain. |
| Timeouts | QL25 / HTTP35 | QL5–10 / read15 | Restore QL25 / connect3, read30 (subject to remaining discovery budget). Previous limits could truncate otherwise valid slower queries; subsecond Apache 500 responses are not explained by a 5-second execution timeout. |
| Endpoint | overpass-api.de | Private.coffee primary, .de fallback | Retain configurable failover, not a blind switch back to an endpoint that previously refused connections. Latest controlled comparison uses only Private.coffee; no claim .de is currently healthy. |
| Corridor | At most20 uniformly sampled vertices | Every vertex, up to20,000 | Bound transport using 10m Douglas-Peucker local-plane simplification, at most256 vertices; compensate with10m radius padding when simplified. Reject excessive complexity explicitly and retain direct-route fallback. Full geometry remains for Mapbox/ranking. |
| Candidates |8 |24 | Restore default8, keep explicit larger limits and time budget. Candidate count affects Mapbox work after discovery, not Overpass HTTP500. |
| Resilience | No caches/cooldowns/budget | Success90s, failures5s; endpoint/query cooldowns, six-request discovery budget,45s start deadline | Retain protections and partial results. These can delay recovery or return503 without new traffic, but cannot explain the direct uncached raw HTTP500 probes below. State is process-local, not permanent. |

## Controlled raw HTTP comparison

Exactly three requests, two seconds between completed requests, no automatic retries or application caches/cooldowns. Same endpoint, form-encoded POST, same User-Agent `ReRoute-HackRU/1.0 (environmental walking navigation)`, coordinates40.7681,-73.9819, radius200m and `out center`. First two differ only by node/nwr; last two differ only by QL timeout.

| Selector | QL timeout | HTTP status | Elapsed | Valid facilities |
|---|---|---|---|---|
| node | 25s | 500 | 0.43s | 0 (no valid JSON elements) |
| nwr | 25s | 500 | 0.47s | 0 (no valid JSON elements) |
| nwr | 5s | 500 | 0.53s | 0 (no valid JSON elements) |

Endpoint: `https://overpass.private.coffee/api/interpreter`. All responses were generic Apache Internal Server Error HTML (`text/html; charset=iso-8859-1`), not Overpass parse/runtime errors. Exact requests:

```overpass
[out:json][timeout:25];node["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;
```

```overpass
[out:json][timeout:25];nwr["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;
```

```overpass
[out:json][timeout:5];nwr["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;
```

Both original-style node and expanded nwr queries failed at the same endpoint. This supports an upstream/gateway availability problem during this run and does not prove a selector, query-plan, timeout or application cooldown regression caused these failures. It also does not exonerate all previous changes: the shorter read timeout and inflated corridor payload are concrete reliability risks corrected here. The endpoint's exact internal failure cause is unknown. No live discovery recovery is claimed.

## Route comparison and validation

Mocked tests load the actual committed OSM module via `git show 105b902:backend/osm_service.py` and intercept its transport. For1,000 collinear vertices the original includes20, the prior current query includes1,000, and the revised query includes2 plus10m padding. A sharp turn at vertex500 missed by original sampling remains in the revised query. Excessively complex zigzags are rejected before any upstream request. A candidate-limit test confirms8 default attempts; explicit24 remains supported. Nearby original-union equivalence, category success/failure caches, throttling and partial result tests also pass.

No live corridor or Mapbox optimization calls were made because minimal discovery probes were unhealthy. Browser integration and route tests use declared mocks and are not evidence of a live successful route. Validation:75 backend tests,7 frontend unit tests,27 browser tests; production build and lint passed (existing Mapbox bundle-size warning).

Frontend UI, address/location search, route comparisons and partial-result rendering are preserved. For reliable live results, a healthy public or compatible managed/self-hosted OSM Overpass endpoint is still necessary; the code does not manufacture facilities.
