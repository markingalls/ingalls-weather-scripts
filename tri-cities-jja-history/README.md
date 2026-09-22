# Tri-Cities JJA History

Companion graphics to [`tri-cities-jja-calendar`](../tri-cities-jja-calendar/):
instead of one summer's daily highs, longer-run views of Tri-Cities JJA
(June-July-August) high temperature vs. the 1991-2020 average. Two charts
share one `fetch_jja_history.py`/`jja_history.json` pipeline:

- **History grid** (`build_history_grid.py`) -- a year-over-year grid of
  JJA daily-high *departure* from normal: years across as columns,
  June/July/August average departure stacked as rows, a gap, then the
  full-season average departure as a bottom row. Purple-blue-white-orange-
  red-maroon departure spectrum, same fonts/branding as the calendar, on
  the same 16x9 canvas. Meant for a handful of recent years side by side
  (defaults to 2019-present) -- one column per year doesn't scale to
  decades.
- **Trend chart** (`build_trend_chart.py`) -- a line chart of *raw* JJA
  mean high temperature across the station's full usable period of
  record, against a single 1991-2020 average reference line, with a
  linear trend line. Meant for the opposite case: the long run, not a
  handful of recent years.

## Files

- `fetch_jja_history.py` -- pulls daily high temperature, the NCEI
  1991-2020 mean daily normal, and the departure, for every JJA day from
  `--start-year` through `--end-year`, from ACIS, in one `StnData` call
  spanning the whole range (the non-summer months that come back too are
  just filtered out client-side). Writes `jja_history.json`: per year, the
  June/July/August/season average departure and the raw season mean high
  (`maxt_mean`); at the top level, the constant 1991-2020 JJA mean high
  itself (`normal_mean_high`, the mean of the 92 unique JJA calendar days'
  ACIS `normal` values -- fixed regardless of which year(s) you query, so
  it comes out the same whether `--start-year`/`--end-year` cover one
  year or thirty). No API key needed.
- `build_history_grid.py` -- renders `jja_history.json` into
  `output/tri_cities_jja_history_<start>-<end>.png`. Defaults to reading
  `jja_history.json`.
- `build_trend_chart.py` -- renders `jja_history.json` into
  `output/tri_cities_jja_trend_<start>-<end>.png`. Defaults to reading
  `jja_history_full.json` (a separate file, since the trend chart wants
  the full period of record while the grid wants only a handful of recent
  years -- see Usage).
- `requirements.txt` / `setup.sh` -- Python dependencies.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# History grid: KPSC / Pasco, WA, 2019 through the most recently completed JJA
python3 fetch_jja_history.py
python3 build_history_grid.py

# Trend chart: full usable period of record (see Notes) -- a separate
# --output so it doesn't overwrite the grid's jja_history.json
python3 fetch_jja_history.py --start-year 1998 --output jja_history_full.json
python3 build_trend_chart.py

# A specific range or station (either chart)
python3 fetch_jja_history.py --start-year 2015 --end-year 2025
python3 fetch_jja_history.py --sid "KPDX 5" --station KPDX --label "Portland, OR"
```

## Notes

- **Source**: ACIS (xmACIS), station `KPSC 5` by default -- same source,
  same `normal`/`departure` element flags, as
  [`tri-cities-jja-calendar`](../tri-cities-jja-calendar/)'s
  `fetch_jja_highs.py`.
- **KPSC's "full usable period of record" is 1998-present, not its
  nominal 1945-present.** The station's raw daily data has isolated
  coverage in 1945 and then a large gap until 1998 (confirmed by pulling
  the full period of record: only 10,854 of 29,759 days since 1945-04-01
  have data, and every JJA from 1998 on has at least 89 of 92 days vs.
  essentially nothing 1946-1997) -- the same gap
  `tri-cities-temp-chart/fetch_climatology.py` documents for the
  1991-2020 percentile window. `build_trend_chart.py`'s
  `MIN_SEASON_DAYS` (80) drops any year that falls short of a usable JJA
  regardless of range requested.
- **The grid's color scale is +-10°F, not the calendar's +-15°F.** A
  single day's high can swing far from normal; a month's or a season's
  *average* can't -- at +-15°F nearly every cell would land pale and
  washed out. +-10°F was picked because it comfortably covers KPSC's
  record (2021's +9.4°F June, driven by the late-June Pacific Northwest
  heat dome, is the only month close to it) without either clipping
  routinely or making ordinary months all look alike. Re-check
  `DEPARTURE_VMAX` in `build_history_grid.py` if a much longer or hotter
  range pushes past it.
- **A year's season average is the mean of that year's individual daily
  departures (or, for the trend chart, raw highs) across all of
  June/July/August**, not the mean of its own three monthly averages --
  equivalent unless a year has very different amounts of missing data
  across its three months, which none currently do (`n_days` in
  `jja_history.json` records the actual count).
- **The trend chart's reference line and each year's raw mean can differ
  from that year's season *departure* by a few hundredths of a degree** --
  ACIS's `normal` and `departure` elements are each independently rounded
  to the nearest whole degree before being returned, so `maxt - normal`
  doesn't always exactly equal the `departure` column for a single day.
  Immaterial at any scale this chart displays; `normal_mean_high` is
  computed directly from the `normal` column rather than backed out of
  `departure`; see `fetch_jja_history.py`'s `normal_by_day`.
- **Trend line**: an ordinary least-squares fit (`numpy.polyfit`, degree
  1) across all usable years' raw JJA mean highs, labeled in °F/decade.
- Styling (fonts, colors, logo placement, background-aware cell text
  color in the grid) mirrors `tri-cities-jja-calendar/build_calendar.py`
  and `tri-cities-temp-chart/build_chart.py` -- edit `build_history_grid.py`
  / `build_trend_chart.py` directly to adjust.
