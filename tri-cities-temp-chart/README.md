# Tri-Cities Temperature Chart

Generates a styled 14-day temperature chart for Ingalls Weather's
Instagram: the last 7 days of **observed** daily highs from xmACIS, the
next 7 days of **forecast** highs from WindBorne MetaMesh, and a
1991-2020 climatology backdrop (also from xmACIS) -- daily P10/P25/P75/P90
percentile shading, the daily normal (sampled as P50, the median), and the
daily record high (pooled across the Tri-Cities area -- see Notes).
Same canvas footprint, fonts, and visual grammar as the
[850 mb chart](../850-700-temp-chart/) (climatology shading behind the
data line, a dotted vertical divider, a horizontal legend strip above the
plot) -- just adapted for a two-source, two-segment (observed/forecast)
series instead of one ensemble.

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA), but any ACIS station
(for the observed/climatology side) and any MetaMesh-covered METAR station
or lat/lon (for the forecast side) works.

## Files

- `fetch_observed.py` -- pulls the last 7 days of observed daily high
  temperature (element `maxt`) from ACIS (the same backend behind
  xmacis.rcc-acis.org) and writes `observed.json`. No API key needed.
  Defaults to ending yesterday, since today's high is usually still
  incomplete.
- `fetch_climatology.py` -- pulls, per calendar day of the year, the
  P10/P25/P50/P75/P90 percentiles for the 1991-2020 climate normals period
  (computed client-side from KPSC's daily series in that window -- see
  Notes; P50 is what the chart plots as the "daily normal"), and the
  record high + year, pooled across KPSC and the other long-running
  Tri-Cities-area stations (Kennewick, Richland) via ACIS's
  period-of-record `groupby` reduction. Writes `climatology.json`. No API
  key needed. Only needs re-running if you change station -- it has
  nothing to do with the current forecast run.
