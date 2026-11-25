# Pacific Northwest Precipitation Type + Highs Map

A styled "forecast highs and weather" map for one local (Pacific) day,
tomorrow by default, in the spirit of the TV national-map graphic. It covers
WA, OR, and ID, plus slivers of southern BC, western MT, and northern CA/NV:

- **Shading:** where precipitation falls that day, colored by type (green
  for rain, purple for mix, blue for snow). Each type has three shades,
  light, moderate, and heavy, set by the day's total liquid equivalent.
- **City labels:** the day's forecast high at a set of select cities, in the
  repo's default label style (same as `../thanksgiving-snow-climatology-map/`):
  the city name centered on its location in a 50%-black rounded box, with the
  high in bold just above it. The city list is that map's too. There are no
  condition icons. The precip shading carries the weather.

Everything comes from one source, ECMWF's free Open Data IFS distribution
(0.25°, 3-hourly steps), fetched live via Herbie. No API key is needed.

## Files

- `build_map.py` fetches ECMWF IFS `tp`/`sf`/`ptype`/`mx2t3` for the day
  and renders the map. Each live run also saves a `.npz` snapshot to
  `output/`, so `--file` can re-render without fetching again.
- `requirements.txt` / `setup.sh` hold the Python and system dependencies
  (GDAL for cartopy, libeccodes for cfgrib, and the Poppins font weights).

Shared basemap data comes from [`../maps/`](../maps/) (`land_slim.json`,
`admin1_boundary_lines.json`, `admin0_boundary_lines.json`). Borders come
from the line datasets, not polygon outlines, the same as
`../columbia-basin-temps/`. The logo comes from
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                          # first time / fresh environment only
python3 build_map.py                   # tomorrow
python3 build_map.py --date 2026-11-27
python3 build_map.py --file output/snapshot_2026-11-26.npz  # re-render, no fetch
python3 build_map.py --set-high Tri-Cities=57   # hand-adjust a city's high (repeatable)
```

`--set-high CITY=F` replaces the model value shown for that city in this run
only. Nothing is saved, so the next run goes back to the model's highs.
Individual labels can also be nudged off their point with the optional
`(dx_pt, dy_pt)` on that city's entry in `CITIES` (Tri-Cities, Portland, and
Afton use it). The high is still sampled at the city's real location.

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
- **Smoothing and gridding:** total, snow, and mix amounts are resampled
  directly onto a regular grid in the map projection's own coordinates,
  with one cell per output pixel. They're then lightly gaussian-smoothed
  (about 11 km) *before* classifying, so the 0.25° cell edges round off.
  The categories are drawn with `imshow` and nearest interpolation, so
  neighboring types never blend into colors that aren't on the legend.
  Resampling on a lon/lat grid and letting cartopy project it would rotate
  the cells under Lambert and leave visible stair-steps at type edges.
- **Highs** are the max of `mx2t3` (max 2m temperature over the previous 3
  hours) for steps ending between 10am and 8pm local, roughly 7am–7pm,
  interpolated linearly to each city from the native grid. These are 0.25° grid-cell values, so
  cities in valleys next to high terrain can read a few degrees cool
  (and vice versa): the grid cell's mean elevation isn't the town's.
  Treat them as model guidance, not a hand-edited forecast.
- **Projection and size:** Lambert Conformal Conic centered on WA/OR/ID
  (−117.6°), with standard parallels at 43° and 48°N, so shapes and
  east-west scale stay true. PlateCarree stretches the map about 40%
  horizontally at this latitude. The output size is fixed at 2000×1567 px,
  and the zoom is fit to that frame: it spans `LAT_MIN`–`LAT_MAX`
  (41.95°–49.45°) along the central meridian, enough room for Bellingham's
  value label at the top and Medford at the bottom. The width follows from
  the frame's aspect ratio. To zoom, change those two latitudes and
  everything else adjusts.
- Border and coastline geometries are densified to 0.05° vertex spacing
  before drawing. Natural Earth stores the 49th parallel and the 42nd
  (OR/CA/NV) with very few vertices, and under Lambert those would draw as
  straight chords instead of following the parallel's curve. Without this,
  the US/Canada border showed up as several diverging lines.
