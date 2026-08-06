# NWS Alerts Maps (Columbia Basin, Portland Metro, ...)

Generates a styled map of active NWS weather alerts for one of several
regions -- originally built just for the Columbia Basin (North Bend, WA to
Baker City, OR corridor) for Ingalls Weather's Instagram, now also
deployed live on the site for a Portland Metro variant at the same true
zoom level, using live NWS data plus a pre-built local basemap.

## Files

- `fetch_alerts.py` — pulls current active alerts + zone geometries from
  the NWS API for OR/WA/ID and writes `alerts_with_zones.json`. Every
  region currently defined pulls from this same query, so one fetch serves
  all of them -- run this first, any time you want the map(s) to reflect
  right-now conditions.
- `build_map.py` — `REGIONS` dict registry (extent, center point, city
  labels, roads files, title, output filename) plus `build_map(region_key,
  alerts_path, output_path)`, which renders one region using
  `alerts_with_zones.json` plus the static basemap files in `../maps/`.
  `python3 build_map.py --region <key>` from the command line.
- `deploy/publish_alerts.py` — cron entry point. Fetches once, builds and
  atomically publishes every region in `REGIONS`. One region failing
  doesn't stop the others.
- `requirements.txt` / `setup.sh` — Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).

## Regions

Every region shares the same `LON_SPAN`/`LAT_SPAN` (degrees shown across
the map) and `SATELLITE_HEIGHT` (the `NearsidePerspective` projection's
actual zoom control) -- adding a region means picking a center point, not
guessing a matching zoom level by eye. `region_extent()` derives each
region's actual `[lon_min, lon_max, lat_min, lat_max]` from its center
point at render time.

- **`columbia_basin`** — the original region. Center `(-119.75, 46.2)`,
  the same hand-tuned extent (`[-122.5, -117.0, 44.4, 48.0]`) this
  project started with -- `LON_SPAN`/`LAT_SPAN`/`SATELLITE_HEIGHT` were
  reverse-engineered from it, not the other way around.
- **`portland`** — same span/zoom, centered ~0.35 deg west of the true
  Portland point (`-122.95917, 45.59578` vs. the unshifted `-122.60917`
  that `tri-cities-7day-forecast/deploy/build_and_publish.py` uses for
  Portland) so the bottom-left legend lands mostly over open ocean instead
  of on top of Newport/Lincoln City. About a quarter of the frame is open
  ocean at this zoom level given how close Portland sits to the coast --
  expected, not a bug.
- **Planned, not built yet**: a wider "Washington + Oregon + adjacent
  areas" region. It'll need its own city list tuned for a much larger
  area, and likely more roads coverage than
  `washington_roads.geojson`/`oregon_roads.geojson`/
  `idaho_roads_north.geojson` currently provide -- southern OR below
  ~44°N is clipped out of `oregon_roads.geojson`, and there's no CA/NV/BC
  roads data at all yet, depending on how far "adjacent" ends up
  reaching. (Checked while adding the Portland region: contrary to an
  initial assumption, the *existing* road files are **not** clipped to
  the Columbia Basin corridor -- they already cover their full home
  states, e.g. `oregon_roads.geojson` already has dense Portland-area
  coverage. The wide region's gap is specifically the area *outside*
  WA/OR/north-ID, not anything within them.)

## City label placement

`cfg["cities"]` entries are `(name, lon, lat, pos)`, where `pos` is one of
8 directions: `left`/`right`/`above`/`below` plus the four diagonals
(`above-left`, `above-right`, `below-left`, `below-right`). Columbia
Basin's cities are spread far enough apart that plain left/right never
collided. Portland's immediate metro cluster is deliberately kept sparse
(just Portland, Vancouver, Hillsboro) rather than leaning on the diagonals
to fit more in -- an earlier version with Beaverton and Gresham also
included needed the full 8-way set just to keep five tightly-packed
labels from running together, and even then it read as busy. The 8-way
system is still there in the code for whichever region needs it next.
Government Camp, added on the map's southeast corner near the Mt. Hood
highway, uses `below-right` to stay clear of Hood River's label to its
north.

## Shared basemap data

Lives one level up in [`../maps/`](../maps/) so other scripts can reuse it:

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
  `idaho_roads_north.geojson` — motorway/trunk/primary road geometry, full
  home-state coverage for OR/WA (Idaho covers everything north of
  McCall). Not region-specific -- `cfg["roads_files"]` picks which of
  these each region actually loads (Portland skips Idaho's, since its
  extent never reaches that far east). Regenerated from fresh Geofabrik
  OR/WA/ID `.osm.pbf` extracts (`osmium tags-filter` on
  `highway=motorway,motorway_link,trunk,trunk_link,primary,primary_link`,
  then `osmium export` to GeoJSON) after discovering the original files
  only ever had `motorway`/`trunk` tags -- `primary` didn't exist in the
  data at all, so highways tagged that way in OSM (US-26 through
  Government Camp, US-97 through Bend/Redmond, most of the Willamette
  Valley's north-south highways) were structurally missing, not just
  filtered out at render time. `build_map.py` draws `primary` in its own
  color, one step duller than `trunk`.

The Ingalls Weather logo (placed bottom-right on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                              # first time / fresh environment only
python3 fetch_alerts.py                    # refresh live alerts (both regions read this)
python3 build_map.py --region columbia_basin
python3 build_map.py --region portland
```

## Notes

- Colors, region definitions, city labels, etc. are all defined near the
  top of `build_map.py` — edit directly to adjust.
- Alert colors follow the official NWS hazard color table (baked into
  `build_map.py`), so new alert types (Red Flag Warning, Winter Storm
  Warning, etc.) are colored automatically without edits.
- The legend/subtitle for a given region only reflect alert types with at
  least one zone actually inside *that region's* extent — NWS returns
  every active alert for the whole OR/WA/ID query, most of which sit outside
  whatever domain a given region is currently showing.
- Duplicate NWS products covering the exact same zone (this happens
  sometimes) are deduped so they don't double-stack shading.
- Natural Earth's `admin1_boundary_lines.json` includes each coastal
  state's offshore 3-nautical-mile maritime boundary as an ordinary
  admin-1 line -- `build_map.py` drops it via distance-from-land
  filtering. Oregon's version is its own separate feature (entirely
  offshore), so a whole-feature filter drops it cleanly; Washington's is
  fused into the *same* LineString as its real Canada/Columbia River land
  borders, so the whole feature's minimum distance from land is 0 and a
  whole-feature filter alone doesn't catch it -- `trim_offshore_segments()`
  splits on per-vertex distance instead, keeping only the near-land runs.
