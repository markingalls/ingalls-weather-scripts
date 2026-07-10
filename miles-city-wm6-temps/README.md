# Miles City WM-6 3km High Temps Map

A one-off styled map of WindBorne WeatherMesh-6 3km high (daily max) 2m
temperatures over eastern Montana and the western Dakotas, centered on
Miles City, MT, and framed from a little west of Helena to a little east
of Bismarck. Styled to match Ingalls Weather's regional-scale map house
style (see [`../western-us-noaa-outlooks/`](../western-us-noaa-outlooks/)).

"High" for a given date is the max hourly 2m temperature between 8am and
8pm local time (America/Denver) — the daytime window that reliably
contains the daily peak without fetching all 24 hourly grids.

## Usage

```bash
bash setup.sh                          # first time / fresh environment only
export WB_API_KEY=...                  # https://app.windbornesystems.com/api_tokens
python build_map.py                    # defaults to the coming Sunday
python build_map.py --date 2026-07-12
```

Live data is fetched directly from the WindBorne API (13 hourly gridded
forecasts, ~90 MB each — the wm-6-3km archive only serves whole-run
snapshots, so each hourly fetch pulls every surface variable even though
only `temperature_2m` is used). Output PNG lands in `output/`.

To render from a previously-saved grid instead of fetching live (useful
for testing, or to avoid re-pulling ~1 GB of hourly grids), pass
`--file path/to/snapshot.npz` — see `fetch_daily_high()` in `build_map.py`
for the npz layout (`lat`, `lon`, `temp_k`, all cropped to the map's bbox).

## Files

- `build_map.py` — fetches the hourly grids, reduces them to a daily-max
  temperature field, and renders the map. Map domain, city labels, and the
  daytime window are all defined near the top — edit directly to adjust,
  or to repurpose this for a different region/date.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`states_lakes_slim.json` (lake fills), and `admin1_boundary_lines.json` /
`admin0_boundary_lines.json` (state/province and international borders).
The Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- The color scale (`TEMP_COLOR_TABLE` in `build_map.py`) is a fixed
  Kelvin-to-RGB curve, not rescaled to each day's min/max — the same color
  always means the same absolute temperature across every map this script
  renders. The colorbar sits below the map, centered, with Fahrenheit
  ticks on the bottom edge and Celsius ticks on the top edge (both are the
  same underlying Kelvin scale, via `secondary_xaxis`).
- City labels show that spot's forecast high on a second line, sampled
  from the resampled grid (see below) at each city's coordinates.
- Borders are drawn from Natural Earth's dedicated boundary-*line*
  datasets (`admin1_boundary_lines.json` / `admin0_boundary_lines.json`),
  not from state/country polygon outlines. Adjacent polygons in the
  `states_lakes_slim.json` dataset are simplified independently, so their
  outlines drift apart at shared borders (visible as a jagged double line
  at this map's zoom level); the line datasets store each border once, so
  neighboring regions share identical vertices. Both were filtered from
  `ne_10m_admin_1_states_provinces_lines.json` /
  `ne_10m_admin_0_boundary_lines_land.json` (same source repo as the other
  `../maps/` files) down to US/Canada/Mexico.
- The fetched grid is curvilinear (the model's native projection warped
  into lat/lon) and is resampled onto a plain regular lat/lon grid
  (`resample_to_regular_grid()`) before rendering. This isn't just
  cosmetic: rendering the curvilinear grid directly left a stripe of
  missing data at the corner of the map frame, and it turns out the
  resampled grid itself has to be padded past the plotted extent
  (`RESAMPLE_PAD_DEG`) too, or the same gap reappears -- cartopy's `imshow`
  warps the raster into the map projection by inverse-projecting each
  screen pixel back to lon/lat and sampling the source array, and right at
  the requested extent's edge that lookup can land a hair outside the
  source array's bounds and get masked out.
- wm-6-3km's forecast horizon is short (currently 72 hours), so `--date`
  only works for the next few days out.
