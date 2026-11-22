# Pacific Northwest Thanksgiving Snow Climatology Map

A styled map of Washington, Oregon, and Idaho: one dot per weather
station, colored by the percent of Thanksgivings in that station's period
of record that had snow. Major cities are labeled with their own
station's value. All data comes from ACIS (the backend behind
xmACIS / SC-ACIS) — NWS COOP, first-order (airport), CoCoRaHS, and
SNOTEL daily station records.

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
- `build_map.py` — computes each station's percentage from that JSON and
  renders the map. No network access needed, so it's quick to iterate on.
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
- **Period of record is per station.** Each dot uses every Thanksgiving
  that station has a valid reading for. Missing years are left out of both
  the numerator and denominator, not counted as "no snow." Stations with
  fewer than `--min-years` valid Thanksgivings (default 20) aren't
  plotted. This means dots aren't all from the same years: a long-running
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
- **City labels** (`CITY_STATIONS` in `build_map.py`) are matched by ACIS
  station ID, mostly first-order airports. Tri-Cities uses Kennewick
  COOP (`454154`), since Pasco airport only has ~14 Thanksgivings on
  record. Bend and McCall also use their long-running COOP sites. A
  station that falls below `--min-years` is skipped (and the script
  reports it).
- **The `depth` map runs much higher in the mountains** than the
  `snowfall` map. Partly that's physics (snow already on the ground counts
  even if none fell that day). Partly it's which stations report: SNOTEL
  sites measure snow depth but not daily snowfall, so high-elevation
  SNOTEL sites (often 100%) appear only on the `depth` map.
- **Color bins are fixed** (`PCT_BINS` / `PCT_COLORS`), not rescaled per
  map, so a shade means the same percentage on both versions. Exactly 0%
  gets its own tan so "never on record" stands apart from "rarely." The
  colorbar uses equal-width blocks rather than a proportional scale, since
  the bins are uneven and most stations sit at the low end.
- **Dots, not a smoothed field.** Thanksgiving snow odds depend mostly on
  elevation, which changes faster than the station spacing in the
  Cascades, Blue Mountains, and central Idaho. Interpolating between
  valley and pass stations would paint numbers that no station measured.
  Dots are drawn lowest-percentage first, so where stations cluster the
  snowier (usually higher) ones sit on top.
- WA/OR/ID are filled light; neighboring states and provinces are muted
  gray, so they read as "no data" rather than "0%". (Canada's
  Thanksgiving is in October anyway.)
