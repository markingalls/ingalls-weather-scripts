# Pressure Gradient Chart

Generates a styled same-day pressure-gradient chart for Ingalls Weather's
Instagram: the difference between two stations' own sea-level pressure
(station A minus station B) across the full 24-hour local calendar day, in
24-hour time -- since this is a same-day chart, the line legitimately stops
partway through the day rather than reaching the right edge, marked with a
dotted vertical line at the most recent observation. A dotted horizontal
line at 0 mb marks the sign change, labeled "Onshore Flow" above and
"Offshore Flow" below. A single current-conditions stat box (Current
Gradient) sits above the plot. Same canvas footprint, fonts, and overall
layout as [`tempest-pressure-chart/`](../tempest-pressure-chart/) -- a
cousin chart, not a sibling station, since both sides here come from NWS
stations rather than a personal Tempest station.

Defaults to **PDX (Portland International) minus HRI (Hermiston
Municipal)** -- the first pair this project is built around. Both are
NWS ASOS/AWOS airport stations, chosen (over the Tempest-based sibling
charts) because they bracket the Columbia River Gorge: when Portland's
sea-level pressure is higher, air is pushed east through the gap (onshore,
positive); when Hermiston's is higher, air is pushed west toward the coast
(offshore, negative). `fetch_gradient.py` takes `--station-a`/`--station-b`
so a different pair can be swapped in once more gradients are built.

## Files

- `fetch_gradient.py` -- pulls a day's near-real-time, already-near-sea-
  level pressure observations for both stations from api.weather.gov (see
  Notes below), pairs them up by nearest observation time, and writes
  `gradient_obs.json`. Run this any time you want the chart to reflect the
  latest observations.
- `build_chart.py` -- renders `gradient_obs.json` into `gradient_chart.png`.
- `requirements.txt` / `setup.sh` -- Python dependencies and the Poppins
  font fetch (no system packages needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

# Default: today, PDX minus HRI
python3 fetch_gradient.py
python3 build_chart.py

# A specific day or station pair
python3 fetch_gradient.py --date 2026-08-30 --station-a KPDX --station-b KHRI
python3 build_chart.py
```

## Notes

- **Source**: `api.weather.gov`'s per-station `/observations` feed for
  each station, `start`/`end`-windowed to the local calendar day. This is
  deliberately *not* the once-an-hour synoptic METAR product -- NWS/FAA
  ASOS and AWOS sites also transmit "special" observations whenever
  conditions change enough to warrant one, and api.weather.gov folds all
  of those into the same feed, so a busy station like KPDX or KHRI
  actually reports roughly every 5 minutes, not on a fixed schedule.
  Confirmed live: a 2-hour window for KPDX returned 25 observations (one
  every ~4.8 minutes), and a full day returned 309 (one every ~4.7
  minutes) -- no API key needed, just a `User-Agent` identifying the
  requester (`fetch_gradient.py`'s `HEADERS`).
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
  as that sibling chart. The current-conditions stat box and the y-axis
  bounds still use the single latest/full-range *raw* readings.
- **Day boundary** is a fixed local timezone (`--timezone`, default
  `America/Los_Angeles` -- both KPDX and KHRI sit in Pacific time), local
  midnight to midnight, not a per-station lookup (NWS stations don't carry
  a timezone field the way a Tempest station's own API response does).
- **X-axis spans the full 24-hour local day**, same tick layout as
  `tempest-pressure-chart`.
- **Data outages show as a break in the line, not a straight line across
  them** -- same `insert_gaps()` NaN-insertion approach as
  `tempest-pressure-chart`, with a longer `MAX_GAP` (15 minutes, vs. that
  chart's 6) sized for this chart's slower ~5-minute native cadence.
- **Y-axis** pads a flat ±1.5 mb around the day's observed range, same as
  `tempest-pressure-chart`, but additionally guarantees at least ±2.5 mb of
  room around 0 mb either way -- the zero line and its onshore/offshore
  labels need that space even on a day the gradient never actually changes
  sign. Tick labels show an explicit `+`/`-` sign (`%+.0f`), since the sign
  itself is the point of this chart, unlike a plain pressure reading.
- **Zero line and onshore/offshore labels**: a dotted horizontal line at
  0 mb (`ZERO_LINE_COLOR`), with "Onshore Flow" text above it and
  "Offshore Flow" below, pinned near the plot's left edge via a blended
  transform (`transAxes` for x, `transData` for y) so they stay put
  regardless of where the line itself sits that day, rather than drifting
  with the x-axis span.
- **High/low markers** circle and label the day's highest and lowest
  gradient (`HIGH_COLOR`/`LOW_COLOR`, the same red/blue every chart in
  this family uses) -- always on, same reasoning as
  `tempest-pressure-chart`. Label values show an explicit sign (e.g. `Low:
  -3.2 mb`). Same above-left/above-right/below-left/below-right fallback
  placement mechanism as that sibling chart.
- **Current-conditions stat box** reuses `tempest-pressure-chart`'s
  single-stat, centered-chip layout, but its background comes from
  `GRADIENT_COLOR_TABLE` -- a table diverging around 0 mb (warm/orange for
  a negative, offshore reading; blue for a positive, onshore one) via the
  same `interp_color()`/`text_color_for_bg()` mechanism as that sibling
  chart's absolute-pressure ramp, since this chart plots a signed
  difference rather than an absolute reading.
- **Line color** (`GRADIENT_COLOR`, a muted navy) is deliberately its own
  hue, not `tempest-pressure-chart`'s forest green -- this chart plots a
  difference between two NWS stations, not one Tempest station's own
  reading, so it doesn't share that chart's "family" green.
- Chart styling (fonts, dimensions, logo placement, current-conditions
  stat box mechanics) otherwise mirrors `tempest-pressure-chart/build_chart.py`
  directly -- edit `build_chart.py` to adjust.

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

Then install `deploy/crontab.example`'s line via `crontab -e` -- no API
key needed, `api.weather.gov` is free. `publish_gradient.py` runs every 15
minutes (see that file's docstring for why 15 minutes is enough even
though both stations' own feeds update roughly every 5).

End-to-end test:

```bash
venv/bin/python3 deploy/publish_gradient.py
tail -f state/publish.log
```

Confirm `/var/www/images/pdx_hri_gradient.png` exists and is fresh, then
load `https://images.ingallswx.com/pdx_hri_gradient.png` in a browser.
Wait 15 minutes and confirm the file's timestamp updates on its own while
the URL stays the same -- same overwrite-in-place-with-atomic-rename
pattern, and same nginx `Cache-Control: no-cache, max-age=60` handling, as
every other image served from that folder.

No nginx changes needed -- `nginx-images.conf` already serves any file
dropped into `/var/www/images/`, not just the forecast images it was
originally written for.
