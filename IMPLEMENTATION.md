# Phase 1 delivery

Implemented GPS/manual/address start selection, address/POI/map destination selection, cancellation, direct walking directions, real OSM discovery with metadata, walking-time bin selection, bounded detour optimization, route comparison, facility popups/details, mobile panel collapse, and separate clear-route/clear-destination/reset behavior. Existing endpoint names and their original request and response fields remain compatible. FastAPI and vanilla JavaScript are retained.

## Original audit mapping

| # | Finding | Implementation / practical limit |
|---|---|---|
| 1 | Hardcoded API URL / CORS | `/api` Vite proxy; configurable build-time API URL and backend origin list; HTTPS production instructions. |
| 2 | GPS failure blocks use | Manual map start and separate place/address search; denied/unavailable/timeout feedback; late GPS responses ignored. |
| 3 | Location changes leave stale routes | Every committed endpoint change aborts and invalidates route work, clears geometry, summaries and recommendation. |
| 4 | Facility request races | Independent AbortController/request-generation lane; clear previous results immediately; only current response may render. |
| 5 | Cleanup inconsistency | Distinct start/destination/recommendation markers; central route cleanup, explicit destination clearing, reset and request cancellation. |
| 6 | Fixed corridor/eight candidates | Detour-aware bounded corridor, configurable default 24 candidates, interleaved rankings, best eligible actual walking duration. Completeness/limit metadata; no global optimality claim. |
| 7 | Simplified path distorts query | Full geometry retained in a POST corridor query. Explicit 20,000-vertex limit instead of silent approximation. |
| 8 | Unverified waypoint snapping | Mapbox radiuses plus returned waypoint-distance validation for starts, stops and ends. Area-center/access warnings remain. |
| 9 | Upstream failures discard results | Bounded retries/fallback/cache, runtime-remark detection, isolated candidate failures, direct-route fallback with explicit warnings. |
| 10 | Map/token failure recovery | Public-token check before map import; safe map error status; backend token errors return 503; health reports configuration state. |
| 11 | Address search/destination routing absent | Separate start and destination Search Box forms supporting POIs; independent direct-route action through existing backend endpoint. |
| 12 | Mobile map obstruction | Collapsible control panel, map-visible status and cancel controls, panel-aware bounds fitting and reduced-motion handling. |
| 13 | Loading/repeated work | Disabled busy actions, cancellation, request timeouts, independent search lanes, bounded upstream work and caches. Synchronous server work may finish after browser abort. |
| 14 | OSM accessibility assumptions | Preserve access/wheelchair/hours/fees/operator/recycling metadata; exclude private/no facilities from automatic recommendations; label access unverified and area centers approximate; enforce center-based nearby radius. |
| 15 | Straight-line nearest bin | New bounded walking-time comparison endpoint. Nearby list still explicitly sorts by straight-line distance. Neither is presented as a global nearest guarantee. |
| 16 | Weak response validation | Validate external JSON, route geometry, distances/durations, waypoint structures, facilities and place results; frontend validates responses before rendering. Safe JSON error messages. |
| 17 | Facility result details | Name/type/coordinates, metadata, highlighted popup/marker, direct/optimized comparison and candidates/limitations. |
| 18 | Working-directory imports | Package-safe imports with compatibility for launching inside backend; documented root command. |
| 19 | Token-bearing exception logs | Raw requests errors, upstream bodies and URLs never logged or returned; safe named service errors. Env files remain ignored/untracked. |
| 20 | Large main bundle | Lazy Mapbox import, dedicated vendor chunk, removed React dependencies. Application JS ~17 KB minified; Mapbox remains ~1.86 MB and emits the size warning. |
| 21 | Unused scaffold | Removed React entry/components/styles/template assets and React Vite plugin. Working `script.js` entry preserved. |
| 22 | Setup/dependency/tests incomplete | Root README, environment examples, consolidated requirements, frontend/unit/browser/backend suites and explicit live smoke scripts. |
| 23 | Accessibility/usability gaps | Form labels, semantic keyboard-operable buttons, accessible icon names, status announcements, selection cancel/Escape, disabled/busy states and reduced motion. Physical device/accessibility audit remains manual. |

## Executed verification

- Backend: **46 tests passed, 0 failed**, with deterministic mocked upstream responses. Covers health, validation, CORS including configured production origin, response compatibility, Overpass retries/fallback/cache/runtime errors/deduplication, Mapbox ordering/stops/snapping/malformed responses/configuration, detour boundaries, zero detour, >8 candidates, limits/deadlines, partial failures and direct fallback.
- Frontend unit tests: **7 passed, 0 failed**.
- Chrome browser tests: **26 passed, 0 failed**, including mobile viewport, GPS allowed/denied/late callbacks, manual/address selection, direct/optimized rendering, comparison, cancellation, out-of-order responses, marker reset, invalid responses, failed/empty searches and recovery. One test traverses actual Vite proxy and FastAPI with only external service boundaries mocked. The map adapter is mocked for these deterministic tests.
- Real Mapbox/WebGL Chrome smoke: **passed**, with real map tiles and GPS denial/manual controls enabled. Screenshot inspected locally.
- Limited live Mapbox Directions: **passed**. Search Box broad city query: **5 results**; campus-specific query returned zero.
- Limited live Overpass: primary timed out; fallback returned a valid empty Rutgers-area search. A subsequent 500-meter New York-area fallback query returned HTTP 500 after bounded retry. Real nonempty facility discovery and a real live optimized route are therefore **not verified**. No sample facilities are used by the application.
- Frontend production build: **passed**. Lint: **passed**. Git whitespace check: **passed**. No real environment tokens are tracked.
- Nonfatal diagnostics: Mapbox vendor chunk size warning; installed Starlette emits a TestClient/httpx deprecation warning. Tests pass with the current environment.

## Files

Changed: `.gitignore`, root/backend requirements, all four existing backend modules, `frontend/index.html`, `frontend/src/script.js`, `frontend/src/style.css`, Vite config, package manifest/lockfile and frontend README.

Added: root README and this delivery record; backend package initializer, safe service/cache module, dev requirements, backend/frontend `.env.example`, backend unit tests and explicit live/browser integration helpers; frontend request/validation utility, unit tests, Playwright config, deterministic browser map adapter/browser suite and real-map smoke script.

Removed: unused React `App.jsx`, `main.jsx`, `App.css`, `index.css`; template React/Vite/hero/icon/favicon assets; React runtime/types/plugin dependencies.

## Remaining limits and next steps

Public Overpass availability and OSM coverage are outside application control. Keep the configured fallback, retry after transient failures, or supply a reachable compatible Overpass instance for a predictable live demo. Confirm actual nearby facility coverage before presenting; do not invent facilities. Mapbox token/account access, URL restrictions, billing and region coverage must support Maps, Directions and Search Box.

Optimization is limited by the configured corridor, candidates and approximate time budget. Snapping and access tags cannot prove physical entrance accessibility, opening hours, or an exhaustive optimum. Browser abort suppresses stale rendering but cannot cancel already-running synchronous backend requests. The Mapbox SDK remains the largest download. Phone viewport tests ran in desktop Chrome; physical iOS/Android browsers still need the manual checklist in README.

Setup commands, environment variables, deployment/phone HTTPS guidance, complete test commands and a manual end-to-end checklist are in [README.md](README.md).
