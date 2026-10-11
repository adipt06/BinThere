# Network comparison — 2026-10-11 04:50 UTC

Two direct, uncached requests from the workspace machine to `https://overpass.private.coffee/api/interpreter`, separated by two seconds. Identical query, coordinates, radius and application User-Agent; transport compared POST with GET. No application cooldown, caching or retry layer involved.

```overpass
[out:json][timeout:100];node["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;
```

## Local POST

```json
{
  "vantage": "local workspace machine",
  "started_utc": "2026-10-11T04:50:11.100468+00:00",
  "method": "POST",
  "endpoint": "https://overpass.private.coffee/api/interpreter",
  "query": "[out:json][timeout:100];node[\"amenity\"=\"waste_basket\"](around:200,40.7681,-73.9819);out center;",
  "user_agent": "ReRoute-HackRU/1.0 (environmental walking navigation)",
  "status": 500,
  "seconds": 0.459,
  "headers": {
    "Server": "nginx/1.26.3",
    "Date": "Sun, 11 Oct 2026 04:50:11 GMT",
    "Content-Type": "text/html; charset=iso-8859-1"
  },
  "elements": null,
  "valid_facilities": 0,
  "generic_apache_error": true
}
```

## Local GET

```json
{
  "vantage": "local workspace machine",
  "started_utc": "2026-10-11T04:50:13.566132+00:00",
  "method": "GET",
  "endpoint": "https://overpass.private.coffee/api/interpreter",
  "query": "[out:json][timeout:100];node[\"amenity\"=\"waste_basket\"](around:200,40.7681,-73.9819);out center;",
  "user_agent": "ReRoute-HackRU/1.0 (environmental walking navigation)",
  "status": 500,
  "seconds": 0.533,
  "headers": {
    "Server": "nginx/1.26.3",
    "Date": "Sun, 11 Oct 2026 04:50:14 GMT",
    "Content-Type": "text/html; charset=iso-8859-1"
  },
  "elements": null,
  "valid_facilities": 0,
  "generic_apache_error": true
}
```

DNS resolved to193.219.97.30. No HTTP_PROXY, HTTPS_PROXY or ALL_PROXY environment variables were present. This does not rule out transparent network filtering or system-level network configuration.

## Attempted independent fetch

The remote web-fetch tool was asked to retrieve the same query via GET at approximately the same time. It returned: "URL ... is not accessible via this tool." It did not expose an upstream HTTP status, timing, headers, or body. The tool cannot set the same custom User-Agent or perform a matching POST. This is an unavailable measurement, not evidence of an Overpass error from a second network. An identical controlled comparison across two networks was therefore not completed.

## What this establishes

Both local methods returned500 in less than0.6 seconds, despite a100-second QL timeout. Responses advertised nginx/1.26.3 and contained generic Apache Internal Server Error HTML, not valid facility JSON. Current failures occur outside the ReRoute application, and switching POST to GET did not fix them. These observations do not distinguish provider/gateway failure from a network-specific intermediary, nor establish that all provider clients are affected.

A matching POST from a different machine/network is still needed. Run this once on another network, near the time of a local check; the shell quoting intentionally preserves Overpass syntax:

```sh
curl --silent --show-error --max-time 105 --dump-header - \
  --user-agent 'ReRoute-HackRU/1.0 (environmental walking navigation)' \
  --header 'Accept: application/json' \
  --data-urlencode 'data=[out:json][timeout:100];node["amenity"="waste_basket"](around:200,40.7681,-73.9819);out center;' \
  --write-out '\nHTTP=%{http_code} elapsed=%{time_total}s\n' \
  'https://overpass.private.coffee/api/interpreter'
```

No production code changed for this diagnostic run. No further endpoint probes were made.
