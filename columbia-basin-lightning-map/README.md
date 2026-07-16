# Columbia Basin GLM Lightning Map

The canonical Columbia Basin lightning map: a styled map of the last 24
hours of lightning flashes across the Columbia Basin (same domain as
[`../columbia-basin-alerts-map/`](../columbia-basin-alerts-map/) and
[`../columbia-basin-temps/`](../columbia-basin-temps/): North Bend, WA
down to the Baker City, OR corridor), sourced from the GLM (Geostationary
Lightning Mapper) instrument on GOES-18 -- NOAA's operational GOES-West
satellite -- for Ingalls Weather's Instagram.

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections from the
  last 24 hours out of NOAA's public `noaa-goes18` bucket on AWS Open
  Data and writes `lightning_last24h.json`. Run this first, any time you
  want the map to reflect right-now conditions.
- `build_map.py` -- renders the map using `lightning_last24h.json` plus
  the static basemap files in `../maps/`. Writes
  `columbia_basin_lightning.png`.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/) -- see
`../columbia-basin-alerts-map/README.md` for what each file is. The
Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                        # first time / fresh environment only
python3 fetch_lightning.py           # pull the 24h of GLM flashes ending now
python3 fetch_lightning.py --end-pt "14:00"               # ... ending 14:00 PT today
python3 fetch_lightning.py --end-pt "2026-07-16 14:00"    # ... ending 14:00 PT on a given date
python3 build_map.py                 # render columbia_basin_lightning.png
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
- **Satellite choice**: GOES-18 is the current operational GOES-West
  satellite and the one with a clean view of the Pacific Northwest;
  GOES-East (GOES-19) views this domain at a much more oblique angle.
  If NOAA ever promotes a different satellite to the GOES-West slot,
  update `BUCKET` in `fetch_lightning.py`.
- **Quality flags**: `flash_quality_flag` values are kept as-is (not
  filtered) -- GLM's flash product only reports validated detections, and
  the flag mostly marks minor processing caveats (e.g. constituent event
  count/duration exceeding a threshold), not false positives.
- **Recency bands**: flashes are colored by age -- last hour (bright
  pink/red), 1-6 hours ago (orange), 6-24 hours ago (pale yellow) -- a
  common lightning-tracker convention. Age is derived from each source
  file's scan-start timestamp (20-second resolution), not the per-flash
  time-offset field within it, which is precise enough for hour-scale
  recency buckets. Bands are drawn oldest-first so more recent strikes
  render on top where tracks overlap.
- **Bounding box padding**: `fetch_lightning.py` pads the map's lat/lon
  extent by 0.5 degrees when filtering flashes, so strikes right at the
  map edge aren't dropped before `build_map.py` ever sees them.
