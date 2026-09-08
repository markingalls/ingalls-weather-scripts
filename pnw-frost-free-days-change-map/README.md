# Pacific Northwest Frost-Free Period Change Map

A styled climatology map, companion to
[`../pnw-frost-free-days-map/`](../pnw-frost-free-days-map/) (same
domain, same frost-free-period methodology) and to
[`../pnw-first-freeze-change-map/`](../pnw-first-freeze-change-map/)
(same two-period comparison design): each long-record station's change
in average frost-free period length between 1961-1975 and 2006-2020,
plotted as a diverging-colored dot at that station's own location — blue
where the season is now shorter than it used to be, red where it's now
longer. No interpolation or shading between stations, same reasoning as
the sibling maps.

## Files

- `fetch_climatology.py` — discovers GHCN-Daily stations inside the
  domain bbox with a real TMIN record spanning both 1961-1975 and
  2006-2020 (identical filter to
  [`../pnw-first-freeze-change-map/`](../pnw-first-freeze-change-map/)),
  pulls each period's full calendar years from NOAA's Access Data
  Service separately, and writes `climatology_change.json`: per station,
  each period's mean frost-free day count and the change between them.
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
python3 fetch_climatology.py               # writes climatology_change.json (~6-9 min)
python3 build_map.py                       # reads climatology_change.json, renders the map
python3 fetch_climatology.py --min-years 8   # looser per-period completeness
python3 build_map.py --climatology data.json --out output/custom_name.png
```

## Why this needs full calendar years, not just July-December

[`../pnw-first-freeze-change-map/`](../pnw-first-freeze-change-map/)
only needs each year's July-December half. Frost-free period length
needs the *last spring* freeze too, which can fall anywhere from January
through June, so both period fetches here span the full January
1-December 31 of every candidate year rather than starting July 1 (or,
for the early period, than the sibling map's already-July-anchored
range).

## Why far fewer stations than the frost-free climatology map

Same station-filter story as
[`../pnw-first-freeze-change-map/`](../pnw-first-freeze-change-map/)
vs. [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/): this map
needs a station to have real data on *both ends* of a ~60-year span
(roughly 10 of 15 qualifying years in 1961-1975 *and* 10 of 15 in
2006-2020), not just somewhere in 1991-2020, so the candidate pool drops
from ~1,400 stations to ~550, and fewer still survive after their actual
daily values are checked. See that project's README for the same
station-selection-effect caveat (this map's stations skew toward
continuously-observed COOP sites, not the same density/mix the
climatology sibling maps show).

## Methodology notes

- **Station discovery**: same filter as
  [`../pnw-first-freeze-change-map/`](../pnw-first-freeze-change-map/)
  (TMIN inventory firstyear ≤1962, lastyear ≥2019).
- **Daily readings**: same NCEI Access Data Service batching approach as
  the sibling maps, two separate fetches (one per period), each spanning
  that period's full `<year>-01-01`..`<year>-12-31` range.
- **Per station, per period, per year**: the LAST date on or before June
  30 whose TMIN is ≤32°F and the FIRST date on or after July 1 whose TMIN
  is ≤32°F — same July 1 boundary as
  [`../pnw-frost-free-days-map/`](../pnw-frost-free-days-map/). If both
  are found, that year's frost-free length is the exact number of days
  between them via plain `date` subtraction (leap-year-safe by
  construction, no offset-averaging needed since only a day *count* ever
  gets averaged here, never a calendar date). A period's mean is only
  computed if at least `--min-years` (default 10) of its 15 candidate
  years produced a qualifying length; a station is kept only if *both*
  periods clear that bar.
- **Change** is `recent_mean_frost_free_days - early_mean_frost_free_days`:
  positive means the frost-free season now runs longer than it did in
  1961-1975; negative means shorter.
- **Color table**: fixed day-count control points in
  `CHANGE_COLOR_TABLE_DAYS` (not rescaled per map, so a given shade
  always means the same day-count change across runs), diverging around
  0 — blue for shorter, a light neutral tone near no change, red for
  longer.
- Same dot styling, station halo, figure geometry, `PlateCarree` domain,
  and no-lakes handling as the sibling maps — see
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/)'s README for the
  reasoning behind each. The dot/colorbar alpha is 0.55 (vs. the
  climatology sibling's 0.4), same as
  [`../pnw-first-freeze-change-map/`](../pnw-first-freeze-change-map/),
  since this diverging table sits closer to a light neutral tone near 0
  and needs more saturation to stay legible.
