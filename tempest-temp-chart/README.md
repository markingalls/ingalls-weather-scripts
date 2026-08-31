# Tempest Temperature Chart

Generates a styled same-day temperature chart from a personal WeatherFlow
Tempest station for Ingalls Weather's Instagram: air temperature and dew
point lines across the full 24-hour local calendar day, in 24-hour time --
since this is a same-day chart, the lines legitimately stop partway through
the day rather than reaching the right edge, marked with a dotted vertical
line at the most recent observation. Two current-conditions stat boxes
(Current Temperature / Current Dew Point) sit above the plot. Same canvas
footprint and fonts as the [850/700 mb temp chart](../850-700-temp-chart/)
and [Tri-Cities temp chart](../tri-cities-temp-chart/), just one station's
raw observations instead of a forecast/climatology blend.

Defaults to today (station-local calendar day) and to whichever station the
API key's account has a Tempest ("ST") device on.

`build_lookback_charts.py` renders the same style of chart for each of the
past 5 station-local days (not including today) -- a "look back" companion
to the always-current today chart, the same idea as the lightning maps
having both a realtime and a rolling-window view. Each day is complete, so
there's no "current" reading to highlight: no stat boxes, no "Updated"
clause, and the plot reclaims that space (see `--no-current-conditions`
below).

## Files

