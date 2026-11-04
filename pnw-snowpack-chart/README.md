# Pacific Northwest Snowpack Chart

Generates a styled water-year snowpack chart for Ingalls Weather's
Instagram: this water year's regional **snow water equivalent (SWE)**
across automated snow-pillow stations in Washington, Oregon, Idaho, and
British Columbia (NRCS SNOTEL in the U.S., BC River Forecast Centre
stations in BC), plotted against the **1991-2020 daily median**. The x-axis always runs
**Oct 1 to Aug 1** (August and September are cut, since the median is
effectively zero by then), so the median curve shows the season's
build-up, peak, and melt-out, while this year's line stops at the most
recent day reported. The latest point is labeled with its SWE and percent
of median, and the median's peak is called out.

Same canvas footprint, fonts, palette, and layout as the
[Tri-Cities temperature chart](../tri-cities-temp-chart/) and
[850 mb chart](../850-700-temp-chart/): forest-green data line, amber
dashed climatology (median) line, and a horizontal legend strip above the
plot. One difference: the logo sits in the plot's top-right corner rather
than bottom-right, since that's empty space on a snowpack curve.

## Files

- `fetch_snowpack.py` -- pulls daily SWE (element `WTEQ`) for every
  automated snow-pillow station in the requested states/provinces from
  the NRCS Air and Water Database
  (AWDB) REST API, aggregates it into one regional series plus the
  full-season median curve, and writes `snowpack.json`. No API key
  needed.
- `build_chart.py` -- renders `snowpack.json` into `pnw_snowpack_chart.png`.
- `requirements.txt` / `setup.sh` -- Python dependencies, plus the Poppins
  font (not packaged for apt).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: WA + OR + ID + BC
python3 fetch_snowpack.py
python3 build_chart.py

# A different region -- e.g. Washington only
python3 fetch_snowpack.py --states WA --label "Washington"
python3 build_chart.py
```

The fetch takes a little over a minute (AWDB is slow on multi-state
wildcard queries; the script runs its four calls concurrently). Re-run it any time to pick up the latest day; the water year is
chosen automatically from `--end-date` (default today): Oct 1 onward is
the next calendar year's water year.

## Notes

- **Source**: NRCS AWDB REST API
  (`wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data`), daily `WTEQ`,
  queried with a `*:<STATE>:<NETWORK>` wildcard per state/province.
  U.S. states use the SNOTEL network (`SNTL`). BC's automated snow
  weather stations, run by the BC River Forecast Centre, are carried in
  AWDB under network `MSNT` (`NETWORK_BY_STATE` in `fetch_snowpack.py`).
  BC's manual snow courses (`SNOW`) are monthly readings, not daily, so
  they're left out. All values come back in inches. BC spans the whole
  province, including the far north, not just its southern ranges.
- **Median, not mean**: the comparison curve is AWDB's
  `centralTendencyType=MEDIAN` -- NRCS's 1991-2020 daily median, the same
  statistic NRCS's own snowpack reports lead with (a mean gets pulled up
  by a few huge years). Each station's daily median is pulled, then those
  are averaged across stations to make the regional curve. Both it and
  this year's line are drawn as lines only, with no shading underneath.
- **Full-season median curve**: AWDB only returns a central tendency
  alongside a date that actually has an observed value. Asking for the
  rest of the current water year returns nothing, and neither does any
  day a station was down. The script instead reads the medians from
  several completed reference water years (`--reference-wys`, default
  WY2024, WY2023, WY2025) and merges them, first year with a given
  calendar day winning. The median for a calendar day is the same
  1991-2020 value whichever year it's read from, so merging just fills
  outage gaps. That matters mostly for BC, where only 20 of 55 stations
  had an unbroken WY2024; merging three years brings 50 up to full
  coverage. WY2024 goes first because it includes Feb 29; a Feb 29 still
  missing is filled with the mean of Feb 28 and Mar 1.
- **Station set**: fixed to stations with a median for every calendar
  day (276 as of Nov 2026: WA 68, OR 77, ID 81, BC 50), so the median
  curve is one consistent set of sites all season. Stations too new to
  have normals drop out here. `snowpack.json`'s `n_stations` and
  `stations_by_state` report the counts.
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
