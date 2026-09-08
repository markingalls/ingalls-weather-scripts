# Pacific Northwest First Freeze Change Map

A styled climatology map, companion to
[`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) (same domain, same
freeze definition, same GHCN-Daily source): each long-record station's
change in average first fall freeze date (daily low ≤32°F / 0°C) between
1961-1975 and 2006-2020, plotted as a diverging-colored dot at that
station's own location — blue where the freeze now arrives earlier than
it used to, red where it arrives later. No interpolation or shading
between stations, same reasoning as the sibling map.

## Files

- `fetch_climatology.py` — discovers GHCN-Daily stations inside the
  domain bbox with a real TMIN record spanning both 1961-1975 and
  2006-2020, pulls each period from NOAA's Access Data Service
  separately, and writes `climatology_change.json`: per station, each
  period's mean first-freeze day (as an offset from July 1) and the
  change between them.
- `build_map.py` — plots `climatology_change.json`'s stations as
  diverging-colored dots at their own locations and renders the map.
- `requirements.txt` / `setup.sh` — same as
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/).

Shared basemap data lives one level up in [`../maps/`](../maps/). The
Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                              # first time / fresh environment only
python3 fetch_climatology.py               # writes climatology_change.json (~5-8 min)
python3 build_map.py                       # reads climatology_change.json, renders the map
python3 fetch_climatology.py --min-years 8   # looser per-period completeness
python3 build_map.py --climatology data.json --out output/custom_name.png
```

## Why two 15-year windows instead of one 30-year trend

1961-1975 and 2006-2020 are two clean, non-overlapping, equal-length
(15-year) windows near the start and end of GHCN-Daily's practical
station history in this domain, giving a "then vs. now" comparison
simple enough to compute as two independent means rather than a full
per-station linear regression across a noisy ~60-year daily series. This
is a snapshot of change between two eras, not a trend line — it says
nothing about whether the shift was gradual, stepped, or concentrated in
a few anomalous years within either window.

## Why far fewer stations than the sibling map

[`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) only needs a
station to have ~20 of 30 years somewhere in 1991-2020, which around
1,400 stations in this domain satisfy. This map needs a station to have
real data on *both ends* of a ~60-year span (roughly 10 of 15 qualifying
years in 1961-1975 *and* 10 of 15 in 2006-2020) — only about 550
candidate stations even plausibly have that, and fewer still survive
after their actual daily values are checked. Long-running COOP
(volunteer/co-op observer) stations tend to survive this filter; newer
automated ASOS/AWOS airport stations, common at many modern
"first-freeze map" locations, generally don't have a 1960s-era record at
all. That's a real selection effect worth keeping in mind: this map's
station set skews toward stations that have been continuously observed
for six decades, not toward the same density/mix of stations the sibling
map shows.

## Methodology notes

- **Station discovery**: same `ghcnd-stations.txt` / `ghcnd-inventory.txt`
  approach as the sibling map, but filtered to TMIN inventory firstyear
  ≤1962 and lastyear ≥2019 (a loose prefilter for spanning both periods;
  real per-period completeness is checked against actual fetched daily
  values, not just this inventory range).
- **Daily readings**: same NCEI Access Data Service batching approach as
  the sibling map (`dataset=daily-summaries`, ~50 station IDs per
  request, `units=standard` for whole-°F readings with no client-side
  unit conversion) — but two separate fetches, one per period, each
  spanning only that period's own ~14.5 continuous years rather than one
  request covering the full 1961-2020 span (which would pull in ~30
  irrelevant intervening years per station).
- **Per station, per period, per year**: the first date on or after July
  1 whose TMIN reading is ≤32°F, expressed as an offset in days from that
  year's July 1 (0-183) — same leap-year-safe approach as the sibling
  map. A period's mean is only computed if at least `--min-years`
  (default 10) of its 15 candidate years produced a qualifying freeze
  date; a station is kept only if *both* periods clear that bar.
- **Change** is `recent_mean_offset_days - early_mean_offset_days`:
  positive means the average first freeze now falls later in the year
  than it did in 1961-1975 (a longer frost-free season, the more commonly
  expected direction under a warming climate); negative means earlier (a
  shorter frost-free season).
- **Color table**: fixed day-offset control points in
  `CHANGE_COLOR_TABLE_DAYS` (not rescaled per map, so a given shade always
  means the same day-count change across runs), diverging around 0 —
  blue for earlier, a light neutral tone near no change, red for later.
  The ±35-day endpoints were chosen from the actual fetched distribution
  (448 kept stations: mean +10.2d, median +9.0d, 5th/95th percentile
  about -4.6d/+31.5d) — wide enough to cover the bulk of stations with
  real contrast, while a handful of individual-station outliers out to
  -64d/+77d (thin/noisy records even after the completeness filter) get
  clipped to the table's end colors rather than stretching the whole
  scale to fit them.
- Same dot styling, alpha (0.4, colorbar included), station halo,
  figure geometry, `PlateCarree` domain, and no-lakes handling as
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) — see that
  project's README for the reasoning behind each.
