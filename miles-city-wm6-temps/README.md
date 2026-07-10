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

Shared basemap data lives one level up in [`../maps/`](../maps/)
(`states_lakes_slim.json`), and the Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- The color ramp (YlOrRd) is a single-hue sequential ramp scaled to the
  actual min/max present that day, not a fixed scale — it will look
  different run to run.
- wm-6-3km's forecast horizon is short (currently 72 hours), so `--date`
  only works for the next few days out.