- `fetch_tempest.py` -- pulls a day's 1-minute-resolution observations for
  a Tempest station from the WeatherFlow Tempest API and writes
  `tempest_obs.json`. Requires `TEMPEST_API_KEY` in the environment (get
  one at https://tempestwx.com/settings/tokens). Run this any time you
  want the chart to reflect the latest observation.
- `fetch_forecast.py` -- pulls today's NWS forecast high temperature for a
  point and writes `forecast.json`. Optional -- `build_chart.py` runs fine
  without it -- but if present (and for the same date), it extends the
  y-axis to cover the forecast high, not just what's been observed so far.
  No API key needed.
- `build_chart.py` -- renders `tempest_obs.json` (+ `forecast.json`, if
  present) into `tempest_temp_chart.png`.
- `build_lookback_charts.py` -- fetches and renders the past 5 days (not
  including today), one file per day, into `lookback/`. Shells out to
  `fetch_tempest.py` and `build_chart.py` for each day rather than
  reimplementing their logic, so every day's chart behaves exactly like
  running them by hand would. Requires `TEMPEST_API_KEY` same as
  `fetch_tempest.py`.
- `requirements.txt` / `setup.sh` -- Python dependencies (no system
  packages needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export TEMPEST_API_KEY=...         # your Tempest API key

# Default: today, the account's Tempest station
python3 fetch_tempest.py
python3 fetch_forecast.py          # optional -- extends the y-axis to today's forecast high
python3 build_chart.py

# A specific day or station (if the account has more than one)
python3 fetch_tempest.py --date 2026-08-30 --station-id 12345
python3 build_chart.py

# Circle and label the day's lowest and/or highest observation
python3 build_chart.py --mark-low
python3 build_chart.py --mark-high
python3 build_chart.py --mark-low --mark-high

# Past 5 days, one chart per day, into lookback/ -- no current-conditions
# boxes (see --no-current-conditions), low/high always marked
python3 build_lookback_charts.py
python3 build_lookback_charts.py --days 10          # a longer look back
```

## Notes

- **Source**: WeatherFlow's Tempest REST API
  (`swd.weatherflow.com/swd/rest`). `fetch_tempest.py` first calls
  `/stations` to find the account's Tempest ("ST") device (pass
  `--station-id` to pin one if the account has more than one station), then
  `/observations/device/{device_id}` for the 1-minute `obs_st` samples.
  Air temperature (`obs_st` field index 7) comes back in Celsius and is
  converted to Fahrenheit.
- **Day boundary is station-local, not UTC**: the API's own `day_offset`
  parameter buckets by UTC calendar day, which silently shifts "today" for
  any station west of UTC (e.g. a Pacific-time station's `day_offset=0`
  actually starts at 5pm/6pm the previous local day during
  PDT/PST). `fetch_tempest.py` instead computes the station's own local
  midnight-to-midnight window (via its `timezone` field from `/stations`)
  and passes that as explicit `time_start`/`time_end` unix timestamps, so
  "today" always means the station's own calendar day.
- **X-axis spans the full 24-hour local day** (midnight to midnight) even
  when run mid-day, per the same-day-chart use case this project is built
  for -- the line simply stops at the most recent observation rather than
  the axis being cropped to only the elapsed hours. Ticks are every 3 hours
  in 24-hour time (`00:00`/`03:00`/.../`21:00`); a dotted vertical marker at
  the last observation makes the stopping point read as current, not as
  missing data. Skipped under `--no-current-conditions`: a complete day's
  line already runs the full 24 hours (its last observation lands a minute
  before midnight, not literally at it), so the same marker there would
  misleadingly read as "cut short" rather than "complete."
- **Data outages show as a break in the line, not a straight line across
  them.** The Tempest hub reports roughly once a minute; `build_chart.py`'s
  `insert_gaps()` walks the observations and, wherever two consecutive
  ones are more than `MAX_GAP` (6 minutes) apart, inserts a NaN-valued
  point at the gap's midpoint before plotting -- matplotlib breaks a line
  at a NaN y-value rather than connecting across it, so a real outage
  (station offline, hub lost power/WiFi, etc.) reads as a visible gap
  instead of implying data that doesn't exist. Only the plotted line uses
  the gap-inserted series -- the day's low/high, the "now" marker, and the
  y-axis bounds all still come from the real observations (`times`/`temps`
  as fetched, unmodified), so a gap never affects what those report.
- **Y-axis** is fixed to 3°F below the day's low and 3°F above its high.
  The low is `min` of whatever's been observed so far, across *both*
  temperature and dew point (dew point is always <= air temperature, so
  it's often the actual lower bound, not temperature's own low) -- before
  the actual overnight low has happened yet, the axis just reflects the
  partial day and widens as later observations come in. The high is
  `max(observed high, forecast high)` (temperature only -- dew point never
  exceeds it, so it never affects the top bound): `fetch_forecast.py`'s
  NWS forecast high (if `forecast.json` is present and for the same date)
  gives the axis headroom for the afternoon high before it's actually been
  observed; once it has, the observed max takes over as the larger of the
  two -- `max()` is itself the override: a forecast is only ever a floor
  on the axis, never a ceiling that could clip an observation running
  hotter than it. With no `forecast.json`, the high is just the observed
  max so far, same as the low.
  **For future reference**: there's currently no forecast *low* (only a
  forecast high, from NWS's daytime period), but if one is ever added, it
  should follow the same rule symmetrically -- `day_low = min(day_low,
  forecast_low)`, so an actual cold observation can still override the
  forecast rather than the other way around. An observation should always
  be able to override a forecast in whichever direction it turns out to be
  more extreme, above or below.
- **`--mark-low` / `--mark-high`** (both off by default, independently
  toggleable) circle the day's lowest/highest observation and label them
  `Low: XX.X°F at HH:MM` / `High: XX.X°F at HH:MM`. Each prefers
  below-and-right of its point, but tries above-right, below-left, and
  above-left in turn, keeping the first whose actual rendered extent stays
  inside the plot and clear of the logo *and* the other marker (if both
  are on -- the high is placed after the low, so it also avoids the low's
  final position; they're normally hours apart in a real diurnal curve,
  but this holds even when they land close together) -- rather than
  guessing a fixed offset, since a forecast-driven axis can leave very
  little room below the low (the bottom padding is a flat 3°F regardless
  of how tall the axis gets above it), and either point could in
  principle land anywhere in the day, including the logo's own corner.
- **Dew point line**: plotted alongside temperature (forest green,
  `#164f29` -- the same green `TEMP_COLOR` used before it was changed to
  the logo's blue), same gap-breaking treatment as temperature (see
  above), but deliberately has no `--mark-low`/
  `--mark-high` equivalent -- those stay temperature-only. Missing-RH
  observations (rare) come back from `fetch_tempest.py` with no
  `dew_point_f` key at all; `build_chart.py` substitutes `NaN` for those
  before plotting, so a lone missing reading breaks the line the same way
  a real outage does, rather than crashing or silently interpolating
  across it.
- A small legend (top-left, unobtrusive) distinguishes the two lines --
  added once there were two series to tell apart; the original
  single-line version didn't need one (the y-axis label alone was
  enough). It has a plain white background (no border) so it stays
  readable over the gridlines and, on a day the line happens to pass
  through that corner, over the data itself -- drawn above the plotted
  lines (`zorder` one above `Z_TEMP`) so it never gets covered.
- Chart styling (fonts, dimensions, logo placement) mirrors
  `850-700-temp-chart/build_chart.py` and `tri-cities-temp-chart/build_chart.py`
  -- edit `build_chart.py` directly to adjust. The temperature line is the
  same blue as the cloud in the Ingalls Weather logo (`#1d7db0`, sampled
  directly from `assets/ingalls_weather_logo.png`'s dominant cloud-fill
  pixel color). `--mark-low` uses the same deep blue (`#0b3d91`)
  `hrrr-smoke-chart` uses for its second location line, and `--mark-high`
  the same dark red (`#a3242b`) `tri-cities-temp-chart` uses for record
  highs.
