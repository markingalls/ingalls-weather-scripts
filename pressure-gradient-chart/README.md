# Pressure Gradient Chart

Generates a styled multi-day pressure-gradient chart for Ingalls Weather's
Instagram: the difference between two stations' own pressure (station A
minus station B) across a trailing local-calendar-day window (3 days by
default), in 24-hour time. The x-axis right edge is simply the most
recent observation itself -- there's no dotted "now" marker partway
through empty space, since the data already runs all the way to the
edge of the plot. A dotted horizontal line at 0 mb marks the sign
change, labeled "Onshore Flow" above and "Offshore Flow" below. Same
canvas footprint and fonts as
[`tempest-pressure-chart/`](../tempest-pressure-chart/) -- a cousin chart,
not a sibling station, since both sides here come from NWS stations
rather than a personal Tempest station. Unlike that chart, there's no
current-conditions stat box -- this chart's whole point is the multi-day
trend, not a single "right now" number.

Defaults to **PDX (Portland International) minus HRI (Hermiston
Municipal)** -- the first pair this project was built around, and still
`fetch_gradient.py`/`fetch_metamesh_gradient.py`'s own CLI default. Both
are NWS ASOS/AWOS airport stations, chosen (over the Tempest-based
sibling charts) because they bracket the Columbia River Gorge: when
Portland's pressure is higher, air is pushed east through the gap
(onshore, positive); when Hermiston's is higher, air is pushed west
toward the coast (offshore, negative). `--station-a`/`--station-b` point
either script at a different pair for ad hoc use; see **Deployed pairs**
below for the full set of pairs actually live on the site.

## Files

- `fetch_gradient.py` -- pulls the last N days' (3 by default)
  near-real-time, already-near-sea-level pressure observations for both
  stations from api.weather.gov (see Notes below), pairs them up by
  nearest observation time, and writes `gradient_obs.json`. Run this any
  time you want the chart to reflect the latest observations.
- `build_chart.py` -- renders `gradient_obs.json` into `gradient_chart.png`.
- `fetch_metamesh_gradient.py` -- the obs + forecast sibling: pulls the
  past day's observed gradient (imports `fetch_gradient.py`'s own
  functions directly, rather than reimplementing them) plus the next 5
  days from WindBorne MetaMesh, and writes `gradient_forecast.json` with
  an `is_forecast` flag on every point. Requires `WB_API_KEY` in the
  environment.
- `build_forecast_chart.py` -- renders `gradient_forecast.json` into
  `gradient_forecast_chart.png`: a solid observed line, a dashed forecast
  line, and a dotted "now" boundary between them. Imports its fonts,
  palette, and gap/smoothing helpers from `build_chart.py` rather than
  duplicating them (see Notes below).
- `requirements.txt` / `setup.sh` -- Python dependencies and the Poppins
  font fetch (no system packages needed here, unlike the map projects).
- `deploy/pairs.py` -- the list of station pairs actually deployed live
  (see **Deployed pairs** below); `deploy/publish_gradient.py` and
  `deploy/publish_forecast_gradient.py` both loop over it.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Observed-only: last 3 days, PDX minus HRI
python3 fetch_gradient.py
python3 build_chart.py

# A longer window, a different end date, or a different station pair
python3 fetch_gradient.py --days 5 --date 2026-08-30 --station-a KPDX --station-b KHRI
python3 build_chart.py

