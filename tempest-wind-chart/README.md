# Tempest Wind Chart

Generates a styled same-day wind chart from a personal WeatherFlow Tempest
station for Ingalls Weather's Instagram: a wind speed line plus individual
gust dots across the full 24-hour local calendar day, in 24-hour time --
since this is a same-day chart, the line legitimately stops partway through
the day rather than reaching the right edge, marked with a dotted vertical
line at the most recent observation. The day's single highest gust is
circled and labeled. Two current-conditions stat boxes (Current Wind /
Current Gusts) sit above the plot. Same canvas footprint, fonts, and
overall layout as [`tempest-temp-chart/`](../tempest-temp-chart/) -- a
sibling chart for the same station, wind instead of temperature.

Defaults to today (station-local calendar day) and to whichever station the
API key's account has a Tempest ("ST") device on.

`build_lookback_charts.py` renders the same style of chart for each of the
past 5 station-local days (not including today) -- a "look back" companion
to the always-current today chart, same idea as `tempest-temp-chart`'s own
look-back tool.

## Files

- `fetch_tempest.py` -- pulls a day's 1-minute-resolution wind
  observations (speed, gust, direction) for a Tempest station from the
  WeatherFlow Tempest API and writes `tempest_wind_obs.json`. Requires
  `TEMPEST_API_KEY` in the environment (get one at
  https://tempestwx.com/settings/tokens). Run this any time you want the
  chart to reflect the latest observation. Same station-discovery and
  station-local-day-boundary handling as
  `tempest-temp-chart/fetch_tempest.py` -- see that project's README for
  why the day boundary is computed the way it is.
- `build_chart.py` -- renders `tempest_wind_obs.json` into
  `tempest_wind_chart.png`. See `--no-current-conditions` in Notes below
  for rendering a past, complete (archive) day instead of today's.
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

# That same past day as an archive chart -- no current-conditions boxes
python3 build_chart.py --no-current-conditions

# Past 5 days, one chart per day, into lookback/ -- no current-conditions
# boxes, peak gust always marked
python3 build_lookback_charts.py
python3 build_lookback_charts.py --days 10          # a longer look back
```

## Notes

- **Source**: WeatherFlow's Tempest REST API
  (`swd.weatherflow.com/swd/rest`), same `/stations` + `/observations/device`
  flow as `tempest-temp-chart/fetch_tempest.py`. Wind speed, gust, and
  direction come from `obs_st` field indices 2, 3, and 4 respectively,
  already in m/s (speed/gust) and degrees (direction); speed and gust are
  converted to mph before being written out, direction is left in degrees
  (`build_chart.py`'s `degrees_to_cardinal()` converts to a 16-point
  compass label only at render time).
- **Day boundary is station-local, not UTC** -- see
  `tempest-temp-chart/README.md`'s own note on this; the logic is
  identical here.
- **X-axis spans the full 24-hour local day**, same reasoning and tick
  layout as `tempest-temp-chart`.
- **Wind speed is a line, gust is dots, not a second line** -- a gust is
  its own brief spike, not a continuous quantity the way sustained wind
  speed is, so plotting it as a scatter reads as "these moments gusted"
  rather than implying a connected trend between them. Only the wind
  speed line uses `insert_gaps()`'s NaN-insertion approach to show data
  outages as a break rather than a straight line across them (see
  `tempest-temp-chart`'s own README for how and why); gust dots need no
  equivalent -- a missing reading there is simply not plotted, no
  different from a real outage.
- **Peak gust** is circled and labeled (`Peak Gust: XX.X mph at HH:MM`,
  dark red, same hue `tempest-temp-chart`/`tri-cities-temp-chart` use for
  their own daily-high callouts) -- gust rather than wind speed, since a
  gust burst is the more newsworthy extreme for a wind chart (a day's low
  wind speed is usually just calm/near-zero, not worth calling out the
  way temperature's daily low is). Always on, unlike
  `tempest-temp-chart`'s opt-in `--mark-low`/`--mark-high` -- there's
  only ever one marker here, so there's no on/off combination to expose
  as a flag. Label placement tries above-right first (reads better
  sitting over the peak than crowding the generally busier area below,
  where other gust dots tend to cluster), then above-left, below-right,
  below-left, keeping the first whose actual rendered extent stays
  inside the plot and clear of the logo -- same fallback approach as
  `tempest-temp-chart`'s own extreme-marking, just for a single always-on
  marker instead of up to two optional ones. The label sits on a solid
  white backing patch rather than only a white path-effects stroke
  around each glyph -- a stroke-only halo leaves the gaps between/inside
  letters transparent, so a gridline crossing the label (this label can
  land on one; a data value's own y-position has no reason to avoid a
  round-number gridline) showed through as a visible strikethrough before
  this fix.
- **Y-axis** floors at a flat 0 mph rather than padding below the day's
  low the way the temp chart does -- wind speed can't go negative, so
  there's no meaningful "3 mph below calm" to pad for. The ceiling
  defaults to 25 mph -- a calm/typical day (most days) reads better on a
  consistent, familiar axis rather than one that stretches to whatever
  that particular calm day's tiny max happened to be, which would make
  ordinary gusts look artificially dramatic. It widens to cover the day's
  highest reading across *both* series (gust is almost always >= wind
  speed, but both are checked rather than assuming that holds for every
  sample), padded a flat +3 mph, whenever that actually exceeds 25 -- so
  a genuinely windy day's line/dots never crowd or clip past the edge.
- Chart styling (fonts, dimensions, logo placement, current-conditions
  stat box mechanics) mirrors `tempest-temp-chart/build_chart.py` --
  edit `build_chart.py` directly to adjust. Wind speed is the same blue
  (`#1d7db0`) `tempest-temp-chart` uses for its own temperature line,
  gust is the same forest green (`#164f29`) it uses for dew point --
  same primary/secondary color pairing as that chart, rather than this
  one picking its own arbitrary hues, so the two Tempest station charts
  read as one visual family.
- **Logo placement defaults bottom-right**, matching `tempest-temp-chart`,
  moving to the top-right corner if either series would pass behind it
  there: the wind speed line via the same actual-drawn-path check
  `tempest-temp-chart` uses (`Path.intersects_bbox`, not just the raw
  data points), and the gust dots via a simpler point-in-rect test per
  dot, since a scattered point has no path of its own for that check to
  apply to.
- **Current-conditions stat boxes** reuse `tempest-temp-chart`'s stat-box
  design wholesale (two-line right-aligned label, bold color-chip value,
  centered per column, `stat_visual_shift` nudge, the `get_window_extent()`
  bbox-padding gotcha) -- see that project's README for the full writeup
  of how and why it's built the way it is. The one difference: both boxes
  here look themselves up against the *same* `WIND_COLOR_TABLE` (m/s ->
  RGB control points) rather than each having its own table, since only
  one table was supplied for wind; `mph_to_ms()` converts the display
  value into the table's own units before the lookup, in place of the
  temp chart's `fahrenheit_to_kelvin()`. Current Wind additionally needs
  both a speed *and* a direction reading to show a real value (a lone
  direction or a lone speed reads as `N/A`) -- Current Gusts is speed-only,
  since gust has no direction of its own in the Tempest API.
  **Current Gusts is the peak gust over the trailing `RECENT_GUST_WINDOW`
  (5 minutes), not the single most recent 1-minute sample** -- a lone
  sample is noisy from one moment to the next, while a short trailing
  peak reads as a more meaningful "what's it doing right now" without
  smoothing away real gustiness the way a longer average would. Current
  Wind is unaffected -- still the single most recent wind speed +
  direction reading.
- **`--no-current-conditions`** renders a plain historical-day (archive)
  chart: no stat boxes, no "Updated" clause in the subtitle (just the
  date), title drops "Today's", and no dotted last-observation marker --
  same reasoning, and the same flag name, as `tempest-temp-chart`'s own
  archive-day mode; see that project's README for the full writeup. The
  plot reclaims the stat boxes' vertical space, back to the full
  0.65-of-figure height. `build_lookback_charts.py` always passes this --
  pass it to `build_chart.py` directly to render a single past day the
  same way, e.g. after `fetch_tempest.py --date 2026-08-30`.
