# NWS Alerts Maps (Columbia Basin, Portland Metro, ...)

Generates a styled map of active NWS weather alerts for one of several
regions -- originally built just for the Columbia Basin (North Bend, WA to
Baker City, OR corridor) for Ingalls Weather's Instagram, now also
deployed live on the site for a Portland Metro variant at the same true
zoom level, plus a much wider Pacific Northwest + adjacent-states variant,
using live NWS data plus a pre-built local basemap. All three regions
publish on the same 5-minute cron cycle -- see `deploy/`.

## Files

- `fetch_alerts.py` — pulls current active alerts + zone geometries from
  the NWS API for `AREA` (currently `OR,WA,ID,CA,NV,MT,UT` -- every state
  any region's extent reaches into, however slightly) and writes
  `alerts_with_zones.json`. Every region currently defined pulls from this
  same query, so one fetch serves all of them -- run this first, any time
  you want the map(s) to reflect right-now conditions. Zone geometries are
  cached to disk (`state/zone_geometry_cache.json`, gitignored) across
  runs, since zone boundaries are effectively static and re-fetching all
  of them fresh every 5-minute cron tick doesn't scale once `AREA` covers
  seven states worth of zones -- a cold cache run takes a few minutes, a
  warm one finishes in seconds.
- `build_map.py` — `REGIONS` dict registry (extent, center point, city
  labels, roads files, title, output filename) plus `build_map(region_key,
  alerts_path, output_path)`, which renders one region using
  `alerts_with_zones.json` plus the static basemap files in `../maps/`.
  `python3 build_map.py --region <key>` from the command line.
- `deploy/publish_alerts.py` — cron entry point. Fetches once, builds and
  atomically publishes every region in `REGIONS`. One region failing
  doesn't stop the others.
- `requirements.txt` / `setup.sh` — Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip; osmium-tool
  is also installed here for regenerating road data, see below).

## Regions

