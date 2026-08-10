# GLM Lightning Maps (Last 24 Hours)

A styled map of the last 24 hours of lightning flashes, for each of four
regions -- Columbia Basin, Portland Metro, Pacific Northwest, and BC
Interior -- sourced from the GLM (Geostationary Lightning Mapper)
instrument on GOES-18, NOAA's operational GOES-West satellite. Real-time
companion: [`../columbia-basin-lightning-realtime-map/`](../columbia-basin-lightning-realtime-map/)
(last 2 hours). 5-day rolling archive companion:
[`../columbia-basin-lightning-daily-map/`](../columbia-basin-lightning-daily-map/).

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections from the
  last 24 hours out of NOAA's public `noaa-goes18` bucket on AWS Open
  Data, over a domain spanning all four regions below, and writes
  `lightning_last24h.json`. Run this first, any time you want the map(s)
  to reflect right-now conditions.
- `build_map.py` -- `REGIONS` dict registry (extent, center point, city
  labels, roads files, output filename) plus `build_map(region_key,
  lightning_path, output_path)`, which renders one region using
  `lightning_last24h.json` plus the static basemap files in `../maps/`.
  `python3 build_map.py --region <key>` from the command line.
- `deploy/publish_lightning.py` -- cron entry point. Fetches once, builds
  and atomically publishes every region in `REGIONS`. One region failing
  doesn't stop the others. `fcntl.flock`-locked so an overlapping cron
  tick skips instead of running a second pass concurrently.
- `deploy/crontab.example` -- every 15 minutes; lightning has no fixed
  issuance schedule to align to, so like `../columbia-basin-alerts-map/`
  this is a polling interval, not a cycle time.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).

## Regions

Same `REGIONS`-dict pattern as `../columbia-basin-alerts-map/build_map.py`
-- see that project's README for the full writeup of `region_extent()`,
the shared "true zoom" `LON_SPAN`/`LAT_SPAN`/`SATELLITE_HEIGHT`, and how
a region overrides them for a different zoom level.

- **`columbia_basin`** -- the original region, unchanged: center
  `(-119.75, 46.2)`, same domain as `../columbia-basin-alerts-map/` and
  `../columbia-basin-temps/`.
- **`portland`** -- the unshifted "Portland point" (`-122.60917,
  45.59578`) that `tri-cities-7day-forecast` and `850-700-temp-chart`
  use -- unlike `columbia-basin-alerts-map`'s `portland` region, this one
  doesn't need to shift for a legend collision (only one legend entry
  here, not a variable-length NWS event list).
- **`pnw`** -- same extent as `columbia-basin-alerts-map`'s `pnw_wide`
  region (`center=(-119.3, 44.9)`, `lon_span=13.0`, `lat_span=8.8`,
  `satellite_height=22_000_000`), so the same named domain looks the same
  across both products. Reaches the WA/OR coast and the US/Canada border
  widely enough to need the same two fixes as that project (see Notes).
