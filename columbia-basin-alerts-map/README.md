# Columbia Basin NWS Alerts Map

Generates a styled map of active NWS weather alerts across the Columbia
Basin (North Bend, WA to Baker City, OR corridor) for Ingalls Weather's
Instagram, using live NWS data plus a pre-built local basemap.

## Files

- `fetch_alerts.py` — pulls current active alerts + zone geometries from
  the NWS API for OR/WA and writes `alerts_with_zones.json`. Run this
  first, any time you want the map to reflect right-now conditions.
- `build_map.py` — renders the map using `alerts_with_zones.json` plus the
  static basemap files in `../maps/`. Writes `columbia_basin_alerts.png`.
- `requirements.txt` / `setup.sh` — Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/) so other
scripts can reuse it:

- `land_slim.json`, `countries_slim.json` — coastline / country
  boundaries (US, Canada, Mexico), simplified and clipped for this
  project's scale.
- `admin1_boundary_lines.json` — state/province outlines (drawn instead of
  `states_lakes_slim.json`'s own state polygons, which are coarser Natural
  Earth 10m outlines; this dedicated line dataset's US portion is Census
  TIGER/Line, so it tracks rivers like the WA/OR border tightly).
- `states_lakes_slim.json` — used only for its lake polygons here (the
  white-filled lakes); state outlines come from `admin1_boundary_lines.json`
  instead, see above.
- `counties_wa_or_id.geojson` — county boundaries for WA/OR/ID.
- `washington_roads.geojson`, `oregon_roads.geojson`,
  `idaho_roads_north.geojson` — motorway/trunk road geometry per state
  (Idaho covers everything north of McCall).

The Ingalls Weather logo (placed bottom-right on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh              # first time / fresh environment only
python3 fetch_alerts.py    # refresh live alerts
python3 build_map.py       # render columbia_basin_alerts.png
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
