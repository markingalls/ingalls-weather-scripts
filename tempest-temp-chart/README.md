# Tempest Temperature Chart

Generates a styled same-day temperature chart from a personal WeatherFlow
Tempest station for Ingalls Weather's Instagram: a single air-temperature
line across the full 24-hour local calendar day, in 24-hour time -- since
this is a same-day chart, the line legitimately stops partway through the
day rather than reaching the right edge, marked with a dotted vertical line
at the most recent observation. Same canvas footprint and fonts as the
[850/700 mb temp chart](../850-700-temp-chart/) and
[Tri-Cities temp chart](../tri-cities-temp-chart/), just one station's raw
observations instead of a forecast/climatology blend.

Defaults to today (station-local calendar day) and to whichever station the
API key's account has a Tempest ("ST") device on.

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
  present) into `tempest_temp_chart.png`. Its rendering logic is the
  importable `build_chart(data_path, forecast_path, output_path,
  mark_low=False, mark_high=False)` function -- `main()` is a thin CLI
  wrapper around it -- so `deploy/publish_tempest.py` can call it directly
  rather than shelling out.
- `deploy/publish_tempest.py` -- cron entry point. Fetches Tempest
  observations and the NWS forecast high, then renders and atomically
  publishes `hermiston_temp.png` with both extremes marked. See
  "Deployment" below.
- `deploy/crontab.example` -- every 5 minutes, with `TEMPEST_API_KEY` set
  inline (cron doesn't load your shell profile).
- `requirements.txt` / `setup.sh` -- Python dependencies (no system
  packages needed here, unlike the map projects, but `setup.sh` does fetch
  the Poppins font directly -- see its comment).

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
  missing data.
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
  The low is simply `min` of whatever's been observed so far -- before the
  actual overnight low has happened yet, the axis just reflects the
  partial day and widens as later observations come in. The high is
  `max(observed high, forecast high)`: `fetch_forecast.py`'s NWS forecast
  high (if `forecast.json` is present and for the same date) gives the
  axis headroom for the afternoon high before it's actually been observed;
  once it has, the observed max takes over as the larger of the two --
  `max()` is itself the override: a forecast is only ever a floor on the
  axis, never a ceiling that could clip an observation running hotter than
  it. With no `forecast.json`, the high is just the observed max so far,
  same as the low.
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
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `850-700-temp-chart/build_chart.py` and `tri-cities-temp-chart/build_chart.py`
  -- edit `build_chart.py` directly to adjust. The temperature line reuses
  the same forest green (`#164f29`) those charts use for their own
  observed-temperature series; `--mark-low` uses the same deep blue
  (`#0b3d91`) `hrrr-smoke-chart` uses for its second location line, and
  `--mark-high` the same dark red (`#a3242b`) `tri-cities-temp-chart` uses
  for record highs. No legend -- there's only the one series, labeled
  directly in the title/y-axis instead.
- **Logo placement defaults bottom-right**, matching those other temp
  charts, but moves to the top-right corner instead whenever the
  temperature line's actual drawn path (every segment, via
  `Path.intersects_bbox` -- not just the raw data points, since a segment
  between two widely spaced samples can cut through the corner without
  either endpoint landing inside it) would pass behind it there. A
  same-day chart's line only ever reaches that corner when "now" is late
  in the day and the temperature happens to be low then too, but it does
  happen (and more so once a forecast high has stretched the axis down
  into that corner's territory) -- checked once per render against the
  final axis bounds, before `--mark-low`/`--mark-high`'s own placement
  logic runs (which then sees the logo whichever corner it ended up in).
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
- **Subtitle** is just the date; timezone and station-vs-property
  distinctions live in the title's label and this file, not on the chart
  itself.

## Deployment

Published live at `https://images.ingallswx.com/hermiston_temp.png`,
refreshed every 5 minutes. See
[`tri-cities-7day-forecast/deploy/DEPLOY.md`](../tri-cities-7day-forecast/deploy/DEPLOY.md)
for the general first-time droplet setup (Phases 1-6: DigitalOcean
droplet, nginx, DNS, SSL, cloning the repo) -- that's shared
infrastructure, already set up for the other projects deployed there, so
this project only adds:

```bash
cd /opt/ingalls-weather-scripts/tempest-temp-chart
python3 -m venv venv
venv/bin/pip install -r requirements.txt
# (Poppins isn't apt-packaged -- setup.sh's font-fetch loop covers it if
# it isn't already on the droplet from another project's setup.)
bash setup.sh
```

Then install `deploy/crontab.example`'s lines via `crontab -e`, with your
real `TEMPEST_API_KEY` in place of the placeholder.

End-to-end test:

```bash
venv/bin/python3 deploy/publish_tempest.py
tail -f state/publish.log
```

Confirm `/var/www/images/hermiston_temp.png` exists and is fresh, then
load `https://images.ingallswx.com/hermiston_temp.png` in a browser. Wait
5 minutes and confirm the file's timestamp updates on its own while the
URL stays the same -- same overwrite-in-place-with-atomic-rename pattern,
and same nginx `Cache-Control: no-cache, max-age=60` handling, as every
other image served from that folder (see DEPLOY.md's Phase 9 for why the
short `max-age` matters even though it's not a bare `no-cache` -- WordPress's
Jetpack Image CDN doesn't revalidate with origin the way a browser does).

No nginx changes needed -- `nginx-images.conf` already serves any file
dropped into `/var/www/images/`, not just the forecast images it was
originally written for. If you add this chart to `image-hit-stats`'
dashboard categorization, its pattern is already in
`image-hit-stats/update_stats.py`'s `CATEGORY_PATTERNS`
(`hermiston_temp.png` -> "Tempest Temp Chart").
