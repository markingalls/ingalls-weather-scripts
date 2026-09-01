# SE Texas / SW Louisiana NWS Alerts Map

Generates a styled map of active NWS weather alerts across the Houston-
Galveston-Beaumont corridor and the adjacent SW Louisiana parishes around
Lake Charles and Lafayette, for Ingalls Weather's Instagram, using live
NWS data plus a pre-built local basemap. Same visual style as
[`../columbia-basin-alerts-map/`](../columbia-basin-alerts-map/), applied
to a different domain.

## Files

- `fetch_alerts.py` — pulls current active alerts + zone geometries from
  the NWS API for TX/LA and writes `alerts_with_zones.json`. Run this
  first, any time you want the map to reflect right-now conditions.
- `build_map.py` — renders the map using `alerts_with_zones.json` plus the
  static basemap files in `../maps/`. Writes `se_texas_alerts.png`.
- `requirements.txt` / `setup.sh` — Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/) so other
scripts can reuse it. This project reuses `land_slim.json`,
`countries_slim.json`, `admin1_boundary_lines.json`, and
`states_lakes_slim.json` as-is (they already cover this domain), plus two
files built specifically for this map:

- `counties_tx_la.geojson` — county/parish boundaries for all of Texas and
  Louisiana (US Census `cb_2022_us_county_20m` cartographic boundary
  file, filtered to STATEFP 48 and 22).
- `se_texas_la_primary_roads.geojson` — major roads clipped to this map's
  extent (plus a small margin), from the US Census
  `tl_2023_us_primaryroads` TIGER/Line file. **Unlike the Columbia Basin
  roads files, this is not OSM data** — Overpass and Geofabrik were both
  unreachable from the environment this was built in, so it's sourced
  from Census TIGER instead, using the `RTTYP` field as a stand-in for
  OSM's motorway/trunk split: `I` (Interstate) and `M` (named local
  roads, which in this domain are almost entirely Houston-area
  limited-access freeways/tollways like the Sam Houston Tollway and Gulf
  Fwy) are styled as motorway; `U`/`S`/`O` (US highway / state highway /
  other) are styled as trunk. If OSM access becomes available later, this
  file could be rebuilt with `osmium` the same way the Columbia Basin
  roads files were, for a closer match to true `highway=motorway`/`trunk`
  tagging.

The Ingalls Weather logo (placed bottom-right on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh              # first time / fresh environment only
python3 fetch_alerts.py    # refresh live alerts
python3 build_map.py       # render se_texas_alerts.png
```

## Notes

- The map domain, city labels, colors, etc. are all defined near the top
  of `build_map.py` — edit directly to adjust.
- Alert colors follow the official NWS hazard color table (baked into
  `build_map.py`), so new alert types (Red Flag Warning, Winter Storm
  Warning, etc.) are colored automatically without edits.
- The legend/subtitle only reflect alert types with at least one zone
  actually inside the current map extent — NWS returns every active
  alert for the whole state query, some of which can be far outside
  whatever domain this is currently showing.
- Duplicate NWS products covering the exact same zone (this happens
  sometimes) are deduped so they don't double-stack shading.
- Timestamps are shown in US Central time (`America/Chicago`), unlike the
  Columbia Basin map which uses Pacific time.