- `fetch_forecast.py` -- pulls the next 7 days of WindBorne MetaMesh
  forecast highs (max of `temperature_2m` in the 8am-8pm local window,
  same daytime-high definition
  [`columbia-basin-temps`](../columbia-basin-temps/) uses) and writes
  `forecast.json`. Requires `WB_API_KEY` in the environment (get one at
  https://app.windbornesystems.com/api_tokens). Run this any time you
  want the chart to reflect the latest model run.
- `build_chart.py` -- renders `observed.json` + `forecast.json` +
  `climatology.json` into `tri_cities_temp_chart.png`.
- `requirements.txt` / `setup.sh` -- Python dependencies (no system
  packages needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export WB_API_KEY=...              # your WindBorne API key

# Default: KPSC / Pasco, WA
python3 fetch_observed.py
python3 fetch_climatology.py       # only needed once per station
python3 fetch_forecast.py
python3 build_chart.py

# Anywhere else -- e.g. KPDX
python3 fetch_observed.py --sid "KPDX 5" --station KPDX --label "Portland, OR"
python3 fetch_climatology.py --sid "KPDX 5"
python3 fetch_forecast.py --station KPDX --label "Portland, OR"
python3 build_chart.py
```

`fetch_climatology.py` takes `--sid` explicitly (rather than reading
`observed.json`) so it can be run once and reused across many
observed/forecast refreshes for the same station.

## Notes

- **Observed/climatology source**: ACIS (the web-services backend behind
  xmacis.rcc-acis.org), station `KPSC 5` (ACIS's ICAO-code identifier for
  Tri-Cities Airport -- also known to ACIS as `PSC 3`, WBAN `24163 1`, or
  GHCN `USW00024163 6`, all interchangeable).
- **Percentiles (including the daily normal) have no direct ACIS
  element** -- ACIS's `normal` flag only exposes NCEI's separate
  mean-based normals product, and its `pct_xx_yyy` reduce code is a
  threshold-exceedance count, not a statistical percentile. So
  `fetch_climatology.py` pulls KPSC's daily `maxt` series for the
  1991-2020 climate normals window in one call and computes
  P10/P25/P50/P75/P90 per calendar day in Python (`numpy.percentile`),
  skipping any calendar day with fewer than 5 years of data (mainly a
  Feb 29 concern). The chart's "daily normal" line is this P50 (median),
  not a mean -- deliberately sampled from the same 1991-2020 series as the
  percentile bands, so the whole percentile backdrop comes from one
  consistent sample and period.
- **KPSC's raw daily data has a large historical gap** that eats into the
  nominal 1991-2020 window: daily `maxt` is essentially all missing
  1991-1997 (confirmed by pulling the full series), so the percentiles and
  daily normal are really drawn from **1998-2020 (~23 years)**, not a full
  30. `climatology.json`'s `percentile_years` field reports the real
  sample (vs. `percentile_period`, the nominal 1991-2020 target), and the
  chart's subtitle shows both.
- **Record highs are pooled across the Tri-Cities area, not KPSC alone**,
  and deliberately are *not* restricted to 1991-2020 -- KPSC's own usable
  record only goes back to 1998, which would understate true record highs
  for most of the year. `fetch_climatology.py` also pulls the full
  period-of-record daily series (via ACIS's `groupby: "year"`
  period-of-record reduction, one call per station) for Kennewick (COOP
  454154, back to 1894) and Richland (COOP 457015, back to 1944) -- both a
  few miles from KPSC in the same metro area -- and takes the max across
  all three per calendar day. Each day's `record_station` field in
  `climatology.json` records which station it came from; in practice
  Kennewick's much longer history supplies most of the year's records.
- **Forecast source**: WindBorne MetaMesh -- not a single model like
  WeatherMesh-6/WM-6, but WindBorne's multi-model blend, which fuses WM-6
  with other leading NWP/AI models. Queried by station ID (`stations=KPSC`
  on the plain `point_forecast` endpoint, not the model-specific
  `wm-6/point_forecast/interpolated` one `850-700-temp-chart` uses), which
  gets MetaMesh's bias-corrected "Station Forecast" mode (trained on that
  station's own METAR observations) rather than its coordinate-based
  ERA5-trained mode. Hourly `temperature_2m`, reduced to a daily high by
  taking the max across each local day's 8am-8pm samples. Deterministic
  (MetaMesh doesn't publish an ensemble spread the way WM-6 does), so the
  forecast segment is a single line, visually distinct from the
  climatology shading.
- **Today's split**: `observed.json` defaults to ending yesterday and
  `forecast.json` starts today, so the 14-day x-axis has no overlapping or
  double-counted day. A dotted vertical line marks the boundary. Today's
  own forecast high may be based on fewer samples than other days if the
  model run was initialized partway through the day (partial coverage of
  the 8am-8pm window) -- `forecast.json`'s `n_samples` field per day
  reflects this.
- **Y-axis** is fixed to `min(P10, observed, forecast) − 5°F` ..
  `max(P90, observed, forecast, record) + 3°F` across the whole series
  (not autoscaled), so a normal week doesn't get stretched just to fit a
  couple of record-high points -- extreme record spikes still get just
  enough headroom to stay on-chart, at a tighter margin than the rest of
  the range.
- **Layering** (back to front): percentile shading, then gridlines, then
  the daily-normal line, then record-high points, then the
  observed/forecast temperature line on top.
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `850-700-temp-chart/build_chart.py` -- edit `build_chart.py` directly to
  adjust. Observed/forecast temperature uses the same forest green
  (`#164f29`) as that chart's ensemble line (solid + filled markers for
  observed, dashed + hollow markers for forecast); the daily-normal line
  reuses that chart's climatology orange (`#c9531c`); record highs get
  their own dark red (`#a3242b`) star markers. The three percentile bands
  are drawn as adjacent (not nested/overlapping) fills, each its own
  color rather than one hue tapered by alpha: light blue for 10th-25th,
  neutral gray for 25th-75th, light red for 75th-90th. Every
  observed/forecast point is labeled with its value (white-halo text, via
  `matplotlib.patheffects`) so exact highs don't require reading off the
  axis. The legend is a 7-item, 2-row strip (vs. that chart's 4-item
  single row), so the title/subtitle sit a bit higher to clear it -- see
  the comment above `subtitle_y` in `build_chart.py` if you change the
  legend's item count or column layout.
