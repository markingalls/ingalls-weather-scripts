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
  `tempest_wind_chart.png`.
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
  as a flag. Label placement tries below-right first, then above-right,
  below-left, above-left, keeping the first whose actual rendered extent
  stays inside the plot and clear of the logo -- same fallback approach
  as `tempest-temp-chart`'s own extreme-marking, just for a single
  always-on marker instead of up to two optional ones.
- **Y-axis** floors at a flat 0 mph rather than padding below the day's
  low the way the temp chart does -- wind speed can't go negative, so
  there's no meaningful "3 mph below calm" to pad for. The ceiling is the
  day's highest reading across *both* series (gust is almost always >=
  wind speed, but both are checked rather than assuming that holds for
  every sample), padded a flat +3 mph so nothing crowds the axis edge.
- Chart styling (fonts, dimensions, logo placement, current-conditions
  stat box mechanics) mirrors `tempest-temp-chart/build_chart.py` --
  edit `build_chart.py` directly to adjust. Wind speed is teal
  (`#0e7c86`), gust is amber (`#d97706`) -- a cool/calm vs. warm/burst
  pairing, distinct from every color `tempest-temp-chart` itself uses so
  the two charts don't visually blend together if shown side by side.
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
- **Not (yet) included**: a `--no-current-conditions` mode / look-back
  archive (`tempest-temp-chart`'s 5-day rolling window) fits this
  project's existing design well if wanted later -- ask, and it can be
  added the same way it exists on the temp chart.