- **Logo placement defaults bottom-right**, matching those other temp
  charts, but moves to the top-right corner instead whenever either
  line's actual drawn path (every segment, via `Path.intersects_bbox` --
  not just the raw data points, since a segment between two widely spaced
  samples can cut through the corner without either endpoint landing
  inside it) would pass behind it there -- dew point is checked along
  with temperature since it's often the lower of the two curves, and so
  the more likely one to actually reach that corner. A same-day chart's
  line only ever reaches that corner when "now" is late in the day and
  the reading happens to be low then too, but it does happen (and more so
  once a forecast high has stretched the axis down into that corner's
  territory) -- checked once per render against the final axis bounds,
  before `--mark-low`/`--mark-high`'s own placement logic runs (which
  then sees the logo whichever corner it ended up in).
- **Forecast source**: `fetch_forecast.py` resolves a lat/lon to its NWS
  forecast office/grid via `/points`, then reads today's first daytime
  period's `temperature` from the standard `/forecast` endpoint (already
  in °F, no conversion). Defaults to Highland Hills' own coordinates --
  pass `--lat`/`--lon` for a different point. If today's daytime period
  has already scrolled out of the forecast (it's evening and the next
  daytime period is tomorrow's), `forecast_high_f` comes back `null` and
  `build_chart.py` just falls back to the observed max, which by then is
  the real high anyway.
- **Display label**: `fetch_tempest.py` writes both the Tempest API's raw
  station name (`station_name`) and a display `label` used in the chart
  title. `STATION_LABEL_OVERRIDES` in `fetch_tempest.py` maps known raw
  names to a more recognizable label (e.g. `"Highland Hills"` →
  `"Highland Hills (Hermiston)"`, the property name plus its town); pass
  `--label` to override for any station, known or not.
- **Subtitle** is the date plus `• Updated: HH:MM PT` (the last
  observation's local time, 24-hour); timezone and station-vs-property
  distinctions otherwise live in the title's label and this file, not on
  the chart itself.
- **`--no-current-conditions`** renders a plain historical-day chart: no
  stat boxes, no "Updated" clause in the subtitle (just the date -- that
  phrasing implies a still-live reading, which doesn't apply to a
  complete, past day), title drops "Today's" (`"Temperature — {label}"`
  instead of `"Today's Temperature — {label}"`), and no dotted
  last-observation marker (see above). The plot reclaims the vertical
  space the stat boxes would have used, back to the same 0.65-of-figure
  height the other temp charts use, with the subtitle/title position
  derived from the axes' own top edge the same way theirs is -- rather
  than the fixed position the current-conditions layout uses, which
  assumes a shorter, stat-box-reserving axes. `build_lookback_charts.py`
  always passes this (plus `--mark-low --mark-high`, since a full day's
  low/high are already known) -- pass it to `build_chart.py` directly to
  render a single past day the same way, e.g. after
  `fetch_tempest.py --date 2026-08-30`.
- **Current-conditions stat boxes** sit in the band freed up by shrinking
  the plot's own height (0.65 -> 0.56 of the figure, vs. the other temp
  charts). Each is a two-line, regular-weight, right-aligned label
  ("Current" / "Temperature", tight 0.85 linespacing) immediately left of
  a bold value chip; the chip's small colored background (not the whole
  row) comes from interpolating `TEMP_COLOR_TABLE`/`DEW_POINT_COLOR_TABLE`
  (K -> RGB control points, linearly interpolated by `interp_color()`)
  against the reading converted to Kelvin, and the bold text itself is
  black or white via `text_color_for_bg()`'s ITU-R BT.601 luminance
  check. The number's fontsize is matched (measure, don't guess) to the
  label block's height at linespacing=1.2 specifically -- kept at that
  original size even though the label itself now renders tighter, so
  tightening the label's spacing didn't also shrink the number. Each
  (label + chip) pair is centered as a unit within its own column,
  nudged left slightly further (`stat_visual_shift`) since a geometrically
  centered pair still reads as sitting a bit right of center -- the bold
  chip carries more visual weight than the plain label next to it.
  **Known matplotlib gotcha**: `Text.get_window_extent()` on a
  `bbox=`-styled Text ignores the padded patch entirely and reports only
  the bare text's box (confirmed empirically: its measured left edge
  lands exactly on the `ha="left"` anchor) -- the pad has to be added
  back by hand (`chip_pad * fontsize_pt * dpi/72`, since a boxstyle's
  `pad` is in font-size units) wherever the chip's actual visual footprint
  matters, or spacing/centering math will be off by the pad amount.
