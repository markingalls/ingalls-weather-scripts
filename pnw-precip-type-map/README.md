# Pacific Northwest Precipitation Type + Highs Map

A styled "forecast highs and weather" map for one local (Pacific) day,
tomorrow by default, in the spirit of the TV national-map graphic. It covers
WA, OR, and ID, plus slivers of southern BC, western MT, and northern CA/NV:

- **Shading:** where precipitation falls that day, colored by type (green
  for rain, purple for mix, blue for snow). Each type has three shades,
  light, moderate, and heavy, set by the day's total liquid equivalent.
- **City labels:** the day's forecast high at a set of select cities. There
  are no condition icons. The precip shading carries the weather.

Everything comes from one source, ECMWF's free Open Data IFS distribution
(0.25°, 3-hourly steps), fetched live via Herbie. No API key is needed.

## Files

- `build_map.py` fetches ECMWF IFS `tp`/`sf`/`ptype`/`mx2t3` for the day
  and renders the map. Each live run also saves a `.npz` snapshot to
  `output/`, so `--file` can re-render without fetching again.
- `requirements.txt` / `setup.sh` hold the Python and system dependencies
  (same as `../dew-point-storm-map/`: GDAL for cartopy, libeccodes for
  cfgrib, and the Poppins font).

Shared basemap data comes from [`../maps/`](../maps/) (`land_slim.json`,
`states_lakes_slim.json`, `admin0_boundary_lines.json`). The logo comes from
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                          # first time / fresh environment only
python3 build_map.py                   # tomorrow
python3 build_map.py --date 2026-11-27
python3 build_map.py --file output/snapshot_2026-11-26.npz  # re-render, no fetch
```

## Methodology notes

- **Run selection:** the script uses the newest IFS run whose files already
  reach the end of the target day. Open Data posts each run's steps
  progressively, so it probes the last step it needs. 06z/18z runs only go
  out to 90 h, so for days further out it falls back to 00z/12z.
- **Day window:** precip is summed over the consecutive 3-hourly steps
  that best bracket local midnight to midnight. The steps don't land
  exactly on Pacific midnight, so each end of the window can be off by
  up to about an hour.
- **Precip type** is set per grid cell from how the day's total splits:
  - *snow* is the `sf` (snowfall water equivalent) increments;
  - *mix* is the non-snow precip in any 3-hour step whose instantaneous
    `ptype` at the end of the step is freezing rain, freezing drizzle,
    ice pellets, or rain/snow mixed;
  - *rain* is everything else.

  A cell is **snow** if at least 65% of the day's total is snow, and
  **rain** if at most 35% is snow. Either way, less than 30% can be ptype
  mix. Every other cell is **mix**. A day that starts as rain and turns
  to snow shows as mix, the way a daily TV map would show it. Mix
  therefore tends to sit in a band around snow areas, roughly along the
  snow level. To widen or narrow that band, change the
  `SNOW_FRAC_*`/`MIX_FRAC_MIX` constants.
- **Intensity** uses the day's total liquid equivalent: light ≥ 0.01 in,
  moderate ≥ 0.10 in, heavy ≥ 0.50 in (`INTENSITY_THRESHOLDS_IN`). These are
  liquid amounts, so heavy snow means half an inch or more of water, about
  5+ inches of snow.
- **Smoothing:** total, snow, and mix amounts are resampled to a 0.02° grid,
  then lightly gaussian-smoothed (σ ≈ 0.1°) *before* classifying. This
  keeps the 0.25° cell edges from showing as blocks. The categories are
  drawn with nearest-cell shading, not gouraud, so neighboring types never
  blend into colors that aren't on the legend.
- **Highs** are the max of `mx2t3` (max 2m temperature over the previous 3
  hours) for steps ending between 10am and 8pm local, roughly 7am–7pm,
  sampled bilinearly at each city. These are 0.25° grid-cell values, so
  cities in valleys next to high terrain can read a few degrees cool
  (and vice versa): the grid cell's mean elevation isn't the town's.
  Treat them as model guidance, not a hand-edited forecast.
- Uses `PlateCarree` and `pcolormesh` like `../dew-point-storm-map/`. See
  that README for why. The figure height is derived from the domain's
  lon/lat spans, so changing `LON_*`/`LAT_*` doesn't leave gutters.
