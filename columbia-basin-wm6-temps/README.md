# Columbia Basin WM-6 3km High Temps Map

A styled map of WindBorne WeatherMesh-6 3km high (daily max) 2m
temperatures over the Columbia Basin, adapted from
[`../miles-city-wm6-temps/`](../miles-city-wm6-temps/) — same rendering
approach and house style, just pointed at the same domain as
[`../columbia-basin-alerts-map/`](../columbia-basin-alerts-map/) (North
Bend, WA down to the Baker City, OR corridor) with a matching city list.

"High" for a given date is the max hourly 2m temperature between 8am and
8pm local time (America/Los_Angeles) — the daytime window that reliably
contains the daily peak without fetching all 24 hourly grids.

## Usage

```bash
bash setup.sh                          # first time / fresh environment only
export WB_API_KEY=...                  # https://app.windbornesystems.com/api_tokens
python build_map.py                    # defaults to the coming Sunday
python build_map.py --date 2026-07-12
```

Live data is fetched directly from the WindBorne API (13 hourly gridded
forecasts, ~90 MB each — the wm-6-3km archive only serves whole-run
snapshots, so each hourly fetch pulls every surface variable even though
only `temperature_2m` is used). Output PNG lands in `output/`.

To render from a previously-saved grid instead of fetching live (useful
for testing, or to avoid re-pulling ~1 GB of hourly grids), pass
`--file path/to/snapshot.npz` — see `fetch_daily_high()` in `build_map.py`
for the npz layout (`lat`, `lon`, `temp_k`, all cropped to the map's bbox,
plus an optional `init_time` string for the subtitle's "Init" timestamp —
omit it and the subtitle just reads "unknown").

## Files

- `build_map.py` — fetches the hourly grids, reduces them to a daily-max
  temperature field, and renders the map. Map domain, city labels, and the
  daytime window are all defined near the top — edit directly to adjust.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`admin1_boundary_lines.json` / `admin0_boundary_lines.json` (state/province
and international borders), `land_slim.json` (coastline), and
`washington_roads.geojson` / `oregon_roads.geojson` /
`idaho_roads_north.geojson` / `pacific_nw_roads_west.geojson` (highways).
The last of those fills a gap: the WA/OR road files were pre-clipped to a
bounding box that stops short of the map's widened western edge and cities
like Portland, Salem, Longview, and Olympia, so it's a supplemental OSM
motorway/trunk extract (via the Overpass API, bbox
`44.0,-124.2,48.0,-122.4`) in the same GeoJSON schema as the others. The
Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- The color scale (`TEMP_COLOR_TABLE` in `build_map.py`) is a fixed
  Kelvin-to-RGB curve, not rescaled to each day's min/max — the same color
  always means the same absolute temperature across every map this script
  renders (and across the Miles City version, since they share the same
  table). The colorbar sits below the map, centered, with Fahrenheit ticks
  on the bottom edge and Celsius ticks on the top edge (both are the same
  underlying Kelvin scale, via `secondary_xaxis`) and only draws the slice
  of the table actually visible that day.
- City labels show that spot's forecast high on a second line, sampled
  from the resampled grid, tucked in tight below the name via points-based
  offsets (constant regardless of map scale) rather than degrees.
- Borders are drawn from Natural Earth's dedicated boundary-*line*
  datasets, not polygon outlines — see the Miles City README for why.
- The coastline (`land_slim.json`, the same layer `columbia-basin-alerts-map`
  uses for its land fill) is drawn outline-only here, with no fill, so it
  traces the Puget Sound without covering up the temperature color over
  water. Highways are motorway + trunk from the WA/OR/ID road files, styled
  the same pastel blue/orange as `columbia-basin-alerts-map`, and drawn on
  top of the state/international border lines rather than under them.
- The fetched grid is curvilinear and is resampled onto a padded regular
  lat/lon grid before rendering to avoid corner rendering gaps — see the
  Miles City README for the full explanation.
- The LON range is widened symmetrically beyond `columbia-basin-alerts-map`'s
  original extent so the rendered frame fills to the title's left margin
  and mirrors it on the right, rather than sitting centered with unused
  space on both sides — see the Miles City README for why a wider box
  alone doesn't do this.
- wm-6-3km's forecast horizon is short (currently 72 hours), so `--date`
  only works for the next few days out.
