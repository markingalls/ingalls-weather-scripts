# Columbia Basin Temperature Map

The canonical styled map of 2m temperatures over the Columbia Basin (same
domain as [`../columbia-basin-alerts-map/`](../columbia-basin-alerts-map/):
North Bend, WA down to the Baker City, OR corridor), adapted from
[`../miles-city-wm6-temps/`](../miles-city-wm6-temps/)'s rendering approach
and house style. Supersedes the old `columbia-basin-wm6-temps/` (WM-6
3km-only, high-only) — everything that could do is one mode of this script.

Supports four forecast sources and three temperature metrics:

| `--source`     | Model                          | Native resolution | Via |
|----------------|---------------------------------|--------------------|-----|
| `wm6-3km` (default) | WindBorne WeatherMesh-6     | 3 km               | WindBorne API (needs `WB_API_KEY`) |
| `hrrr`         | NOAA HRRR CONUS                 | 3 km               | Open-Meteo |
| `ecmwf-ifs`    | ECMWF IFS                       | 0.25°              | Open-Meteo |
| `ecmwf-aifs`   | ECMWF AIFS                      | 0.25°              | Open-Meteo |

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

`hrrr` / `ecmwf-ifs` / `ecmwf-aifs` go through
[Open-Meteo](https://open-meteo.com), which serves point forecasts rather
than gridded downloads, so `fetch_open_meteo()` queries a grid of points
spaced `OPEN_METEO_GRID_DEG` (0.15°, ~3,000 points over this domain) apart
in batches of 200, then interpolates the same way the WM-6 path
interpolates its native curvilinear grid. No API key needed. A full run
takes about 30 seconds.

Output PNG lands in `output/`. To render from a previously-saved grid
instead of fetching live (useful for testing, or to avoid re-fetching),
pass `--file path/to/snapshot.npz` — see `fetch_wm6_3km()` /
`fetch_open_meteo()` in `build_map.py` for the npz layout (`lat`, `lon`,
`temp_k`, plus `meta_kind`/`meta_value` for the subtitle's "Init ..." or
"Retrieved ..." line — omit both and it reads "unknown"). `--source` /
`--metric` / `--hour` still need to be passed alongside `--file` since the
snapshot only holds the grid, not the labels.

## Files

- `build_map.py` — fetches from whichever source was requested, reduces to
  the requested metric, and renders the map. Map domain, city labels, color
  table, and the high/low hour windows are all defined near the top — edit
  directly to adjust.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`admin1_boundary_lines.json` / `admin0_boundary_lines.json` (state/province
and international borders), `land_slim.json` (coastline), and
`washington_roads.geojson` / `oregon_roads.geojson` / `idaho_roads_north.geojson`
(highways — one file per state, no separate/duplicate regional extract).
The Ingalls Weather logo lives in
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
- Borders are drawn from Natural Earth's dedicated boundary-*line*
  datasets, not polygon outlines — see the Miles City README for why.
- The coastline (`land_slim.json`, the same layer `columbia-basin-alerts-map`
  uses for its land fill) is drawn outline-only here, with no fill, so it
  traces the Puget Sound without covering up the temperature color over
  water. Highways are motorway + trunk from the WA/OR/ID road files, styled
  the same pastel blue/orange as `columbia-basin-alerts-map`, and drawn on
  top of the state/international border lines rather than under them.
- Both the WM-6 curvilinear native grid and the Open-Meteo sources' scattered
  query-point grid are resampled onto the same padded regular lat/lon grid
  before rendering (to avoid corner rendering gaps in the NearsidePerspective
  projection) — see the Miles City README for the full explanation of why.
- The Open-Meteo sources' 0.15° query grid is coarser than HRRR's native 3 km
  grid (and, in sharp terrain, coarser than what smoothly resolves a single
  cold or hot outlier point), so a lone high-elevation grid cell can render
  as a sharp-edged patch rather than a smooth gradient — a real value, just
  under-sampled. Lower `OPEN_METEO_GRID_DEG` in `build_map.py` for higher
  fidelity at the cost of more requests/runtime.
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
  hours; IFS/AIFS reach 15 days — `--date` only works within whichever
  source's horizon.
