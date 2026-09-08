# Pacific Northwest Frost-Free Period Map

A styled climatology map, companion to
[`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) (same domain, same
station discovery, same GHCN-Daily source): each station's 1991-2020
average number of frost-free days — the span between the last spring
date and the first fall date its daily low temperature drops to ≤32°F
(0°C) — plotted as a sequentially-colored dot at that station's own
location, short (purple/blue, high mountain interior) to long (gold,
milder low-elevation and coastal areas). No interpolation or shading
between stations, same reasoning as the sibling map.

## Files

- `fetch_climatology.py` — discovers GHCN-Daily stations inside the
  domain bbox (identical filter to
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/)), pulls each
  one's full-calendar-year daily TMIN for 1991-2020 from NOAA's Access
  Data Service, and writes `climatology.json`: per station, the
  mean/median number of frost-free days per year and how many of the 30
  years actually qualified.
- `build_map.py` — plots `climatology.json`'s stations as sequentially
  colored dots at their own locations and renders the map.
- `requirements.txt` / `setup.sh` — same as
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/).

Shared basemap data lives one level up in [`../maps/`](../maps/). The
Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                              # first time / fresh environment only
python3 fetch_climatology.py               # writes climatology.json (~4-6 min)
python3 build_map.py                       # reads climatology.json, renders the map
python3 fetch_climatology.py --min-years 25  # stricter per-station completeness
python3 build_map.py --climatology data.json --out output/custom_name.png
```

## Why this needs full calendar years, not just July-December

[`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) only needs each
year's July-December half (the first fall freeze), so its fetch starts
July 1. Frost-free period length needs the *last spring* freeze too —
which can fall anywhere from January through June — so this script
fetches the full January 1-December 31 span for every year instead.

## Methodology notes

- **Station discovery**: identical to
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) — same bbox,
  same TMIN inventory prefilter (firstyear ≤1995, lastyear ≥2018).
- **Daily readings**: same NCEI Access Data Service batching approach as
  the sibling map (`dataset=daily-summaries`, ~50 station IDs per
  request, `units=standard` for whole-°F readings with no client-side
  unit conversion), but the full `1991-01-01`..`2020-12-31` continuous
  range rather than starting July 1.
- **Per station, per year**: the LAST date on or before June 30 whose
  TMIN is ≤32°F ("last spring freeze") and the FIRST date on or after
  July 1 whose TMIN is ≤32°F ("first fall freeze") — July 1 is the same
  spring/fall boundary the sibling map uses. If both are found that year,
  that year's frost-free length is the exact number of days between them
  via plain `date` subtraction, so leap years are handled automatically
  — no manual day-of-year offset math needed, unlike the sibling map
  (which has to average a *calendar date* across years and specifically
  works around leap-year misalignment; this script only ever averages a
  plain day *count*, which has no such issue).
- A station is kept only if at least `--min-years` (default 20) of the 30
  candidate years produced a qualifying frost-free length (both a spring
  and a fall freeze that year). Both mean and median frost-free days are
  recorded; `build_map.py` plots the mean.
- **Caveat inherited from the sibling map's July 1 boundary**: a station
  where freezing conditions persist past June 30 (e.g. high mountain
  sites) has its spring search cut off there, and an early-July freeze at
  such a site gets counted as *that year's fall freeze* instead — "a
  frost-free period" isn't a very meaningful concept at a site like that
  to begin with, so this isn't treated as a special case, just carried
  forward as-is from the sibling map's convention.
- **Color table**: fixed day-count control points in `DAYS_COLOR_TABLE`
  (not rescaled per map, so a given shade always means the same season
  length across runs), sequential short-to-long: purple/blue through
  teal/green to gold — a different hue path than the sibling map's
  purple-to-red calendar-date table (which ends in red/orange), so the
  two read as clearly different metrics despite sharing a purple start.
- Same dot styling (alpha 0.4, colorbar included), station halo, figure
  geometry, `PlateCarree` domain, and no-lakes handling as
  [`../pnw-first-freeze-map/`](../pnw-first-freeze-map/) — see that
  project's README for the reasoning behind each.