# Observed + MetaMesh forecast: past day observed, next 5 days forecast
export WB_API_KEY=...               # your WindBorne API key
python3 fetch_metamesh_gradient.py
python3 build_forecast_chart.py
```

## Notes

- **Source**: `api.weather.gov`'s per-station `/observations` feed for
  each station, `start`/`end`-windowed to the requested trailing days
  (local midnight `--days` ago through the end of today, capped at "now").
  This is deliberately *not* the once-an-hour synoptic METAR product --
  NWS/FAA ASOS and AWOS sites also transmit "special" observations
  whenever conditions change enough to warrant one, and api.weather.gov
  folds all of those into the same feed, so a busy station like KPDX or
  KHRI actually reports roughly every 5 minutes, not on a fixed schedule.
  Confirmed live: a 2-hour window for KPDX returned 25 observations (one
  every ~4.8 minutes), and a full day returned 309 (one every ~4.7
  minutes) -- no API key needed, just a `User-Agent` identifying the
  requester (`fetch_gradient.py`'s `HEADERS`).
- **Pagination**: the endpoint caps a single request at 500 observations,
  and a multi-day window at ~5-minute cadence blows past that (3 days is
  ~850 per station) -- `fetch_observations()` follows the feed's own
  `pagination.next` cursor (pages come back newest-first) until a page's
  oldest observation reaches the window's start. The cursor URL doesn't
  carry the original `start` bound, so `pressure_series()` explicitly
  re-filters every observation back into `[start_utc, end_utc)` rather
  than trusting the last page to stop exactly there.
- **No further sea-level reduction is applied** -- `fetch_gradient.py`
  uses each observation's own `barometricPressure` field as-is. Despite
  the name, that field is *not* a station's raw absolute pressure; it's
  already an altimeter-setting-equivalent, near-sea-level value. Confirmed
  by comparing it against the same observations' own raw METAR text: at
  KPDX, `barometricPressure` read 1017.27 mb against that ob's own
  `A3004` altimeter (1017.2 mb); at KHRI (196 m elevation -- the more
  telling case, since any double-reduction bug shows up more there),
  `barometricPressure` read 1014.2 mb against that ob's own `A2995`
  altimeter (1014.2 mb) *and* its `SLP139` remark (1013.9 mb) -- all three
  agree to within a few tenths of a mb. An earlier version of this script
  additionally ran `barometricPressure` back through
  `tempest-pressure-chart/fetch_tempest.py`'s own station-elevation
  barometric formula (reasonable for that project, where Tempest's
  `obs_st` genuinely is raw station pressure) -- applied here, it
  double-counted the elevation correction NWS had already done, inflating
  KHRI's reading by ~24 mb and turning a real ~3 mb gradient into a
  fictitious ~-20 mb one. Verified against a live pull: the buggy version
  read -19.8 mb; the fixed version reads a plausible +2.7 mb for the same
  moment.
- **Default labels** (`--label-a`/`--label-b`, when not given explicitly)
  are each station's own bare 3-letter code (`bare_code()`, e.g. `KSEA` ->
  `SEA`), not a fixed default -- an earlier version hardcoded `PDX`/`HRI`
  as the defaults regardless of `--station-a`/`--station-b`, which would
  have mislabeled every other pair in `deploy/pairs.py` had it shipped
  that way.
- **Pairing the two stations' observations**: the two stations don't
  report on the same schedule (KPDX might land on :55/:00/:05, KHRI on
  :53/:58/:03), so `merge_gradient()` treats station A's own observation
  times as the master timeline and, for each one, finds the nearest
  station B observation within `MATCH_TOLERANCE` (4 minutes) --
  nearest-neighbor via `bisect`, not interpolation. A station-A time with
  no close-enough station-B match is dropped rather than paired with a
  stale reading.
- **Line smoothing**: a centered simple moving average (`smooth()`,
  `SMOOTHING_WINDOW = 3` samples, ~15 minutes at this chart's ~5-minute
  cadence -- much shorter than `tempest-pressure-chart`'s 15-sample window,
  which is tuned for that chart's ~1/minute Tempest cadence) is applied to
  the plotted line before gap-breaking, same order-of-operations reasoning
  as that sibling chart. The high/low markers and the y-axis bounds still
  use the full-window *raw* readings.
- **Window boundary** is a fixed local timezone (`--timezone`, default
  `America/Los_Angeles` -- both KPDX and KHRI sit in Pacific time), not a
  per-station lookup (NWS stations don't carry a timezone field the way a
  Tempest station's own API response does). `--days` (default 3) counts
  trailing local calendar days ending on `--date` (today, by default);
  `window_start`/`window_days` in `gradient_obs.json` drive the chart's
  x-axis directly, rather than re-deriving it from the observations
  themselves.
- **X-axis right edge is the last observation itself** (`times[-1]`), not
  `window_start + window_days` -- the data runs all the way to the edge
  of the plot, with "now" simply being wherever that edge falls. Ticks
  come every 12 hours, labeled with both date and time (`%-m/%-d %Hh`) --
  a bare `%H:%M`, fine for `tempest-pressure-chart`'s single-day chart,
  would leave two different days' midnights looking identical here.
- **Data outages show as a break in the line, not a straight line across
  them** -- same `insert_gaps()` NaN-insertion approach as
  `tempest-pressure-chart`, with a longer `MAX_GAP` (15 minutes, vs. that
  chart's 6) sized for this chart's slower ~5-minute native cadence.
- **Y-axis** (`gradient_ylim()`) is always symmetric around 0 -- the zero
  line stays vertically centered regardless of the data, rather than
  drifting off-center whenever only one side of the window overflows.
  Half-range is ±`DEFAULT_Y_RANGE_MB` (8 mb) by default, or the observed
  min/max magnitude padded by `OVERFLOW_PAD_MB` (2 mb) if that's bigger --
  so a lopsided window (say, a +6.4 mb high with only a -0.3 mb low)
  pushes *both* sides out to ±8.4, not just the top. Tick labels show an
  explicit `+`/`-` sign on every tick except 0 itself,
  since the sign is the point of this chart, unlike a plain pressure
  reading.
- **Zero line and onshore/offshore labels**: a dotted horizontal line at
  0 mb (`ZERO_LINE_COLOR`), with "Onshore Flow" text just above it and
  "Offshore Flow" just below (`place_flow_labels()`, a fixed
  `FLOW_LABEL_OFFSET_MB` = 0.2 mb either way, not scaled to the y-range --
  with the range now generally ±8 mb rather than tracking the window's own
  tighter swing, a range-proportional offset would push these labels much
  farther from the line than intended). Tries each of
  `FLOW_LABEL_X_CANDIDATES` (7 horizontal positions, left edge first) via
  a blended transform (`transAxes` for x, `transData` for y), landing on
  the first where neither label's box intersects any plotted line's own
  path -- a pair whose gradient hugs zero for its *entire* window (e.g.
  HRI-ALW, two nearby Basin stations with little pressure difference
  between them) can cross the left-edge default's narrow band almost
  continuously. Falls back to whichever candidate the line hits least
  (`_line_hits()`, a vertex-in-box count -- matplotlib doesn't expose a
  true intersection *area* between an arbitrary `Path` and a `Bbox`) if
  none is fully clear. Their final window extents are included in the
  high/low markers' collision-avoidance list (`occupied` in
  `build_chart()`), so a marker label never lands on top of them.
- **High/low markers** circle and label the window's highest and lowest
  gradient (`HIGH_COLOR`/`LOW_COLOR`, the same red/blue every chart in
  this family uses) -- always on, same reasoning as
  `tempest-pressure-chart`. Label values show an explicit sign (e.g. `Low:
  -3.2 mb`). Placement tries 8 offset/alignment candidates (more, and
  larger, than `tempest-pressure-chart`'s own 4 -- this chart's noisier,
  closer-together wiggles need more clearance to reliably miss the line),
  rejecting any that overlap another label/the logo *or* the line's own
  drawn path (`Path.intersects_bbox()` against the line's transformed
  path, not just the other labels' bounding boxes) -- an extreme sits ON
  the line, which keeps running right past it in both directions, so a
  label offset that clears every other label can still land right on top
  of the line a little further along. Falls back to whichever
  in-bounds, off-the-line candidate overlaps other labels least if none
  is fully clear.
- **No current-conditions stat box**, unlike `tempest-pressure-chart` --
  this chart's plot reclaims that vertical space (the full 0.65-of-figure
  axes height, same as that chart's own `--no-current-conditions` archive
  layout) rather than headlining a single "current" reading, since the
  point of a multi-day chart is the trend, not one instant.
- **Line color** (`GRADIENT_COLOR`, a muted navy) is deliberately its own
  hue, not `tempest-pressure-chart`'s forest green -- this chart plots a
  difference between two NWS stations, not one Tempest station's own
  reading, so it doesn't share that chart's "family" green.
- **Logo placement** (`place_logo()`) defaults bottom-right, moving to
  top-right if *any* plotted line's own drawn path would pass behind it
  there (`Path.intersects_bbox()`, same mechanism the high/low markers'
  own line-avoidance uses) -- falling back to bottom-right, the original
  default, if a line runs through both corners. Shared by
  `build_forecast_chart.py`, which passes it *both* of its lines (solid
  observed + dashed forecast) -- an earlier version there only ever
  checked whichever one happened to be assigned to a single
  `gradient_line` variable, silently never checking the other.
- Chart styling (fonts, dimensions) otherwise mirrors
  `tempest-pressure-chart/build_chart.py` directly -- edit `build_chart.py`
  to adjust.

## Obs + MetaMesh forecast version

`fetch_metamesh_gradient.py` + `build_forecast_chart.py` render a second
chart: the past day's NWS-observed gradient (solid line) plus the next 5
days from WindBorne MetaMesh (dashed line), split at a dotted "now"
boundary.

- **Forecast source**: MetaMesh's `pressure_msl` field (already mean sea
  level pressure, no reduction needed), queried by station id for both
  stations via `/forecasts/v1/point_forecast` -- the same endpoint and
  `WB_API_KEY` env var every other MetaMesh-consuming project in this repo
  uses (e.g. `tri-cities-7day-forecast/fetch_metamesh_forecast.py`).
  Confirmed live that MetaMesh accepts **KHRI directly as a station id**
  (not just coordinates), and that both stations' forecasts share the
  exact same hourly time grid -- no interpolation/pairing needed on the
  forecast side, unlike the observed segment's two independently-timed
  NWS feeds. Also confirmed `pressure_msl` tracks this project's own
  `barometricPressure`-based observed readings closely at the same hour
  (e.g. 1017.08 mb MetaMesh vs. 1017.27 mb observed for KPDX, 1014.08 mb
  vs. 1014.2 mb for KHRI), so the observed-to-forecast handoff doesn't
  visibly jump.
- **Combining the two segments**: `fetch_metamesh_gradient.py` writes one
  time-ascending `observations` array covering both, each point flagged
  `is_forecast: true/false`. `build_forecast_chart.py` splits on that flag
  to plot two `Line2D`s (solid observed, dashed forecast,
  `dashes=(5, 2.5)` -- the same dash pattern
  `tri-cities-temp-chart/build_chart.py` uses for its own forecast line),
  prepending the last observed point onto the forecast series so the
  dashed segment starts exactly where the solid one ends, with no visual
  gap at the boundary.
- **Code reuse**: `fetch_metamesh_gradient.py` imports
  `normalize_station_id`/`pressure_series`/`merge_gradient`/
  `MATCH_TOLERANCE` directly from `fetch_gradient.py` rather than
  reimplementing the observed-segment logic (pagination included).
  `build_forecast_chart.py` similarly imports its fonts, palette, sizing
  constants, and `insert_gaps()`/`smooth()`/`gradient_ylim()`/
  `place_logo()`/`place_flow_labels()` from `build_chart.py` -- same chart
  family (including the same ±8 mb default y-range, onshore/offshore
  label placement, and logo-placement mechanics), so duplicating those
  would just be a maintenance hazard.
- **Smoothing** applies only to the observed segment (same
  `SMOOTHING_WINDOW` as `build_chart.py`, since NWS's ~5-minute cadence is
  noisy at this scale) -- the forecast segment is left raw, since
  MetaMesh's hourly cadence is already coarse enough that smoothing it
  would blur real hour-to-hour model detail rather than remove noise.
- **High/low markers** cover the *entire* observed+forecast window, not
  just the observed segment -- the label itself doesn't distinguish
  whether the extreme fell in the observed or forecast portion, since the
  dotted "now" line and the solid/dashed line style already show that.
  Its collision-avoidance loop checks both the solid and dashed lines'
  own drawn paths (same `Path.intersects_bbox()` mechanism as
  `build_chart.py`), plus two extra, larger-offset fallback placements
  beyond `build_chart.py`'s own eight, and picks whichever in-bounds,
  off-both-lines candidate overlaps existing labels least if none is
  fully clear -- a forecast extreme landing right at the window's last
  point (in the bottom-right corner the logo already claims) is a real,
  not just hypothetical, case here.
- **Legend**: unlike the observed-only chart (a single series needs no
  key), this chart adds a small top-right legend distinguishing "Observed"
  from "MetaMesh Forecast" by line style.
- Everything else (zero line/onshore-offshore labels, logo placement, no
  current-conditions stat box, axis styling) is identical to `build_chart.py`.

## Deployed pairs

`deploy/pairs.py` lists every pair actually live on
`images.ingallswx.com`, each an NWS ASOS/AWOS airport pair bracketing a
specific Pacific Northwest terrain gap or valley -- confirmed live
(both against api.weather.gov and, for the forecast chart, WindBorne
MetaMesh) before adding a pair there:

| Pair | Gap / corridor |
| --- | --- |
| AST-PDX | Astoria (river mouth) to Portland -- lower Columbia River / coastal gradient |
| PDX-DLS | Portland to The Dalles -- western Columbia River Gorge |
| PDX-GEG | Portland to Spokane -- a long, cross-Cascades/eastern-WA span |
| PDX-HRI | Portland to Hermiston -- the original pair; central Gorge / Columbia Basin entrance |
| SEA-ELN | Seattle to Ellensburg -- Snoqualmie Pass / Stampede Gap, the I-90 corridor |
| HRI-ALW | Hermiston to Walla Walla -- an intra-Basin gradient around the Wallula Gap |

`publish_gradient.py` and `publish_forecast_gradient.py` (see
**Deployment** below) both loop over this same list in a single cron-driven
run, one `<slug>_gradient.png` / `<slug>_gradient_forecast.png` pair of
outputs per entry -- adding or removing a deployed pair is a `pairs.py`
edit, not a crontab or script change. Note that KDLS's barometer had a
multi-hour outage during testing (confirmed against its own raw METAR --
it stopped reporting `barometricPressure` mid-day without a station
change), so PDX-DLS's chart may show more/longer gaps than the other
pairs day to day; that's real station flakiness `insert_gaps()` is
already built to show honestly, not a bug in this project.

## Deployment

See [`tri-cities-7day-forecast/deploy/DEPLOY.md`](../tri-cities-7day-forecast/deploy/DEPLOY.md)
for the general first-time droplet setup (Phases 1-6: DigitalOcean
droplet, nginx, DNS, SSL, cloning the repo) -- that's shared
infrastructure, already set up for the other projects deployed there, so
this project only adds:

```bash
cd /opt/ingalls-weather-scripts/pressure-gradient-chart
python3 -m venv venv
venv/bin/pip install -r requirements.txt
# (Poppins isn't apt-packaged -- setup.sh's font-fetch loop covers it if
# it isn't already on the droplet from another project's setup.)
bash setup.sh
```

Then install `deploy/crontab.example`'s lines via `crontab -e`. Each line
covers *every* pair in `deploy/pairs.py` in one run (same
one-lock-many-outputs pattern as
`hrrr-smoke-chart/deploy/publish_smoke.py` -- one pair's fetch failing
doesn't stop the others):

- `publish_gradient.py` (observed-only) needs no API key --
  `api.weather.gov` is free -- and runs every 15 minutes (see that file's
  docstring for why 15 minutes is enough even though every pair's two
  stations update roughly every 5).
- `publish_forecast_gradient.py` (obs + MetaMesh forecast) needs
  `WB_API_KEY` -- skip that line in the crontab if `tempest-temp-chart`,
  `tri-cities-7day-forecast`, or any other MetaMesh-consuming project is
  already deployed on this droplet, since it sets the same variable -- and
  runs hourly.

Each pair gets its own intermediate JSON (`gradient_obs_<slug>.json` /
`gradient_forecast_<slug>.json`) so pairs never write over each other
within the same run.

End-to-end test, observed-only (all pairs):

```bash
venv/bin/python3 deploy/publish_gradient.py
tail -f state/publish.log
```

Confirm each pair's log line reads `succeeded`, and that
`/var/www/images/<slug>_gradient.png` exists and is fresh for all six
(e.g. `pdx_hri_gradient.png`, `sea_eln_gradient.png`, ...) -- load one in
a browser, e.g. `https://images.ingallswx.com/pdx_hri_gradient.png`. Wait
15 minutes and confirm its timestamp updates on its own while the URL
stays the same -- same overwrite-in-place-with-atomic-rename pattern, and
same nginx `Cache-Control: no-cache, max-age=60` handling, as every other
image served from that folder.

End-to-end test, obs + MetaMesh forecast (all pairs):

```bash
venv/bin/python3 deploy/publish_forecast_gradient.py
tail -f state/publish.log
```

Confirm `/var/www/images/<slug>_gradient_forecast.png` exists and is
fresh for all six, e.g.
`https://images.ingallswx.com/pdx_hri_gradient_forecast.png`. This uses
its own lock file (`state/forecast_run.lock`, distinct from
`publish_gradient.py`'s `state/run.lock`) so a slow run of one never
blocks the other.

Adding a 7th pair later: add one `(station_a, station_b, slug)` tuple to
`deploy/pairs.py` -- both publish scripts and both crontab lines already
cover it, nothing else to change.

No nginx changes needed -- `nginx-images.conf` already serves any file
dropped into `/var/www/images/`, not just the forecast images it was
originally written for.
