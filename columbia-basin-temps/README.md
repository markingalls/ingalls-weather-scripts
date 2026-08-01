# Columbia Basin Temperature Map

The canonical styled map of 2m temperatures over the Columbia Basin (same
domain as [`../columbia-basin-alerts-map/`](../columbia-basin-alerts-map/):
North Bend, WA down to the Baker City, OR corridor). Supersedes the old
`columbia-basin-wm6-temps/` (WM-6 3km-only, high-only) — everything that
could do is one mode of this script.

Supports four forecast sources, all at full native resolution, and five
metrics:

| `--source`     | Model                          | Native resolution | Via |
|----------------|---------------------------------|--------------------|-----|
| `wm6-3km` (default) | WindBorne WeatherMesh-6     | 3 km               | WindBorne API (needs `WB_API_KEY`) |
| `hrrr`         | NOAA HRRR CONUS                 | 3 km               | Herbie, from AWS Open Data / NOMADS |
| `ecmwf-ifs`    | ECMWF IFS                       | 0.25°, 3-hourly steps | Herbie, from ECMWF Open Data |
| `ecmwf-aifs`   | ECMWF AIFS                      | 0.25°, 6-hourly steps | Herbie, from ECMWF Open Data |

| `--metric`        | Definition |
|--------------------|------------|
| `high` (default)  | Max hourly 2m temp, 8am-8pm local time — the daytime window that reliably contains the daily peak. |
| `low`             | Min hourly 2m temp, 2am-9am local time — the pre-dawn window that reliably contains the daily trough. Not a true overnight low spanning midnight into the next morning; see Notes. |
| `time`            | Temp at one specific local hour, via `--hour H` (0-23). |
| `fire`            | Peak SPC-style fire weather risk (None/Elevated/Critical/Extreme) over all 24 local hours. `wm6-3km` only -- see Notes and Fire weather below. |
| `min_rh`          | Lowest 2m relative humidity over all 24 local hours. `wm6-3km` only -- same continuous colormap/colorbar style as `high`/`low`/`time`, just %RH instead of °F/°C. See Notes. |

## Usage

```bash
bash setup.sh                                              # first time / fresh environment only
export WB_API_KEY=...                                       # only needed for --source wm6-3km
python build_map.py                                         # WM-6 3km high, coming Sunday
python build_map.py --source hrrr --metric low --date 2026-07-12
python build_map.py --source ecmwf-ifs --metric time --hour 17 --date 2026-07-12
python build_map.py --source ecmwf-aifs --date 2026-07-12
python build_map.py --metric fire --date 2026-07-12
python build_map.py --metric min_rh --date 2026-07-12
```

`wm6-3km` fetches hourly gridded forecasts directly from the WindBorne API
(one per hour the requested metric's local-hour window needs — 13 for
`high`, 8 for `low`, 1 for `time` — each ~90 MB, since the wm-6-3km archive
only serves whole-run snapshots with every surface variable even though
only `temperature_2m` is used).

