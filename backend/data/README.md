# Genuine 10-mile OSM facility dataset

`resources_10mi.json` contains **273 actual OSM records**: **128 Trash Bin, 60 Restroom, 85 Recycling Location**. These counts were obtained after parsing, radius filtering, deduplication and validation. The accompanying `resources_10mi.source.json.gz` retains the extracted original IDs, geometry representative points, tags and extract SHA256; its payload SHA256 matches `source.sha256` in the dataset.

- Source: https://download.geofabrik.de/north-america/us/new-jersey-261009.osm.pbf
- Source boundary verified against: https://download.geofabrik.de/north-america/us/new-jersey.poly
- Authentic PBF reused from the earlier verified download, 164,165,911 bytes; MD5 `42ddf6a5f18c42447f5f5fa53f690d58`, matching the provider checksum. The full regional PBF is intentionally kept outside Git.
- Embedded OSM timestamp: `2026-10-09T20:21:04Z`.
- Snapshot generation/retrieval: `2026-10-11T05:29:10.261149+00:00`. This is a build date, not a claim of newer source data.
- Coverage: **circle**, approximate center latitude **40.53399**, longitude **-74.45793**, radius **16,093.44 meters (10 miles)**. Center is supplied approximate Society Hill / Piscataway, not verified present GPS.
- Envelope (west, south, east, north): `[-74.64836155433552, 40.389258216944434, -74.26749844566449, 40.67872178305557]`. Envelope corners are **outside** circle coverage.

All three categories contain usable mapped records; public access and opening hours remain unverified. Nodes preserve their mapped coordinates; ways and multipolygon relations use geometry bounding-box centers and are labelled `area_center`, not entrances. Useful metadata and original `osm_tags` are retained. Only representative points within the circle are kept. Facilities deduplicate by OSM element type and ID. Full, partial and outside search coverage are distinguished at runtime; successful empty searches within full coverage remain valid.

Regenerate from the repository root (Python with optional osmium installed):

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-snapshot.txt
python -m backend.scripts.generate_resources --latitude 40.53399 --longitude -74.45793 --radius-miles 10
```

Use `--refresh` for a newly downloaded extract; otherwise cache reuse avoids another large download. Source coverage, download completeness, checksums, geometry, identities and resulting categories/counts are validated before publishing. See the root README for source overrides, modes, run commands and browser checks. Dataset is © OpenStreetMap contributors, ODbL1.0: https://www.openstreetmap.org/copyright and https://opendatacommons.org/licenses/odbl/1-0/ . Preserve attribution and license when sharing.

The following smaller snapshot is retained for compatibility and additional verified coverage.

# Genuine OSM facilities — Rutgers / New Brunswick

`rutgers.json` contains 44 downloaded OSM facilities:

- 26 Trash Bin
- 6 Restroom
- 12 Recycling Location

Source: https://download.geofabrik.de/north-america/us/new-jersey-261009.osm.pbf

Extract data timestamp:2026-10-09T20:21:04Z.
Snapshot generated:2026-10-11T05:14:51.584141+00:00.
Verified downloaded PBF MD5:42ddf6a5f18c42447f5f5fa53f690d58 (matched Geofabrik's published `.md5`).
The PBF SHA256 is retained in the snapshot's source metadata. The original 156.6 MiB PBF is not committed.

Coverage rectangle (west,south,east,north):`[-74.48,40.475,-74.415,40.535]`, wholly within the New Jersey extract near Rutgers/New Brunswick. This is a bounded demo area, not all Rutgers campuses or Manhattan. Full coverage requires the requested radius or buffered route to fit inside this rectangle; overlapping requests can return explicitly partial results. Mapping completeness and actual public access are not guaranteed.

`rutgers.source.json.gz` preserves the facilities extracted from the downloaded PBF with their original OSM IDs/tags and representative coordinates, the original-extract checksum, and provenance. The snapshot's `source.sha256` hashes that retained payload before archive wrapping. This permits auditing normalization without storing the entire regional extract. Way/relation coordinates are bounding-box centers, not verified entrances. An empty category search can be valid within a smaller radius even though the regional file contains facilities of that category.

All data is © OpenStreetMap contributors, available under ODbL1.0:
https://www.openstreetmap.org/copyright
https://opendatacommons.org/licenses/odbl/1-0/

Preserve attribution and the license when sharing the snapshot. The data is a saved OSM snapshot, not real-time infrastructure/access verification. See the root README for refresh/import commands and configuration. No facilities were invented.
