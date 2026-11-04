# Pacific Northwest Snowpack Chart

Generates a styled water-year snowpack chart for Ingalls Weather's
Instagram: this water year's regional **snow water equivalent (SWE)**
across the NRCS SNOTEL network in Washington, Oregon, and Idaho, plotted
against the NRCS **1991-2020 daily median**. The x-axis always spans the
full water year (**Oct 1 .. Sep 30**), so the median curve shows the whole
season's build-up, peak, and melt-out, while this year's line stops at the
most recent day reported. The latest point is labeled with its SWE and
percent of median, and the median's peak is called out.

Same canvas footprint, fonts, palette, and layout as the
[Tri-Cities temperature chart](../tri-cities-temp-chart/) and
[850 mb chart](../850-700-temp-chart/): forest-green data line, amber
dashed climatology (median) line, horizontal legend strip above the plot, dotted
vertical marker at the latest day, logo bottom-right.

## Files

- `fetch_snowpack.py` -- pulls daily SWE (element `WTEQ`) for every SNOTEL
  station in the requested states from the NRCS Air and Water Database
  (AWDB) REST API, aggregates it into one regional series plus the
  full-season median curve, and writes `snowpack.json`. No API key
  needed.
- `build_chart.py` -- renders `snowpack.json` into `pnw_snowpack_chart.png`.
- `requirements.txt` / `setup.sh` -- Python dependencies, plus the Poppins
  font (not packaged for apt).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: WA + OR + ID
python3 fetch_snowpack.py
python3 build_chart.py

# A different region -- e.g. Washington only
python3 fetch_snowpack.py --states WA --label "Washington"
python3 build_chart.py
```

The fetch takes about a minute (AWDB is slow on multi-state wildcard
queries). Re-run it any time to pick up the latest day; the water year is
chosen automatically from `--end-date` (default today): Oct 1 onward is
the next calendar year's water year.

## Notes

- **Source**: NRCS AWDB REST API
  (`wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data`), SNOTEL network,
  daily `WTEQ`, queried with a `*:<STATE>:SNTL` wildcard per state.
- **Median, not mean**: the comparison curve is AWDB's
  `centralTendencyType=MEDIAN` -- NRCS's 1991-2020 daily median, the same
  statistic NRCS's own snowpack reports lead with (a mean gets pulled up
  by a few huge years). Each station's daily median is pulled, then those
  are averaged across stations to make the regional curve. It's drawn as
  a line only, with no shading underneath.
- **Full-season median curve**: AWDB only returns central tendencies
  alongside dates that actually have data, so asking for the rest of the
  current water year returns nothing. The script instead reads the
  medians from a completed reference water year (`--reference-wy`,
  default WY2024, which includes Feb 29 so every calendar day is covered)
  -- the median for a given calendar day is the same 1991-2020 value
  whichever year it's read from.
- **Station set**: fixed to stations with a median for every calendar
  day (~214 across WA/OR/ID), so the median curve is one consistent set
  of sites all season. `snowpack.json`'s `n_stations` reports the count.
- **Regional aggregation**: the median curve is the mean of those
  stations' daily medians. Each observed day's percent of median is
  `sum(observed) / sum(median)` over only the stations that reported
  that day (the NRCS "same stations on both sides" index method), and the
  plotted SWE is that ratio times the regional median curve -- so a few
  stations dropping out on a given day doesn't make the line jump. Early
  in October, when the regional median is under 0.05", percent of
  median is meaningless and the plotted value is just the mean of
  reporting stations.
- **Truncation**: this year's line ends at the most recent day on which
  at least half the station set has reported. Today's values post station
  by station through the morning, so running early in the day typically
  ends the line at yesterday (the fetch prints any day it drops).
- **Label placement**: the latest-value label sits above the point (with a
  leader line) while it's in the bottom half of the plot, and below it
  once the line is in the top half, so it clears both the rising median
  curve early in the season and the legend strip near peak; it flips to
  the left of the point late in the water year so it stays on-canvas.
