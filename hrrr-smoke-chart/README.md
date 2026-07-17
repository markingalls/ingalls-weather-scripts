# HRRR Near-Surface Smoke Chart

Generates a styled meteogram of NOAA HRRR near-surface smoke (mass density
at 8 m above ground) for one or more points, over a full 48-hour HRRR
cycle, for Ingalls Weather's Instagram. Same canvas footprint and fonts as
the [Columbia Basin alerts map](../columbia-basin-alerts-map/) and the
[850/700 mb temp chart](../850-700-temp-chart/), just a two-location smoke
line chart instead of a map or an ensemble spread.

Defaults to **Kennewick, WA** and **Hermiston, OR**, but any set of
lat/lon points works.

## Files

- `fetch_smoke.py` — finds the most recent HRRR run at a synoptic hour
  (00/06/12/18z -- the only cycles that run out to 48h; the other hourly
  cycles stop at 18h) that has finished processing through F48, pulls
  near-surface smoke (`MASSDEN:8 m above ground`) at each forecast hour via
  [Herbie](https://github.com/blaylockbk/Herbie) (NOAA's AWS Open Data
  bucket, no API key needed), and writes `smoke.json`. Run this first, any
  time you want the chart to reflect the latest run.
- `build_chart.py` — renders `smoke.json` into `hrrr_near_surface_smoke.png`.
- `requirements.txt` / `setup.sh` — Python dependencies (`herbie-data` +
  `cfgrib`/`eccodes` for pulling and decoding the GRIB2 subsets; no system
  packages needed beyond what pip installs).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: Kennewick, WA + Hermiston, OR
python3 fetch_smoke.py
python3 build_chart.py

# Any other set of points
python3 fetch_smoke.py --locations '[{"label":"Yakima, WA","lat":46.6021,"lon":-120.5059},{"label":"Walla Walla, WA","lat":46.0646,"lon":-118.3430}]'
python3 build_chart.py
```

## Notes

- **Source**: NOAA HRRR's smoke product (`MASSDEN` at 8 m above ground),
  fetched as a byte-range GRIB2 subset per forecast hour -- only that one
  field is downloaded from each hourly file, not the full multi-GB archive.
  Values come off the grid in kg/m³ and are converted to µg/m³.
- **Point extraction** is nearest-grid-cell (HRRR's native ~3 km grid), not
  interpolated -- fine at this resolution for a single point.
- **"Most recent 48 hour run"**: HRRR only runs its extended 48h forecast
  at 00/06/12/18z; the other 20 hourly cycles stop at F18.
  `select_latest_48h_run()` walks backward from the current synoptic hour
  until it finds a run whose F48 file actually exists on NOAA's servers
  (i.e. has finished processing), rather than assuming the most recent
  synoptic hour is already done.
- **Y-axis is AQI, not raw µg/m³.** `build_chart.py` converts each point's
  smoke concentration to an AQI value via the EPA's piecewise-linear PM2.5
  breakpoint table (`pm25_to_aqi()`, May 2024 revision). HRRR's near-surface
  smoke field is a smoke mass density, not a regulatory PM2.5 measurement --
  treating it as PM2.5 to derive an AQI is the same approximation
  NOAA/AirNow smoke-forecast tools make, good for a "how smoky will it
  feel" read rather than an official index. The plot area is shaded by AQI
  category (Good/Moderate/USG/Unhealthy/Very Unhealthy/Hazardous, official
  EPA colors, direct-labeled on the right edge) and fixed to
  `0 .. max(all series) * 1.25` (with a 100 AQI floor so Good+Moderate are
  always visible even on a quiet/smoke-free run), not autoscaled tightly to
  the data. Both location lines get a white halo so they stay legible over
  whichever band color they cross.
- **X-axis** is rendered in Pacific time (`America/Los_Angeles`, so it
  follows PDT/PST automatically), even though the run itself is fetched
  and labeled by init time in UTC/z per meteorological convention.
- Chart styling (fonts, colors, dimensions) mirrors
  `850-700-temp-chart/build_chart.py` -- edit `build_chart.py` directly to
  adjust. Reuses that project's same two accents (forest green `#164f29`
  for the first location, climatology orange `#c9531c` for the second) so
  a multi-line chart still reads as this brand's palette. Axis
  spines/ticks are black. Logo sits top-right, spanning the title/subtitle/
  legend header (the alerts-map/temp-chart projects place it bottom-right
  instead, since those don't have a full-width band legend competing for
  that corner).
