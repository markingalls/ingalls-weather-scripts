# Tri-Cities JJA Daily High Calendar

Generates a wall-calendar-style graphic of Tri-Cities daily high
temperature across meteorological summer (June-July-August): a real
month grid (Sunday-Saturday columns) for each of the three months, one
cell per day showing that day's observed high and its departure from the
1991-2020 average, both from ACIS (the same backend behind
xmacis.rcc-acis.org). Each cell is shaded on a diverging purple-to-maroon
scale by that departure -- purple/blue for a below-normal day, white for
a day right at normal, orange through red to maroon for an above-normal
day -- so a summer's hot/cool stretches read at a glance instead of
requiring you to read every number.

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA) and the most
recently *completed* JJA, but any ACIS station and any year works.

## Files

- `fetch_jja_highs.py` -- pulls daily high temperature (element `maxt`),
  the NCEI 1991-2020 mean daily normal, and the departure from that
  normal, for June 1 - August 31 of a given year, from ACIS. Writes
  `jja_highs.json`. No API key needed. ACIS's `normal` element flag
  exposes NCEI's own mean-based daily normal directly, and a `departure`
  flag returns observed-minus-normal already computed server-side, both
  requested in the same call as the raw `maxt` column -- so, unlike
  [`tri-cities-temp-chart`](../tri-cities-temp-chart/)'s percentile
  climatology (which ACIS has no direct element for), there's nothing to
  compute client-side here.
- `build_calendar.py` -- renders `jja_highs.json` into
  `output/tri_cities_jja_calendar_<year>.png`.
- `requirements.txt` / `setup.sh` -- Python dependencies.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: KPSC / Pasco, WA, most recently completed JJA
python3 fetch_jja_highs.py
python3 build_calendar.py

# A specific year or station
python3 fetch_jja_highs.py --year 2025
python3 fetch_jja_highs.py --sid "KPDX 5" --station KPDX --label "Portland, OR"
python3 build_calendar.py
```

## Notes

- **Source**: ACIS (xmACIS), station `KPSC 5` by default (see
  `tri-cities-temp-chart/README.md` for KPSC's alternate station-id
  forms). Both the observed high and the normal/departure come from the
  same `StnData` call, so they're always internally consistent.
- **"Departure from average" is NCEI's mean-based 1991-2020 daily
  normal**, not the P50/median climatology
  [`tri-cities-temp-chart`](../tri-cities-temp-chart/) plots -- that
  project computes its own percentiles client-side specifically because
  ACIS has no percentile-of-distribution element; this one wants exactly
  the mean-based normal ACIS's `normal` flag already provides, which is
  the conventional definition of "departure from normal" (e.g. NWS CF6
  climate reports).
- **Default year**: the current year once September has started (that
  JJA is over), otherwise last year (this year's JJA isn't finished yet).
  Override with `--year`.
- **Color scale**: a diverging colormap from purple (-15°F) through blue
  to white (0°F, i.e. no shading -- a day right at normal gets no color
  at all) through orange, red, to maroon (+15°F), built in
  `build_calendar.py` as `DEPARTURE_CMAP`/`DEPARTURE_STOPS` and clipped
  beyond ±15°F rather than extrapolated further. Edit those constants to
  adjust the anchor colors or the ±15°F range.
- **Layout**: June and July side by side, August centered below -- each
  month its own small axes drawn as a real Sunday-first calendar grid
  (`calendar.Calendar(firstweekday=6)`), not a GitHub-style contribution
  heatmap. Day number top-left of each cell, the high (bold) and signed
  departure (small) centered below it. Text color flips between dark ink
  and white per cell (see `cell_text_style`) based on that cell's own
  departure color, with a thin same-side-contrast halo -- a single
  fixed text/halo pairing doesn't hold up across the whole purple-to-
  maroon range. All three months share one `fixed_rows` grid height (the
  most weeks any of the three needs) so cell size and the month titles
  above each grid line up consistently even when one month has fewer
  calendar weeks than the others. A missing day (ACIS `M`) shades gray
  with just an "M" -- no departure text.
- **Vertical layout** is a top-to-bottom flow (`flow_text` in
  `build_calendar.py`): each title/subtitle/grid is placed from a running
  cursor advanced by that element's own height plus a fixed gap, rather
  than at hand-tuned fixed figure coordinates. That's what let June/July
  vs. August move from one row to two without re-deriving every offset by
  eye -- change `ROW_MONTHS`, `FIG_W`/`FIG_H`, or the per-block gaps and
  the rest of the layout re-flows on its own.
- Chart styling (fonts, colors, logo placement) mirrors
  `tri-cities-temp-chart/build_chart.py` -- edit `build_calendar.py`
  directly to adjust.
