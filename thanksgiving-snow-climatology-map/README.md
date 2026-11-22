# Pacific Northwest Thanksgiving Snow Climatology Map

A styled, gridded map of Washington, Oregon, and Idaho shaded by the
percent of Thanksgivings that had snow. It's built from every ACIS station's
own period of record (the backend behind xmACIS / SC-ACIS: NWS COOP,
first-order airport, CoCoRaHS, and SNOTEL daily records) and spread onto a
~3 km terrain grid. Major cities are labeled with the repo's standard
value-at-location style.

Two versions, picked with `--metric`:

- **`snowfall`** (default) — measurable snow *fell* on Thanksgiving Day
  (daily snowfall ≥ 0.1"; a trace doesn't count).
- **`depth`** — a "white Thanksgiving": snow *on the ground* Thanksgiving
  morning (snow depth ≥ 1").

## Files

- `fetch_climatology.py` — pulls every Thanksgiving's snowfall and snow
  depth for every WA/OR/ID station in ACIS, 1890–the most recent
  Thanksgiving, and writes `output/thanksgiving_snow.json`. One
  `MultiStnData` call per year; takes several minutes. Only needs
  re-running once a year, after a new Thanksgiving.
- `build_map.py` — computes each station's percentage from that JSON,
  grids it against terrain, and renders the map (~10 s). No network access
  needed: the terrain grid is cached in
  [`../maps/pnw_terrain_3km.npz`](../maps/) (ETOPO 2022, same file as
  `pnw-mslp-precip-map`) and re-fetched from NCEI only if it's missing.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, apt-only) and the Poppins font used for map labels.

Shared basemap data lives one level up in [`../maps/`](../maps/), and the
Ingalls Weather logo in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                         # first time / fresh environment only
python3 fetch_climatology.py          # once (several minutes)
python3 build_map.py                  # measurable snowfall
python3 build_map.py --metric depth   # snow on the ground
python3 build_map.py --min-years 30   # stricter station filter
```

Output: `output/thanksgiving_snow_<metric>.png`.

## Methodology notes

- **Thanksgiving date** follows the actual US holiday each year: the 4th
  Thursday of November from 1942 on; the second-to-last Thursday for
  1939–1941 (Roosevelt's "Franksgiving" — the federal date, used for all
  three states even though Idaho kept the old date); and the last
  Thursday of November before that.
- **Period of record is per station.** Each station uses every Thanksgiving
  that station has a valid reading for. Missing years are left out of both
  the numerator and denominator, not counted as "no snow." Stations with
  fewer than `--min-years` valid Thanksgivings (default 20) aren't
  used. This means stations aren't all from the same years: a long-running
  COOP site spans 1890s–present, while a SNOTEL site may only cover the
  last ~30 years. The subtitle's year range is the overall span.
- **What doesn't count:** a trace reading counts as no snow. A value ACIS
  flags as accumulated over several days (e.g. `1.0A`) or as part of a
  later total (`S`) is treated as missing, because it can't be pinned to
  Thanksgiving itself.
- **COOP observation time.** Most COOP observers read their gauges once
  a day around 7 AM, and ACIS files that reading under the observation
  date. So a COOP "Thanksgiving" value is really the 24 hours ending
  Thanksgiving morning. First-order airport stations report true calendar
  days. This is the standard caveat for any COOP-based single-day
  climatology.
- **Labels** follow the repo's default value-at-location convention
  (see `CLAUDE.md` / `blue-mountains-downslope-map`): no dot, the name on
  a 50% black box centered on the point, and the bold value above it. The
  value is the nearest grid cell, so it matches the shading under it.
  Tri-Cities is one label at the centroid of Kennewick, Pasco and
  Richland, averaging all three. A value that rounds to 0% shows the name
  only (Portland on the snowfall map). Snoqualmie Pass and Pendleton were
  tried and dropped because they crowded Seattle/Wenatchee and
  Tri-Cities.
- **The `depth` map runs much higher in the mountains** than the
  `snowfall` map. Partly that's physics (snow already on the ground counts
  even if none fell that day). Partly it's which stations report: SNOTEL
  sites measure snow depth but not daily snowfall, so high-elevation
  SNOTEL sites (often 100%) appear only on the `depth` map.
- **Color bins are fixed** (`PCT_BINS` / `PCT_COLORS`), not rescaled per
  map, so a shade means the same percentage on both versions. Under 1%
  gets its own tan so "essentially never" stands apart from "rarely." The
  colorbar uses equal-width blocks rather than a proportional scale, since
  the bins are uneven and most stations sit at the low end.
- **Gridding** (`grid_climatology()` in `build_map.py`) is a
  much-simplified PRISM-style approach. Thanksgiving snow odds depend
  mostly on elevation, which changes faster than the station spacing in
  the Cascades, Blues, and central Idaho, so plain distance interpolation
  would smear valley and pass stations together. Instead:
  1. At every ~3 km cell, fit a distance-weighted linear regression of
     station % on station elevation, using the 30 nearest stations
     (Gaussian weights, bandwidth at least 40 km), and evaluate it at the
     cell's own ETOPO elevation. The slope is clamped to 0–0.08 % per
     meter: odds can't drop with elevation, and a few stations can't fit a
     wild slope. The cell elevation is clamped to 300 m below / 400 m
     above the neighbors' range, so isolated peaks far above any station
     don't get unbounded extrapolation.
  2. Take each station's residual from that fit and spread it back out
     with short-range (20 km) weights. A nugget term fades the correction
     away from stations, so the grid honors each station where it is and
     relies on the elevation relationship in between.
  3. Lightly smooth (σ = 0.8 cells), clip to 0–100%, and mask to WA/OR/ID.
     For display only, the grid is bilinearly upsampled 4× so bin edges
     render as curves instead of ~3 km stair steps.

  Where stations are sparse, the grid is an estimate rather than a
  measurement. The Olympics, the North Cascades crest, and the central
  Idaho wilderness lean most on the elevation fit. That's especially true
  on the `snowfall` map, which has no SNOTEL sites up high.
- **Borders** use the same line-based approach as
  `western-us-noaa-outlooks/`. State and country lines come from the
  dedicated admin-1/admin-0 line files. State lines that duplicate the
  US/Canada border are trimmed, which removes the doubled WA/BC line
  through the San Juans. Each coastal state's offshore 3 nm state-waters
  line is dropped, which removes the phantom line along the WA/OR coast
  and through the Strait of Juan de Fuca.
- Only WA/OR/ID are shaded. Neighboring states and provinces are left as
  muted land, so they read as "no data" rather than "0%". (Canada's
  Thanksgiving is in October anyway.)
