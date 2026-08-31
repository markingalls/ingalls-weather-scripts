# Tempest Sea Level Pressure Chart

Generates a styled same-day sea-level-pressure chart from a personal
WeatherFlow Tempest station for Ingalls Weather's Instagram: a single
pressure line across the full 24-hour local calendar day, in 24-hour time
-- since this is a same-day chart, the line legitimately stops partway
through the day rather than reaching the right edge, marked with a dotted
vertical line at the most recent observation. A single current-conditions
stat box (Current Pressure) sits above the plot. Same canvas footprint,
fonts, and overall layout as [`tempest-temp-chart/`](../tempest-temp-chart/)
and [`tempest-wind-chart/`](../tempest-wind-chart/) -- a third sibling
chart for the same station.

Defaults to today (station-local calendar day) and to whichever station the
API key's account has a Tempest ("ST") device on.

`build_lookback_charts.py` renders the same style of chart for each of the
past 5 station-local days (not including today) -- a "look back" companion
to the always-current today chart, same idea as `tempest-temp-chart`'s and
`tempest-wind-chart`'s own look-back tools.

## Files

- `fetch_tempest.py` -- pulls a day's 1-minute-resolution station pressure
  observations for a Tempest station from the WeatherFlow Tempest API,
  reduces each reading to sea level (see Notes below), and writes
  `tempest_pressure_obs.json`. Requires `TEMPEST_API_KEY` in the
  environment (get one at https://tempestwx.com/settings/tokens). Run
  this any time you want the chart to reflect the latest observation.
  Same station-discovery and station-local-day-boundary handling as
  `tempest-temp-chart/fetch_tempest.py` -- see that project's README for
  why the day boundary is computed the way it is.
- `build_chart.py` -- renders `tempest_pressure_obs.json` into
  `tempest_pressure_chart.png`. See `--no-current-conditions` in Notes
  below for rendering a past, complete (archive) day instead of today's.
- `build_lookback_charts.py` -- fetches and renders the past 5 days (not
  including today), one file per day, into `lookback/`. Shells out to
  `fetch_tempest.py` and `build_chart.py` for each day rather than
  reimplementing their logic, so every day's chart behaves exactly like
  running them by hand would.
- `requirements.txt` / `setup.sh` -- Python dependencies (no system
  packages needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export TEMPEST_API_KEY=...         # your Tempest API key

# Default: today, the account's Tempest station
python3 fetch_tempest.py
python3 build_chart.py

# A specific day or station (if the account has more than one)
python3 fetch_tempest.py --date 2026-08-30 --station-id 12345
python3 build_chart.py

# That same past day as an archive chart -- no current-conditions box
python3 build_chart.py --no-current-conditions

# Past 5 days, one chart per day, into lookback/ -- no current-conditions
# box, high/low always marked
python3 build_lookback_charts.py
python3 build_lookback_charts.py --days 10          # a longer look back
```

## Notes

- **Source**: WeatherFlow's Tempest REST API
  (`swd.weatherflow.com/swd/rest`), same `/stations` + `/observations/device`
  flow as `tempest-temp-chart/fetch_tempest.py`. Station pressure comes
  from `obs_st` field index 6, already in millibars.
- **Sea-level reduction**: Tempest's `obs_st` only reports *station*
  pressure (absolute pressure at the sensor's own elevation), not a
  sea-level-adjusted reading -- `fetch_tempest.py` reduces it itself,
  using the standard barometric formula (the same station-elevation-only
  reduction NWS-style altimeter/QFF-style readings use, ignoring
  humidity/virtual-temperature effects): `P0 = P * (1 - L*h / (T + L*h +
  273.15)) ^ -5.257`, where `h` is the station's own elevation in meters
  (`/stations`' `station_meta.elevation` -- confirmed present and in
  meters against this account's real station: 153.3 m), `L` = 0.0065 K/m
  (the ICAO standard atmosphere's tropospheric lapse rate), `T` is the
  *concurrent* air temperature in °C from that same observation (`obs_st`
  index 7), and `5.257 = g*M/(R*L)` for that same standard atmosphere.
  Verified by hand against a real reading: 992.5 mb station pressure at
  153.3 m with 25.6°C air temp reduces to ~1010.0 mb -- a plausible
  sea-level value for typical late-summer conditions, not the
  implausibly-low ~992 mb the unreduced station pressure alone would
  suggest. Displayed in millibars, not inches of mercury -- unlike the
  rest of this station's chart family's US-customary-units convention
  (°F, mph), mb is the more familiar unit for pressure specifically.
- **Line smoothing**: a centered simple moving average (`smooth()`,
  `SMOOTHING_WINDOW = 15` samples, ~15 minutes at the hub's ~1/minute
  cadence) is applied to the plotted line before gap-breaking --
  pressure sensor noise between individual 1-minute samples is small in
  absolute terms but reads as a distracting staircase/jitter at this
  chart's scale, since a whole day's real diurnal swing is often not
  much bigger than the noise itself. Edges use whatever partial window
  is actually available rather than padding with NaN or truncating, so
  the line's start and end stay exactly as long as the data itself.
  Smoothing happens *before* `insert_gaps()`, not after -- otherwise the
  inserted NaN points would fall inside a smoothing window and poison
  every average that touches them. The current-conditions stat box still
  reads the single latest *raw* sample, same as the temp/wind charts'
  own "current" readouts, and the y-axis bounds pad the raw (unsmoothed)
  range too, so smoothing only affects the drawn line, not what's
  reported as "current" or how tall the axis is.
- **Day boundary is station-local, not UTC** -- see
  `tempest-temp-chart/README.md`'s own note on this; the logic is
  identical here.
- **X-axis spans the full 24-hour local day**, same reasoning and tick
  layout as `tempest-temp-chart`.
- **Data outages show as a break in the line, not a straight line across
  them** -- same `insert_gaps()` NaN-insertion approach as
  `tempest-temp-chart`/`tempest-wind-chart`.
- **Y-axis** pads a flat +-1.5 mb around the day's observed range --
  much smaller than the temp chart's +-3°F, since a whole day's sea-level
  pressure swing is usually tiny (a calm day might only span ~3-7 mb)
  compared to temperature's; a pad sized like temperature's would
  flatten the day's actual diurnal wobble into an imperceptible sliver.
  Tick labels are whole millibars (`%.0f`) -- sub-mb precision isn't
  meaningful at gridline scale, even though the high/low callouts and
  stat box below still show a decimal.
- **High/low markers** circle and label the day's highest and lowest
  sea-level pressure (`HIGH_COLOR`/`LOW_COLOR`, the same red/blue as
  `tempest-temp-chart`'s own `--mark-high`/`--mark-low`, and the
  standard synoptic-map H/L convention) -- always on, unlike that flag,
  since there's only the one series here and a day's high and low are
  always worth calling out, on both a same-day and an archive chart.
  Marked against the *raw* (unsmoothed) readings, same values the
  y-axis padding uses, so the callout is the actual observed extreme --
  which can leave the circle a hair off the (smoothed) drawn line
  itself, a tradeoff made deliberately in favor of reporting the true
  reading. Label placement falls back through above-left/above-right/
  below-left/below-right, keeping the first that stays inside the plot
  and clear of the logo and the other marker's label -- same mechanism,
  and the same solid-white-backing-patch fix (not a path-effects
  stroke, which leaves gaps between letters transparent), as
  `tempest-wind-chart`'s own always-on peak-gust marker.
- Chart styling (fonts, dimensions, logo placement, current-conditions
  stat box mechanics) mirrors `tempest-temp-chart/build_chart.py` -- edit
  `build_chart.py` directly to adjust. The line is the same forest green
  (`#164f29`) `tempest-temp-chart` uses for dew point and
  `tempest-wind-chart` uses for gust -- pressure has only the one series,
  so it just takes the family's green outright rather than needing a new
  hue of its own.
- **Logo placement defaults bottom-right**, matching the sibling charts,
  moving to the top-right corner if the pressure line's actual drawn path
  would pass behind it there (`Path.intersects_bbox`, not just the raw
  data points).
- **Current-conditions stat box** reuses the sibling charts' stat-box
  design (two-line right-aligned label, bold color-chip value, the
  `get_window_extent()` bbox-padding gotcha -- see
  `tempest-temp-chart/README.md` for the full writeup). Unlike the
  temp/wind charts' two-column layout (which centers the label+chip
  pair as a single unit, since each has two stats side by side), this
  single-stat chart centers the **value chip itself** on the figure's
  own horizontal midpoint, with the "Current Pressure" label sitting to
  its left -- the number people actually look at lands dead center,
  rather than being pushed off-center by half the label's own width.
  Its chip background comes from `PRESSURE_COLOR_TABLE`, a Pa-keyed
  `(Pa, (R, G, B))` control-point table linearly interpolated by
  `interp_color()` (same mechanism as the temp/wind charts' own K- and
  m/s-keyed tables) -- the current mb reading is converted to Pa via
  `mb_to_pa()` at the call site, keeping `interp_color()` itself
  unit-agnostic. `PRESSURE_COLOR` (the line's own forest green) is
  unrelated to the chip now -- it's still used for the line itself, just
  no longer for the stat box.
- **`--no-current-conditions`** renders a plain historical-day (archive)
  chart: no stat box, no "Updated" clause in the subtitle (just the
  date), title drops "Today's", and no dotted last-observation marker --
  same reasoning, and the same flag name, as the sibling charts' own
  archive-day mode. The plot reclaims the stat box's vertical space, back
  to the full 0.65-of-figure height.
