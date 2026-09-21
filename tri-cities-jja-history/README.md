# Tri-Cities JJA History Grid

Companion graphic to [`tri-cities-jja-calendar`](../tri-cities-jja-calendar/):
instead of one summer's daily highs, a year-over-year grid of Tri-Cities
JJA (June-July-August) daily-high departure from the 1991-2020 average --
years across as columns, June/July/August average departure stacked as
rows, a gap, then the full-season average departure as a bottom row.
Same purple-blue-white-orange-red-maroon departure spectrum, fonts, and
branding as the calendar, on the same 16x9 canvas.

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA), 2020 through the
most recently *completed* JJA.

## Files

- `fetch_jja_history.py` -- pulls daily high temperature, the NCEI
  1991-2020 mean daily normal, and the departure, for every JJA day from
  `--start-year` through `--end-year`, from ACIS, in one `StnData` call
  spanning the whole range (the non-summer months that come back too are
  just filtered out client-side). Averages the daily departures into a
  June/July/August/season figure per year and writes `jja_history.json`.
  No API key needed.
- `build_history_grid.py` -- renders `jja_history.json` into
  `output/tri_cities_jja_history_<start>-<end>.png`.
- `requirements.txt` / `setup.sh` -- Python dependencies.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: KPSC / Pasco, WA, 2020 through the most recently completed JJA
python3 fetch_jja_history.py
python3 build_history_grid.py

# A specific range or station
python3 fetch_jja_history.py --start-year 2015 --end-year 2025
python3 fetch_jja_history.py --sid "KPDX 5" --station KPDX --label "Portland, OR"
python3 build_history_grid.py
```

## Notes

- **Source**: ACIS (xmACIS), station `KPSC 5` by default -- same source,
  same `normal`/`departure` element flags, as
  [`tri-cities-jja-calendar`](../tri-cities-jja-calendar/)'s
  `fetch_jja_highs.py`.
- **Color scale is +-10°F, not the calendar's +-15°F.** A single day's
  high can swing far from normal; a month's or a season's *average*
  can't -- at +-15°F nearly every cell here would land pale and
  washed out. +-10°F was picked because it comfortably covers this
  station's KPSC record (2021's +9.4°F June, driven by the late-June
  Pacific Northwest heat dome, is the only month close to it) without
  either clipping routinely or making ordinary months all look alike.
  Re-check `DEPARTURE_VMAX` in `build_history_grid.py` if a much longer
  or hotter range pushes past it.
- **A year's season average is the mean of that year's individual daily
  departures across all of June/July/August**, not the mean of its own
  three monthly averages -- equivalent unless a year has very different
  amounts of missing data across its three months, which none currently
  do (`n_days` in `jja_history.json` records the actual count).
- Styling (fonts, colors, logo placement, background-aware cell text
  color) mirrors `tri-cities-jja-calendar/build_calendar.py` -- edit
  `build_history_grid.py` directly to adjust.
