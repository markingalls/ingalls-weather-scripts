# WM-6 Ensemble Spread Chart

Generates a styled meteogram of the WindBorne WeatherMesh-6 (WM-6) ensemble
forecast for a pressure-level temperature at a single point, shown against
long-term climatology, for Ingalls Weather's Instagram. Same canvas
footprint and fonts as the
[Columbia Basin alerts map](../columbia-basin-alerts-map/), just a chart
instead of a map.

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA) and **850 mb**, but any
lat/lon and any WM-6 pressure level works.

## Files

- `fetch_forecast.py` — pulls the current WM-6 ensemble distribution
  (mean, percentiles, std) for a point/level from WindBorne and writes
  `forecast.json`. Requires `WB_API_KEY` in the environment (get one at
  https://app.windbornesystems.com/api_tokens). Run this first, any time
  you want the chart to reflect the latest model run.
- `fetch_climatology.py` — pulls 1991–2020 monthly climatology (mean +
  interannual std dev) for the same point/level from NOAA's NCEP/NCAR
  Reanalysis 1, via PSL's public OPeNDAP server. No API key needed. Only
  needs re-running if you change location or level.
- `build_chart.py` — renders `forecast.json` + `climatology.json` into
  `wm6_ensemble_spread.png`.
- `requirements.txt` / `setup.sh` — Python dependencies (no system packages
  needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export WB_API_KEY=...              # your WindBorne API key

# Default: KPSC, 850 mb
python3 fetch_forecast.py
python3 fetch_climatology.py --lat 46.2647 --lon -119.1189 --level 850
python3 build_chart.py

# Anywhere else, any level -- e.g. KPDX at 700 mb
python3 fetch_forecast.py --lat 45.5898 --lon -122.5951 --station KPDX --label "Portland, OR" --level 700
python3 fetch_climatology.py --lat 45.5898 --lon -122.5951 --level 700
python3 build_chart.py
```

`fetch_climatology.py` takes `--lat`/`--lon`/`--level` explicitly (rather
than reading `forecast.json`) so it can be run once and reused across
multiple forecast refreshes for the same point.

## Notes

- **Climatology source**: NCEP/NCAR Reanalysis 1, native 2.5° grid — we pull
  the nearest grid point via OPeNDAP array-slicing (no full-file download).
  The monthly mean/std (1991–2020) are interpolated to a smooth day-of-year
  curve so the climatology line doesn't step at month boundaries. This is a
  coarse-resolution reanalysis, so treat the climatology band as a regional
  reference rather than a station-exact normal.
- **Forecast source**: WM-6's calibrated ensemble percentiles
  (p01/p10/p25/p75/p90/p99) and mean, from the interpolated point-forecast
  endpoint. WM-6 runs 3-hourly out to 360h (15 days); `--max-hour` on
  `fetch_forecast.py` controls how far out to pull.
- Both datasets report temperature in °C already, so `build_chart.py` does
  no unit conversion.
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `columbia-basin-alerts-map/build_map.py` — edit `build_chart.py` directly
  to adjust.