- **`bc_interior`** -- new, no prior product on this domain. Wider than
  true-zoom (`lon_span=10.0`, `lat_span=5.2`, `satellite_height=9_000_000`)
  to cover the Southern Interior (Kamloops/Kelowna/Vernon/Penticton),
  Prince George (~4.4 degrees north of Penticton), and the Yellowhead
  Pass area just across the Alberta border (Jasper); center is the
  midpoint of that span, not any single city. The east edge was
  originally `lon_span=7.5` (edge at -116.72), which cut off real storm
  activity mid-frame with a visible hard edge well short of Jasper --
  `lon_span=10.0` (edge at -114.25) fixed that without losing the western
  cities; the shared fetch bbox in `fetch_lightning.py` already reached
  farther east than this (bounded by `pnw`'s own wider extent), so no
  fetch change was needed, only the render extent. Uses
  `America/Vancouver` (not `America/Los_Angeles`) for its day/time labels
  -- numerically identical to Pacific time for any date since 2007, so
  this is a correctness/clarity fix rather than a behavior change. Roads
  come from `../maps/british_columbia_roads.geojson` (Geofabrik BC
  extract) plus `../maps/alberta_roads_west.geojson` (Geofabrik Alberta
  extract, clipped to just the Jasper/Yellowhead area) -- both filtered
  to motorway/trunk/primary.

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                        # first time / fresh environment only
python3 fetch_lightning.py           # pull the 24h of GLM flashes ending now (all 4 regions read this)
python3 fetch_lightning.py --end-pt "14:00"               # ... ending 14:00 PT today
python3 fetch_lightning.py --end-pt "2026-07-16 14:00"    # ... ending 14:00 PT on a given date
python3 build_map.py --region columbia_basin
python3 build_map.py --region portland
python3 build_map.py --region pnw
python3 build_map.py --region bc_interior
```

## Notes

- **Source and access**: GLM's Level 2+ "LCFA" (Lightning Cluster
  Filter Algorithm) product reports one record per detected flash --
  centroid latitude/longitude, radiant energy, and quality flags -- so no
  satellite fixed-grid projection math is needed, unlike ABI imagery.
  NOAA publishes it continuously and publicly on AWS Open Data
  (`s3://noaa-goes18/GLM-L2-LCFA/...`), readable anonymously with no AWS
  account or API key. Files are produced every 20 seconds (~4,320/day);
  `fetch_lightning.py` downloads the ones covering the last 24 hours
  concurrently (I/O-bound, so threads are safe there), then parses them
  sequentially -- the underlying HDF5/netCDF4 library isn't thread-safe,
  so parsing concurrently intermittently corrupts memory.
- **One shared fetch, four regions**: `fetch_lightning.py`'s bounding box
  is the union of all four `REGIONS` extents (padded 0.5 degrees), not
  just Columbia Basin's -- widening it doesn't add fetch cost, since GLM
  file listing/download is purely a function of the time window (GOES
  covers the full disk in every file), not the bbox. `build_map.py`
  filters down to each region's own tighter extent at render time, same
  pattern as `columbia-basin-alerts-map/fetch_alerts.py`.
- **Satellite choice**: GOES-18 is the current operational GOES-West
  satellite and the one with a clean view of the Pacific Northwest;
  GOES-East (GOES-19) views this domain at a much more oblique angle.
  If NOAA ever promotes a different satellite to the GOES-West slot,
  update `BUCKET` in `fetch_lightning.py`.
- **Quality flags**: `flash_quality_flag` values are kept as-is (not
  filtered) -- GLM's flash product only reports validated detections, and
  the flag mostly marks minor processing caveats (e.g. constituent event
  count/duration exceeding a threshold), not false positives.
- **Recency bands**: flashes are colored by age -- last hour (purple,
  matching the daily-archive map's single flash color), 1-6 hours ago
  (bright pink/red), 6-24 hours ago (orange). Age is derived from each source
  file's scan-start timestamp (20-second resolution), not the per-flash
  time-offset field within it, which is precise enough for hour-scale
  recency buckets. Bands are drawn oldest-first so more recent strikes
  render on top where tracks overlap.
- **Two fixes ported from `columbia-basin-alerts-map/build_map.py`**,
  needed once `pnw`'s much wider extent came into play (invisible at
  Columbia Basin/Portland's tighter zoom):
  - `drop_long_segments()` -- `countries_slim.json`'s US/Canada/Mexico
    border has several segments over-simplified down to a single straight
    run several degrees long, which cuts across the more detailed
    `admin1_boundary_lines.json` line underneath at wide enough zoom.
  - `trim_offshore_segments()` -- Natural Earth's `admin1_boundary_lines.json`
    includes each coastal state's offshore 3-nautical-mile maritime
    boundary as an ordinary admin-1 line.
- **`MAPS_DIR`/`LOGO_PATH` are absolute**, derived from `build_map.py`'s
  own file location via `SCRIPT_DIR`, not the process's cwd at
  invocation -- a relative path here broke under cron (which starts with
  cwd set to the crontab user's home directory) even though it worked
  fine for a manual run after `cd`-ing into the project directory. Same
  bug, same fix, as `columbia-basin-alerts-map/build_map.py`.
