# Columbia Basin Real-Time Lightning Map

The real-time companion to
[`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/)
(same domain, same GOES-18 GLM source): instead of the full day, this
renders just the last 2 hours, with finer recency bands suited to
watching an active storm right now rather than reviewing a day's worth
of activity.

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections from the
  last 2 hours out of NOAA's public `noaa-goes18` bucket on AWS Open
  Data and writes `lightning_last2h.json`. Run this first, any time you
  want the map to reflect right-now conditions. See
  `../columbia-basin-lightning-map/README.md` for the fuller write-up of
  the data source, satellite choice, and quality-flag handling -- this
  script is identical apart from the shorter lookback window.
- `build_map.py` -- renders the map using `lightning_last2h.json` plus
  the static basemap files in `../maps/`. Writes
  `columbia_basin_lightning_realtime.png`.
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
bash setup.sh                 # first time / fresh environment only
python3 fetch_lightning.py    # pull the last 2h of GLM flashes
python3 build_map.py          # render columbia_basin_lightning_realtime.png
```

For a live view (e.g. an Instagram story that refreshes every few
minutes), re-run both commands on a short interval -- a 2-hour window is
only ~360 GLM files, so a full fetch + render takes a few seconds.

`fetch_lightning.py` also accepts `--end-pt` (same as the 24-hour
version) to pin the window to a specific past Pacific-time moment
instead of now, for testing or reproducing a specific snapshot -- real
usage should just omit it.

## Notes

- **Recency bands**: 0-30 min ago (bright pink/red), 30-60 min ago
  (orange), 60-120 min ago (pale yellow) -- the same palette as the
  24-hour map's hour-scale bands, just compressed onto a 2-hour window
  so a genuinely real-time view can still show gradient/movement within
  the last half hour instead of everything being "last hour." Age is
  derived from each source file's scan-start timestamp (20-second
  resolution). Bands are drawn oldest-first so more recent strikes
  render on top where tracks overlap.
- Everything else (domain, basemap layers, city labels, quality-flag
  handling, bounding-box padding) matches
  `../columbia-basin-lightning-map` exactly -- see that project's README
  for the rationale.
