# HRRR Smoke Charts

Generates styled meteograms of NOAA HRRR smoke for one or more points, over
a full 48-hour HRRR cycle, for Ingalls Weather's Instagram. Same canvas
footprint and fonts as the
[Columbia Basin alerts map](../columbia-basin-alerts-map/) and the
[850/700 mb temp chart](../850-700-temp-chart/), just a two-location smoke
line chart instead of a map or an ensemble spread.

Two smoke fields, each renderable multiple ways:

- **`--variable near_surface`** (default) -- `MASSDEN` @ 8 m above ground.
  Rendered either as **`--units aqi`** (default: AQI, PM2.5-equivalent, with
  EPA category bands) or **`--units raw`** (µg/m³, shaded with NOAA's own
  HRRR-Smoke concentration scale).
- **`--variable column`** -- `COLMD`, vertically integrated smoke (the whole
  atmospheric column, not just what's mixed to the surface). Always raw
  units (mg/m²) -- AQI is a surface-air-quality concept and doesn't apply to
  a column total, so `--units aqi` is ignored for this variable.

Defaults to **Kennewick, WA** and **Hermiston, OR**, but any set of lat/lon
points works.

## Files

- `fetch_smoke.py` — finds the most recent HRRR run at a synoptic hour
  (00/06/12/18z -- the only cycles that run out to 48h; the other hourly
  cycles stop at 18h) that has finished processing through F48, pulls
  **both** smoke fields (near-surface + vertically integrated) at each
  forecast hour via [Herbie](https://github.com/blaylockbk/Herbie) (NOAA's
  AWS Open Data bucket, no API key needed), and writes `smoke.json`. Run
  this once per run you care about -- `build_chart.py` can then render any
  variable/units combination from that same file without re-fetching.
- `build_chart.py` — renders `smoke.json` into a PNG. Output defaults to
  `hrrr_<variable>_smoke_<units>.png` (e.g. `hrrr_near_surface_smoke_aqi.png`,
  `hrrr_near_surface_smoke_raw.png`, `hrrr_column_smoke_raw.png`); pass
  `--output` to override.
- `requirements.txt` / `setup.sh` — Python dependencies (`herbie-data` +
  `cfgrib`/`eccodes` for pulling and decoding the GRIB2 subsets; no system
  packages needed beyond what pip installs).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: Kennewick, WA + Hermiston, OR
python3 fetch_smoke.py

python3 build_chart.py                                          # near-surface, AQI (default)
python3 build_chart.py --units raw                               # near-surface, raw µg/m3, NOAA color scale
python3 build_chart.py --variable column                         # vertically integrated, mg/m2, NOAA color scale

# Any other set of points
python3 fetch_smoke.py --locations '[{"label":"Yakima, WA","lat":46.6021,"lon":-120.5059},{"label":"Walla Walla, WA","lat":46.0646,"lon":-118.3430}]'
python3 build_chart.py
```

## Notes

- **Source**: NOAA HRRR's smoke product, fetched as a byte-range GRIB2
  subset per field per forecast hour -- only that one field is downloaded
  from each hourly file, not the full multi-GB archive. `fetch_smoke.py`
  converts each field to whatever units NOAA's own HRRR-Smoke graphics
  (rapidrefresh.noaa.gov/hrrr/HRRRsmoke/) use for it: near-surface comes off
  the grid in kg/m³ and is converted to µg/m³ (×1e9); column comes off the
  grid in kg/m² and is converted to mg/m² (×1e6).
- **Point extraction** is nearest-grid-cell (HRRR's native ~3 km grid), not
  interpolated -- fine at this resolution for a single point.
- **"Most recent 48 hour run"**: HRRR only runs its extended 48h forecast
  at 00/06/12/18z; the other 20 hourly cycles stop at F18.
  `select_latest_48h_run()` walks backward from the current synoptic hour
  until it finds a run whose F48 file actually exists on NOAA's servers
  (i.e. has finished processing), rather than assuming the most recent
  synoptic hour is already done.
- **AQI y-axis** (`--variable near_surface --units aqi`, the default):
  `build_chart.py` converts each point's smoke concentration to an AQI
  value via the EPA's piecewise-linear PM2.5 breakpoint table
  (`pm25_to_aqi()`, May 2024 revision). HRRR's near-surface smoke field is a
  smoke mass density, not a regulatory PM2.5 measurement -- treating it as
  PM2.5 to derive an AQI is the same approximation NOAA/AirNow
  smoke-forecast tools make, good for a "how smoky will it feel" read
  rather than an official index. The plot area is shaded by AQI category
  (Good/Moderate/USG/Unhealthy/Very Unhealthy/Hazardous, official EPA
  colors, direct-labeled on the right edge) and fixed to
  `0 .. max(all series) * 1.25` (with a 100 AQI floor so Good+Moderate are
  always visible even on a quiet/smoke-free run), not autoscaled tightly to
  the data.
- **Raw y-axis** (`--units raw`, either variable): shaded with NOAA's own
  HRRR-Smoke concentration color scale instead of AQI bands -- 13 bins +
  an unbounded top (magenta arrow on NOAA's maps, same color here), sampled
  directly off the legend swatches of NOAA's published graphics, with
  concentration edges matched per variable/units (near-surface: 1, 2, 4, 6,
  8, 12, 16, 20, 25, 30, 40, 60, 100, 200 µg/m³; column: 1, 4, 7, 11, 15, 20,
  25, 30, 40, 50, 75, 150, 250, 500 mg/m²). Values below the first bin are
  left unshaded, same as NOAA's maps. Unlike the AQI bands, these aren't
  direct-labeled -- 13 bins is too fine-grained to label without cluttering
  a time series, and NOAA's own maps only label the separate colorbar
  legend, not the shaded field itself. y-max is fixed to
  `max(all series) * 1.25` with a per-variable floor (10 µg/m³ near-surface,
  20 mg/m² column) so a quiet run still shows some headroom.
- Both location lines always get a white halo (AQI bands or the raw NOAA
  scale both put color behind them) so they stay legible over whichever
  band color they cross.
- **X-axis** is rendered in Pacific time (`America/Los_Angeles`, so it
  follows PDT/PST automatically), even though the run itself is fetched
  and labeled by init time in UTC/z per meteorological convention.
- Chart styling (fonts, dimensions) mirrors `850-700-temp-chart/build_chart.py`
  -- edit `build_chart.py` directly to adjust. Location lines are forest
  green `#164f29` (also used in that project, the logo's pine tree) for the
  first location, dark blue `#0b3d91` for the second. Axis spines/ticks are
  black. Logo sits top-right, spanning the title/subtitle/legend header
  (the alerts-map/temp-chart projects place it bottom-right
  instead, since those don't have a full-width band legend competing for
  that corner).
