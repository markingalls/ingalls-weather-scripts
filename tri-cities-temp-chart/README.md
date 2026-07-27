# Tri-Cities Temperature Chart

Generates a styled 14-day temperature chart for Ingalls Weather's
Instagram: the last 7 days of **observed** daily highs from xmACIS, the
next 7 days of **forecast** highs from WindBorne WeatherMesh-6 (WM-6), and
a 30-year climatology backdrop (also from xmACIS) -- daily P10/P25/P75/P90
percentile shading, the daily normal (mean), and the daily record high.
Same canvas footprint, fonts, and visual grammar as the
[850 mb chart](../850-700-temp-chart/) (climatology shading behind the
data line, a dotted vertical divider, a horizontal legend strip above the
plot) -- just adapted for a two-source, two-segment (observed/forecast)
series instead of one ensemble.

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA), but any ACIS station
(for the observed/climatology side) and any lat/lon (for the forecast
side) works.

## Files

- `fetch_observed.py` -- pulls the last 7 days of observed daily high
  temperature (element `maxt`) from ACIS (the same backend behind
  xmacis.rcc-acis.org) and writes `observed.json`. No API key needed.
  Defaults to ending yesterday, since today's high is usually still
  incomplete.
- `fetch_climatology.py` -- pulls, per calendar day of the year, the
  P10/P25/P75/P90 percentiles (computed client-side from ACIS's full
  period-of-record daily series -- see Notes), the 1991-2020 daily normal
  mean (ACIS's own precomputed `normal` element), and the record high +
  year (via ACIS's period-of-record `groupby` reduction). Writes
  `climatology.json`. No API key needed. Only needs re-running if you
  change station -- it has nothing to do with the current forecast run.
- `fetch_forecast.py` -- pulls the next 7 days of WM-6 forecast highs
  (max of `temperature_2m` in the 8am-8pm local window, same daytime-high
  definition [`columbia-basin-temps`](../columbia-basin-temps/) uses) and
  writes `forecast.json`. Requires `WB_API_KEY` in the environment (get
  one at https://app.windbornesystems.com/api_tokens). Run this any time
  you want the chart to reflect the latest model run.
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
python3 fetch_forecast.py --lat 45.5898 --lon -122.5951 --station KPDX --label "Portland, OR"
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
- **Percentiles have no direct ACIS element** -- ACIS's `normal` flag only
  exposes NCEI's mean-based normals, and its `pct_xx_yyy` reduce code is a
  threshold-exceedance count, not a statistical percentile. So
  `fetch_climatology.py` pulls the full period-of-record daily `maxt`
  series in one call and computes P10/P25/P75/P90 per calendar day in
  Python (`numpy.percentile`), skipping any calendar day with fewer than 5
  years of data (mainly a Feb 29 concern).
- **KPSC's raw daily data has a large historical gap**: ACIS reports a
  period of record back to 1945, but daily `maxt` is essentially all
  missing from 1947 through 1997 (confirmed by pulling the full series --
  a small usable fragment covers 1945-46, then nothing again until 1998).
  So both the percentile band and the record highs are effectively drawn
  from **~1998-present** (plus that small 1940s fragment) rather than a
  clean, continuous 30 or 80 year record. The chart's subtitle reports the
  actual sample size (years, not just the min/max year span) so this is
  visible at a glance; `climatology.json`'s `record_note` field spells it
  out further. If you point this at a station with a cleaner period of
  record, this caveat may not apply.
- **The daily normal (mean)** is unaffected by that gap -- it's NCEI's own
  smoothed 1991-2020 normals product, independent of what ACIS has on file
  for the raw daily series, pulled via `elems: [{"name": "maxt",
  "normal": "1"}]`.
- **Record highs** come from ACIS's own `groupby: "year"` period-of-record
  reduction (one call covers all 366 calendar days), not a client-side
  scan -- see the query in `fetch_records()` in `fetch_climatology.py`.
- **Forecast source**: WM-6's point-forecast `temperature_2m`, at its
  native ~3-hourly cadence, reduced to a daily high by taking the max
  across each local day's 8am-8pm samples -- not an ensemble spread (WM-6
  does have ensemble percentiles, like `850-700-temp-chart` uses, but this
  chart's forecast segment is a single line to keep it visually distinct
  from the climatology shading).
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
  observed, dashed + hollow markers for forecast); climatology shading and
  the normal line reuse that chart's climatology orange (`#c9531c`);
  record highs get their own dark red (`#a3242b`) star markers. The
  legend is a 6-item, 2-row strip (vs. that chart's 4-item single row),
  so the title/subtitle sit a bit higher to clear it -- see the comment
  above `subtitle_y` in `build_chart.py` if you change the legend's item
  count or column layout.
