# Columbia Basin Temperature Map

The canonical styled map of 2m temperatures over the Columbia Basin (same
domain as [`../columbia-basin-alerts-map/`](../columbia-basin-alerts-map/):
North Bend, WA down to the Baker City, OR corridor), adapted from
[`../miles-city-wm6-temps/`](../miles-city-wm6-temps/)'s rendering approach
and house style. Supersedes the old `columbia-basin-wm6-temps/` (WM-6
3km-only, high-only) — everything that could do is one mode of this script.

Supports four forecast sources, all at full native resolution, and three
temperature metrics:

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

## Usage

```bash
bash setup.sh                                              # first time / fresh environment only
export WB_API_KEY=...                                       # only needed for --source wm6-3km
python build_map.py                                         # WM-6 3km high, coming Sunday
python build_map.py --source hrrr --metric low --date 2026-07-12
python build_map.py --source ecmwf-ifs --metric time --hour 17 --date 2026-07-12
python build_map.py --source ecmwf-aifs --date 2026-07-12
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

Output PNG lands in `output/`. To render from a previously-saved grid
instead of fetching live (useful for testing, or to avoid re-fetching),
pass `--file path/to/snapshot.npz` — see `fetch_wm6_3km()` /
`fetch_hrrr()` / `fetch_ecmwf()` in `build_map.py` for the npz layout
(`lat`, `lon`, `temp_k`, plus `meta_kind`/`meta_value` for the subtitle's
"Init ..." line — omit both and it reads "unknown"). `--source` /
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
  renders (and across the Miles City version, since they share the same
  table). The colorbar sits below the map, centered, with Fahrenheit ticks
  on the bottom edge and Celsius ticks on the top edge (both are the same
  underlying Kelvin scale, via `secondary_xaxis`) and only draws the slice
  of the table actually visible that day.
- City labels show that spot's forecast value on a second line, sampled
  from the resampled grid, tucked in tight below the name via points-based
  offsets (constant regardless of map scale) rather than degrees.
- Borders are drawn from dedicated boundary-*line* datasets, not polygon
  outlines — see the Miles City README for why. US state lines are
  Census TIGER/Line boundaries (full legal-boundary precision, e.g.
  following the Columbia River's actual channel rather than Natural
  Earth's 10m generalization of it), merged into a single deduplicated
  line network (so adjacent states still share identical vertices at
  their common border, same reasoning as the dedicated-line-dataset
  approach generally) and simplified to ~20m tolerance -- finer than
  the map ever resolves, but far smaller than TIGER's raw ~1m vertices.
  International (admin0) and Canadian provincial lines are still Natural
  Earth 10m, since TIGER only covers the US.
- The coastline (`land_slim.json`, the same layer `columbia-basin-alerts-map`
  uses for its land fill) is drawn outline-only here, with no fill, so it
  traces the Puget Sound without covering up the temperature color over
  water. Highways are motorway + trunk from the WA/OR/ID road files, styled
  the same pastel blue/orange as `columbia-basin-alerts-map`, and drawn on
  top of the state/international border lines rather than under them.
- Every source's native grid -- wm6-3km's and HRRR's curvilinear projected
  grid, IFS/AIFS's regular 0.25° lat/lon grid -- is cropped to the map bbox
  then resampled onto the same padded regular lat/lon grid before rendering
  (to avoid corner rendering gaps in the NearsidePerspective projection, and
  so every source renders through identical downstream code) — see the
  Miles City README for the full explanation of the padding.
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
  space on both sides — see the Miles City README for why a wider box
  alone doesn't do this.
- wm-6-3km's forecast horizon is short (currently 72 hours); HRRR's is ~48
  hours (18 for non-synoptic-hour init cycles, `select_hrrr_run()` picks
  whichever recent cycle actually covers the requested window); IFS/AIFS
  reach 15 days — `--date` only works within whichever source's horizon.
- Herbie caches downloaded GRIB2 subsets under `~/data/<model>/` (its
  default `save_dir`, outside this repo) rather than this project's own
  `data/`.