`hrrr` / `ecmwf-ifs` / `ecmwf-aifs` are fetched at full native resolution
via [Herbie](https://herbie.readthedocs.io), which pulls each model's own
free GRIB2 distribution directly from its source (NOAA's AWS Open
Data/NOMADS for HRRR, ECMWF's Open Data program for IFS/AIFS) using
byte-range requests, so only the `temperature_2m` record is downloaded
from each file, not the whole multi-GB archive. No API key needed. A full
run takes well under a minute.

IFS publishes 3-hourly steps and AIFS 6-hourly — coarser than
wm6-3km/hrrr's hourly steps — so `--metric time` snaps to the nearest step
actually available (`fetch_ecmwf()`'s `snap_fxx_list()`), and the map's
title reflects the local hour that was actually plotted, not necessarily
the one requested; a console note explains the substitution when one
happens. `high`/`low` just reduce over whichever native steps fall in the
window (so IFS gets ~4-5 samples across the daytime window, AIFS ~2).

### Fire weather (`--metric fire`)

Plots peak fire weather risk instead of temperature, using [SPC's Fire
Weather Outlook criteria](https://www.spc.noaa.gov/misc/about.html#FireWx):
a cell reaches **Elevated**, **Critical**, or **Extreme** once that tier's
sustained 10m wind, 2m relative humidity, and 2m temperature thresholds
are all met *simultaneously* in any single hour of the 24 local hours of
the target date (`compute_fire_category_grid()`; relative humidity is
derived from `temperature_2m`/`dewpoint_2m` via the Magnus formula, wind
from `wind_u_10m`/`wind_v_10m`). SPC's own criteria also require this to
hold for >= 3 consecutive hours; this script doesn't enforce that minimum
duration, so it will flag brief spikes SPC's own product wouldn't:

| Tier | Sustained wind | RH | Temp |
|------|-----------------|-----|------|
| Elevated | ≥ 15 mph | ≤ 25% | ≥ 55°F |
| Critical | ≥ 20 mph | ≤ 20% | ≥ 60°F |
| Extreme  | ≥ 30 mph | ≤ 13% | ≥ 70°F |

SPC's RH thresholds are regional (it publishes a critical-RH-by-region
map); this domain sits in the Columbia Basin's own "≤20%" critical band,
so that's what's fixed into `FIRE_CATEGORIES` rather than sampled
per-pixel. The western fringe of this map's domain (Portland/Salem/Puget
Sound, west of the Cascades) is technically in a more humid SPC region
(≤25%/≤30%), so fire risk there may be modestly under-reported.

Needs all 24 hourly wm6-3km grids (rather than high/low's 13/8-hour
window), and only wm6-3km, since Herbie's hrrr/ecmwf-ifs/ecmwf-aifs paths
fetch just `temperature_2m` — no dewpoint or wind components (yet).

Since most of the map has no fire risk on a given day, this metric styles
its basemap like `../columbia-basin-alerts-map/build_map.py` instead of
the temperature metrics' bare-white-water/no-fill-land look: land is
filled `#e3e1da` (below the risk raster, via `draw_land()`'s `zorder`
param) and state/international borders use that map's softer beige-gray
(`#b9b6ac`/`#9a978c`) instead of the temperature metrics' dark brown, so
a plain "no risk anywhere" area still reads as a finished map rather than
missing data. It also saves with `bbox_inches="tight"` (same as the
alerts map), since its single legend row needs less room below the frame
than the temperature metrics' colorbar-plus-tick-labels do -- without it
the fixed canvas leaves a dead strip at the bottom.

### Lowest relative humidity (`--metric min_rh`)

Plots the day's lowest 2m relative humidity instead of temperature, using
the same continuous-colormap rendering as `high`/`low`/`time` (fixed color
scale, colorbar with tick labels below the map, bare-outline coastline,
dark-brown borders) rather than `fire`'s discrete swatch style — just %RH
in place of °F/°C. Relative humidity is derived from
`temperature_2m`/`dewpoint_2m` via the Magnus formula
(`compute_min_rh_grid()`), reduced to each cell's minimum across all 24
local hours of the target date. `RH_COLOR_TABLE` is a fixed 0-100% scale
(not rescaled per map): dry reads red/orange, wet reads blue, so the same
shade always means the same %RH across every map this script renders.

Needs all 24 hourly wm6-3km grids (like `fire`), and only wm6-3km, since
Herbie's hrrr/ecmwf-ifs/ecmwf-aifs paths fetch just `temperature_2m` — no
dewpoint.

Output PNG lands in `output/`. To render from a previously-saved grid
instead of fetching live (useful for testing, or to avoid re-fetching),
pass `--file path/to/snapshot.npz` — see `fetch_wm6_3km()` /
`fetch_hrrr()` / `fetch_ecmwf()` / `fetch_wm6_3km_24h()` in
`build_map.py` for the npz layout: `lat`, `lon`, plus `temp_k`
(high/low/time), `category` (fire, already reduced via
`compute_fire_category_grid()`), or `rh_pct` (min_rh, already reduced via
`compute_min_rh_grid()`), plus `meta_kind`/`meta_value` for the subtitle's
"Init ..." line — omit both and it reads "unknown". `--source` /
`--metric` / `--hour` still need to be passed alongside `--file` since the
snapshot only holds the grid, not the labels.

## Files

- `build_map.py` — fetches from whichever source was requested, reduces to
  the requested metric, and renders the map. Map domain, city labels, color
  table, and the high/low hour windows are all defined near the top — edit
  directly to adjust.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, and cfgrib/eccodes -- GRIB2 decoding for hrrr/ecmwf-ifs/
  ecmwf-aifs -- needs libeccodes, both only installing via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`admin1_boundary_lines.json` / `admin0_boundary_lines.json` (state/province
and international borders), `land_slim.json` (coastline), and
`washington_roads.geojson` / `oregon_roads.geojson` / `idaho_roads_north.geojson`
(highways — one file per state, no separate/duplicate regional extract).
US state lines in `admin1_boundary_lines.json` are Census TIGER/Line
boundaries (not Natural Earth's 10m generalization), so they track rivers
like the WA/OR border tightly instead of visibly cutting corners — see
Notes. The Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- The color scale (`TEMP_COLOR_TABLE` in `build_map.py`) is a fixed
  Kelvin-to-RGB curve, not rescaled to each map's min/max — the same color
  always means the same absolute temperature across every map this script
  renders. The colorbar sits below the map, centered, with Fahrenheit ticks
  on the bottom edge and Celsius ticks on the top edge (both are the same
  underlying Kelvin scale, via `secondary_xaxis`) and only draws the slice
  of the table actually visible that day.
- City labels show that spot's forecast value on a second line, sampled
  from the resampled grid, tucked in tight below the name via points-based
  offsets (constant regardless of map scale) rather than degrees.
- Borders are drawn from dedicated boundary-*line* datasets
  (`admin1_boundary_lines.json` / `admin0_boundary_lines.json`), not from
  state/country polygon outlines -- polygon-outline datasets simplify each
  polygon independently, so adjacent shapes' outlines drift apart at
  shared borders (a jagged double line at this map's zoom level); the
  line datasets store each border once, so neighboring regions share
  identical vertices. US state lines are Census TIGER/Line boundaries
  (full legal-boundary precision, e.g. following the Columbia River's
  actual channel rather than Natural Earth's 10m generalization of it),
  merged into a single deduplicated line network the same way and
  simplified to ~20m tolerance -- finer than the map ever resolves, but
  far smaller than TIGER's raw ~1m vertices. International (admin0) and
  Canadian provincial lines are still Natural Earth 10m, since TIGER only
  covers the US.
- The coastline (`land_slim.json`, the same layer `columbia-basin-alerts-map`
  uses for its land fill) is drawn outline-only here, with no fill, so it
  traces the Puget Sound without covering up the temperature color over
  water. Highways are motorway + trunk from the WA/OR/ID road files, styled
  the same pastel blue/orange as `columbia-basin-alerts-map`, and drawn on
  top of the state/international border lines rather than under them.
- Every source's native grid -- wm6-3km's and HRRR's curvilinear projected
  grid, IFS/AIFS's regular 0.25° lat/lon grid -- is cropped to the map bbox
  then resampled onto the same padded regular lat/lon grid before rendering
  (`resample_to_regular_grid()`), so every source renders through identical
  downstream code regardless of its native projection. The padding isn't
  just cosmetic: rendering a curvilinear grid directly leaves a stripe of
  missing data at the corner of the map frame, and the resampled grid
  itself has to be padded past the plotted extent (`RESAMPLE_PAD_DEG`) too,
  or the same gap reappears -- cartopy's `imshow` warps the raster into the
  map projection by inverse-projecting each screen pixel back to lon/lat
  and sampling the source array, and right at the requested extent's edge
  that lookup can land a hair outside the source array's bounds and get
  masked out.
- HRRR's GRIB2 longitude is 0-360°; it's converted to -180..180° before
  cropping, same convention as everything else in this script.
- The `low` metric's 2am-9am window is a same-calendar-day approximation,
  not a true overnight low spanning the previous evening into this
  morning's sunrise — matches how `high`'s daytime window avoids fetching
  all 24 hourly grids, at the cost of missing lows that occur right around
  midnight.
- The LON range is widened symmetrically beyond `columbia-basin-alerts-map`'s
  original extent so the rendered frame fills to the title's left margin
  and mirrors it on the right, rather than sitting centered with unused
  space on both sides. Just picking a wider degree box doesn't reliably
  land on that outcome: cartopy shrinks the axes to preserve the
  projection's true geographic aspect ratio within `AXES_RECT`, so how
  much frame-width-per-degree that produces isn't obvious ahead of time.
  The actual `LON_MIN`/`LON_MAX` values were derived by rendering once,
  measuring the frame's actual left/right pixel margins (a black-pixel row
  scan) and the title's left inset, then solving for the scale factor that
  makes the frame width equal `image_width - 2 * title_inset_px`.
- `fire` and `min_rh` need all 24 local hours of the target date
  (`fetch_wm6_3km_24h()`), but a same-day request's earliest hours can
  already be in the past relative to the current run's `forecast_zero` --
  those hours are skipped (with a console note) rather than erroring, and
  the day's peak/lowest value is reduced over whichever hours remain.
- wm-6-3km's forecast horizon is short (currently 72 hours); HRRR's is ~48
  hours (18 for non-synoptic-hour init cycles, `select_hrrr_run()` picks
  whichever recent cycle actually covers the requested window); IFS/AIFS
  reach 15 days — `--date` only works within whichever source's horizon.
- Herbie caches downloaded GRIB2 subsets under `~/data/<model>/` (its
  default `save_dir`, outside this repo) rather than this project's own
  `data/`.
