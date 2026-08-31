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
- `build_chart.py` -- renders `tempest_obs.json` into
  `tempest_temp_chart.png`.
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

# Circle and label the day's lowest observation
python3 build_chart.py --mark-low
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
  the axis being cropped to only the elapsed hours. Ticks are every 6 hours
  in 24-hour time (`00:00`/`06:00`/`12:00`/`18:00`); a dotted vertical
  marker at the last observation makes the stopping point read as current,
  not as missing data.
- **Y-axis** is fixed to 3°F below the day's observed low and 3°F above
  the day's observed high -- both are simply `min`/`max` of whatever's been
  observed so far, so before the actual overnight low or afternoon high has
  happened yet, the axis just reflects the partial day and widens as later
  observations come in. No forecast source is wired into this project, so
  there's no forward-looking high/low to pad toward in the meantime.
- **`--mark-low`** (off by default) circles the day's lowest observation
  and labels it `Low: XX.X°F at HH:MM`, offset below-and-right of the point
  so it clears both the temperature line and the "now" marker.
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `850-700-temp-chart/build_chart.py` and `tri-cities-temp-chart/build_chart.py`
  -- edit `build_chart.py` directly to adjust. The temperature line reuses
  the same forest green (`#164f29`) those charts use for their own
  observed-temperature series; the `--mark-low` callout uses the same deep
  blue (`#0b3d91`) `hrrr-smoke-chart` uses for its second location line. No
  legend -- there's only the one series, labeled directly in the
  title/y-axis instead.
- **Display label**: `fetch_tempest.py` writes both the Tempest API's raw
  station name (`station_name`) and a display `label` used in the chart
  title. `STATION_LABEL_OVERRIDES` in `fetch_tempest.py` maps known raw
  names to a more recognizable label (e.g. `"Highland Hills"` →
  `"Highland Hills (Hermiston)"`, the property name plus its town); pass
  `--label` to override for any station, known or not.
