# GLM Real-Time Lightning Maps (Last 2 Hours)

The real-time companion to
[`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/)
(same four regions, same GOES-18 GLM source): instead of the full 24
hours, this renders just the last 2 hours, with finer recency bands
suited to watching an active storm right now rather than reviewing a
day's worth of activity.

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections from the
  last 2 hours out of NOAA's public `noaa-goes18` bucket on AWS Open
  Data, over a domain spanning all four regions, and writes
  `lightning_last2h.json`. Run this first, any time you want the map(s)
  to reflect right-now conditions. See
  `../columbia-basin-lightning-map/README.md` for the fuller write-up of
  the data source, satellite choice, and quality-flag handling -- this
  script is identical apart from the shorter lookback window.
- `build_map.py` -- same `REGIONS`-dict pattern as
  `../columbia-basin-lightning-map/build_map.py` (Columbia Basin,
  Portland, Pacific NW, BC Interior), just with a 2-hour-scale
  `AGE_BANDS` and `_realtime`-suffixed output filenames. See that
  project's README for the region definitions themselves.
- `deploy/publish_lightning.py` -- cron entry point, same
  `fcntl.flock`-locked pattern as the 24-hour project's.
- `deploy/crontab.example` -- every 5 minutes, tighter than the 24-hour
  companion's 15-minute cadence since this is the real-time product.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).
- `basemap_cache/` -- not committed, gitignored, and needs no manual setup
  -- caches the static land/countries/states/counties/roads layer per
  region as a raster PNG so a normal run doesn't re-render it from vector
  data every time (a ~45-60s cost otherwise). Self-invalidating; see
  "Basemap raster caching" under `../columbia-basin-lightning-map/README.md`
  Notes for the full write-up -- identical mechanism here.

Shared basemap data lives one level up in [`../maps/`](../maps/) -- see
`../columbia-basin-alerts-map/README.md` for what each file is. The
Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                        # first time / fresh environment only
python3 fetch_lightning.py           # pull the last 2h of GLM flashes (all 4 regions read this)
python3 build_map.py --region columbia_basin
python3 build_map.py --region portland
python3 build_map.py --region pnw
python3 build_map.py --region bc_interior
```

For a live view (e.g. an Instagram story that refreshes every few
minutes), re-run on a short interval -- a 2-hour window is only ~360 GLM
files, so a full fetch + render across all four regions takes well under
a minute.

`fetch_lightning.py` also accepts `--end-pt` (same as the 24-hour
version) to pin the window to a specific past Pacific-time moment
instead of now, for testing or reproducing a specific snapshot -- real
usage should just omit it.

## Notes

- **Recency bands**: 0-30 min ago (purple, matching the daily-archive
  map's single flash color), 30-60 min ago (bright pink/red), 60-120 min
  ago (orange) -- the same palette as the 24-hour map's hour-scale bands,
  just compressed onto a 2-hour window
  so a genuinely real-time view can still show gradient/movement within
  the last half hour instead of everything being "last hour." Age is
  derived from each source file's scan-start timestamp (20-second
  resolution). Bands are drawn oldest-first so more recent strikes
  render on top where tracks overlap.
- Everything else (regions, basemap layers, city labels, quality-flag
  handling, bounding-box padding, the border/offshore-line fixes, the
  absolute `MAPS_DIR`/`LOGO_PATH`) matches
  `../columbia-basin-lightning-map` exactly -- see that project's README
  for the rationale on each.