Columbia Basin and Portland share the same `LON_SPAN`/`LAT_SPAN` (degrees
shown across the map) and `SATELLITE_HEIGHT` (the `NearsidePerspective`
projection's actual zoom control) -- adding one of *those* means picking a
center point, not guessing a matching zoom level by eye. `region_extent()`
derives each region's actual `[lon_min, lon_max, lat_min, lat_max]` from
its center point at render time. A region can override `lon_span`/
`lat_span`/`satellite_height` in its own `dict` entry (`build_map()` falls
back to the shared globals when they're absent) for a fundamentally
different zoom level -- `pnw_wide` does this since it's showing an area
several times larger than Columbia Basin/Portland's shared true-zoom-level
setup, not a variant of it.

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
- **`pnw_wide`** — Washington, Oregon, and Idaho in full, plus slivers of
  northern California, northern Nevada, western Montana, and the very NW
  corner of Utah wherever the frame happens to reach. Center
  `(-119.3, 44.9)`, its own `lon_span=13.0`/`lat_span=8.8`/
  `satellite_height=22_000_000`, legend anchored `upper right` instead of
  the default `lower left` (its lower-left corner covers real CA cities
  like Weed at this zoom, not empty ocean the way Columbia Basin/
  Portland's does). Center point, zoom, and city roster all moved several
  times during development -- treat anything above as current-as-of-
  last-edit, not permanent.

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
north. On `pnw_wide`, Spokane specifically uses `left` rather than
anything on the right side -- it sits close enough to the upper-right
legend that a position tuned to clear one particular legend row count
(e.g. exactly 4 active alert types) gets clipped by a taller one (5+
types, still under the size-halving threshold); `left` is robust to the
legend's height varying with the day's alert count instead.

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
- `counties_wa_or_id.geojson` — county boundaries for WA/OR/ID only, not
  used at all for the CA/NV/MT/UT slivers `pnw_wide` shows -- those areas
  just have no county-line overlay, which is a cosmetic gap, not a bug
  (alert zone shapes come from NWS directly, unaffected by this file).
- `washington_roads.geojson`, `oregon_roads.geojson`, `idaho_roads.geojson`
  (full state), `idaho_roads_north.geojson` (older north-of-McCall-only
  clip, still used by `columbia_basin`/`portland`), `california_roads_
  north.geojson` (north of Redding), `nevada_roads_north.geojson`,
  `montana_roads_west.geojson`, `utah_roads_northwest.geojson` — all
  motorway/trunk/primary road geometry (`_link` variants of each too),
  generated the same way: a Geofabrik `<state>.osm.pbf` extract, `osmium
  tags-filter` on `highway=motorway,motorway_link,trunk,trunk_link,
  primary,primary_link`, then `osmium export` to GeoJSON, clipped down to
  whatever sliver of a large adjacent state a region's extent actually
  needs (full-state CA is ~1.3GB unclipped -- always filter by tag *and*
  clip geographically before committing a new state's roads here). Not
  region-specific -- `cfg["roads_files"]` picks which files each region
  actually loads. The OR/WA/ID files were regenerated from the originals
  after discovering they only ever had `motorway`/`trunk` tags --
  `primary` didn't exist in the data at all, so highways tagged that way
  in OSM (US-26 through Government Camp, US-97 through Bend/Redmond, most
  of the Willamette Valley's north-south highways) were structurally
  missing, not just filtered out at render time. `build_map.py` draws
  `primary` in its own color, one step duller than `trunk`.

The Ingalls Weather logo (placed bottom-right on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                              # first time / fresh environment only
python3 fetch_alerts.py                    # refresh live alerts (every region reads this)
python3 build_map.py --region columbia_basin
python3 build_map.py --region portland
python3 build_map.py --region pnw_wide
```

## Notes

- Colors, region definitions, city labels, etc. are all defined near the
  top of `build_map.py` — edit directly to adjust.
- Alert colors follow the official NWS hazard color table (baked into
  `build_map.py`), so new alert types (Red Flag Warning, Winter Storm
  Warning, etc.) are colored automatically without edits.
- The legend/subtitle for a given region only reflect alert types with at
  least one zone actually inside *that region's* extent — NWS returns
  every active alert for the whole `AREA` query, most of which sit outside
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
- `countries_slim.json`'s own US/Canada/Mexico border lines have a
  similar but distinct problem: several stretches are over-simplified
  down to a single straight segment several degrees long (worst case: the
  entire WA-to-Minnesota run of the 49th parallel collapsed to one
  27.6-degree segment) that cuts straight across the much more detailed
  `admin1_boundary_lines.json` line underneath once a region's extent is
  wide enough to actually see it -- invisible at Columbia Basin/Portland's
  zoom, glaring on `pnw_wide`. `drop_long_segments()` splits on segment
  length (anything over `MAX_BORDER_SEGMENT_DEG` = 3 degrees, well above
  any real simplification grain seen in either file) the same way
  `trim_offshore_segments()` splits on distance -- both are safe on any
  outline-only (`facecolor="none"`) layer since there's no fill to
  preserve, only the traced line.
- Severe Thunderstorm/Tornado/Flash Flood Warnings are NWS's polygon-type
  products -- literal storm-tracking polygons, not tied to county/zone
  boundaries the way every other product here is. `POLYGON_WARNING_EVENTS`
  pulls them out of the normal shaded/candy-stripe-overlap treatment and
  draws them instead as a colored line with a black outline, on top of
  everything else, so a short-fused warning reads as "this exact path,"
  not "this whole county." The legend shows a colored line for these
  instead of a filled swatch to match.
- More than 5 alert types active at once roughly halves the legend's
  font/handle/spacing so it still fits without spilling off the map. If
  editing this: `fig.legend(..., prop=X, fontsize=Y)` silently ignores
  `fontsize` whenever `prop` is also a `FontProperties` instance --
  matplotlib only falls back to `fontsize` when `prop` is `None` -- so the
  size has to be set via `X.copy().set_size(Y)` on the `FontProperties`
  itself instead.
