# GLM Lightning Maps (Last 24 Hours)

A styled map of the last 24 hours of lightning flashes, for each of eight
regions -- Columbia Basin, Portland Metro, Pacific Northwest, BC
Interior, Offshore Pacific Northwest, Full British Columbia, Puget Sound,
and Lower Mainland + Victoria -- sourced from the GLM (Geostationary
Lightning Mapper) instrument on GOES-18, NOAA's operational GOES-West
satellite. Real-time
companion: [`../columbia-basin-lightning-realtime-map/`](../columbia-basin-lightning-realtime-map/)
(last 2 hours). 5-day rolling archive companion:
[`../columbia-basin-lightning-daily-map/`](../columbia-basin-lightning-daily-map/).

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections from the
  last 24 hours out of NOAA's public `noaa-goes18` bucket on AWS Open
  Data, over a domain spanning all eight regions below, and writes
  `lightning_last24h.json`. Run this first, any time you want the map(s)
  to reflect right-now conditions.
- `build_map.py` -- `REGIONS` dict registry (extent, center point, city
  labels, roads files, output filename) plus `build_map(region_key,
  lightning_path, output_path)`, which renders one region using
  `lightning_last24h.json` plus the static basemap files in `../maps/`.
  `python3 build_map.py --region <key>` from the command line.
- `deploy/publish_lightning.py` -- cron entry point. Fetches once, builds
  and atomically publishes every region in `REGIONS`. One region failing
  doesn't stop the others. `fcntl.flock`-locked so an overlapping cron
  tick skips instead of running a second pass concurrently.
- `deploy/crontab.example` -- every 15 minutes; lightning has no fixed
  issuance schedule to align to, so like `../columbia-basin-alerts-map/`
  this is a polling interval, not a cycle time.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).
- `basemap_cache/` -- not committed, gitignored, and needs no manual setup
  -- see "Basemap raster caching" under Notes below.

## Regions

Same `REGIONS`-dict pattern as `../columbia-basin-alerts-map/build_map.py`
-- see that project's README for the full writeup of `region_extent()`,
the shared "true zoom" `LON_SPAN`/`LAT_SPAN`/`SATELLITE_HEIGHT`, and how
a region overrides them for a different zoom level.

- **`columbia_basin`** -- the original region, unchanged: center
  `(-119.75, 46.2)`, same domain as `../columbia-basin-alerts-map/` and
  `../columbia-basin-temps/`.
- **`portland`** -- the unshifted "Portland point" (`-122.60917,
  45.59578`) that `tri-cities-7day-forecast` and `850-700-temp-chart`
  use -- unlike `columbia-basin-alerts-map`'s `portland` region, this one
  doesn't need to shift for a legend collision (only one legend entry
  here, not a variable-length NWS event list).
- **`pnw`** -- same extent as `columbia-basin-alerts-map`'s `pnw_wide`
  region (`center=(-119.3, 44.9)`, `lon_span=13.0`, `lat_span=8.8`,
  `satellite_height=22_000_000`), so the same named domain looks the same
  across both products. Reaches the WA/OR coast and the US/Canada border
  widely enough to need the same two fixes as that project (see Notes).
- **`bc_interior`** -- new, no prior product on this domain. Wider than
  true-zoom (`lon_span=8.87`, `lat_span=5.2`, `satellite_height=9_000_000`),
  center `-119.68, 51.71` -- covers the Southern Interior
  (Kamloops/Kelowna/Vernon/Penticton), Prince George, the southwest
  corridor toward the coast (Hope, Whistler), and the Yellowhead Pass area
  just across the Alberta border (Jasper, Nordegg, Banff). `lat_span` and
  `satellite_height` are independent choices (5.2 for Prince George's
  latitude, 9,000,000 so that span doesn't clip at the frame edges) and
  aren't tied to any particular storm's shape -- a bounded regional map
  will always have *some* edge, and real weather extending past it
  (tapering off outside the frame rather than being visibly truncated
  inside it) is expected, not a bug. `lon_span`, however, is *not* picked
  independently: it's `lat_span` converted to real ground km (`5.2 *
  111.32`) times Columbia Basin's true-zoom width:height ratio in km
  (`(5.5 * cos(46.2deg)) / 3.6`), converted back to degrees at this
  region's own latitude (dividing by `111.32 * cos(51.71deg)`) --
  `8.87`. Picking `lon_span` by eye in raw degrees, as earlier revisions
  of this region did, produces a box whose real-world aspect ratio
  doesn't match the other true-zoom regions, since a degree of longitude
  covers less ground the farther north you go; that mismatch (not the
  zoom level or the fetch) was the actual source of earlier "hard
  cutoff" complaints about this region. `fetch_lightning.py`'s shared
  bbox is still re-verified after every domain change to confirm it
  fully contains all four regions' extents, and its east edge is
  deliberately pulled well past what any region currently renders (out
  to roughly Alberta's eastern border) since storms east of the frame
  are common and fetch cost doesn't scale with bbox area -- it's fine
  for the pull to cover ground no map currently displays. Uses
  `America/Vancouver` (not
  `America/Los_Angeles`) for its day/time labels -- numerically identical
  to Pacific time for any date since 2007, so this is a correctness/clarity
  fix rather than a behavior change. Roads come from
  `../maps/british_columbia_roads.geojson` (Geofabrik BC extract, clipped
  to LON -125.5 to -113.5 / LAT 48.5 to 55.0 -- widened east after an
  earlier -116.0 clip was silently losing highways in southeastern BC,
  e.g. around Cranbrook/Fernie) plus `../maps/alberta_roads_west.geojson`
  (Geofabrik Alberta extract, clipped to LON -120.0 to -113.0 / LAT 48.5
  to 55.0) -- both filtered to motorway/trunk/primary.
- **`offshore_pnw`** -- same wide-zoom style as `pnw` (`lon_span=13.0`,
  `lat_span=8.8`, `satellite_height=22_000_000`), recentered west over
  open water at `(-128.0, 45.5)` -- `pnw`'s own frame is centered well
  inland and only shows a coastal sliver, so this is a dedicated view of
  offshore convection from Northern California up through Vancouver
  Island. Roads: `washington_roads.geojson`, `oregon_roads.geojson`,
  `california_roads_north.geojson`, `british_columbia_roads.geojson`
  (all coastal slivers on the frame's east edge). The only region with
  `show_gridlines=True`: lat/lon gridlines drawn at `zorder=0.95`, just
  under land's `zorder=1`, so land's opaque fill paints over them and
  they only show up over open water -- a chart-like touch that fits a
  map that's mostly ocean, and one every other region skips since it'd
  mostly just cross land there.
- **`full_bc`** -- new, covers the entire province coast-to-Alberta-border
  and past the Yukon boundary. Center `(-125.5, 54.25)`, `lat_span=14.5`,
  `satellite_height=41_000_000`. `lon_span` started from the same
  ground-km/`cos(lat)` conversion `bc_interior`'s is derived from, but
  over this much bigger a span (and this much bigger a swing in latitude
  across the frame, 47 to 61.5) `NearsidePerspective` doesn't scale
  linearly with that formula's flat-ground assumption the way it does for
  `bc_interior`'s smaller extent -- the formula's own output (`26.2`)
  rendered noticeably wider than every other region's tight-cropped
  output. `lon_span=23.2` is tuned from that starting point against the
  actual rendered width instead, landing in the same ~1510-1554px band
  every other region falls into (all eight regions are meant to come out
  the same size on the page). `center_lon` sits 1 degree east of this
  region's true geographic center so Calgary and Edmonton clear the east
  edge without widening `lon_span` back past that matched-width band.
  Uses `America/Vancouver` like `bc_interior`. Roads:
  `bc_yukon_ab_ak_major_roads.geojson` -- generated from Natural Earth's
  own `ne_10m_roads_north_america` (not the usual OSM/Geofabrik extracts
  the other `roads_files` use: Geofabrik's download server refused every
  connection from this environment, and at this zoomed-way-out scale a
  coarser highway-only dataset reads better anyway), filtered to `type`
  in `(Freeway, Tollway, Primary)` -- NE's own top two road tiers, plus
  `Tollway`, its own separate category for divided/limited-access toll
  roads (without it, the Coquihalla -- BC-5 between Hope and Merritt --
  and a short WA-16/Tacoma Narrows Bridge segment were both missing
  despite being freeway-grade) -- and remapped to `highway=motorway`
  (`Freeway`/`Tollway`) or `trunk` (`Primary`) so the existing MOTORWAY/
  TRUNK/PRIMARY classification in `_draw_static_layers` just works.
  Nothing in the file is tagged `primary`, so the region renders freeways
  (toll or not) and major highways only, by construction rather than a
  per-region filter switch. Covers BC, Alberta, Yukon, Alaska, Northwest
  Territories, and the WA/ID/MT slivers this frame's edges reach into.
  `show_counties=False` (this region's only US territory is a sliver at
  the edge of an otherwise Canada-focused map, where county lines are
  just clutter) and `roads_source="Natural Earth"` (used in the
  attribution line instead of the default "OpenStreetMap", which would
  misattribute this region's roads) are two new per-region config keys;
  no other region currently sets either.
- **`puget_sound`** -- true-zoom, same `LAT_SPAN` as `columbia_basin`/
  `portland` but `lon_span=5.63` (bumped a little over the shared
  `LON_SPAN` default): this region's center sits noticeably further
  north (47.55 vs Columbia Basin's 46.2), and `NearsidePerspective`
  renders the same longitude span narrower the further the frame center
  sits from the equator, so the plain default came out visibly narrower
  than the other regions' output. Tuned empirically against rendered
  output width (same ~1510-1554px target band as `full_bc` above) rather
  than the ground-km formula -- close enough a latitude gap that
  eyeballing the match was simpler and just as accurate. Center
  `(-122.4, 47.55)`. Roads: `washington_roads.geojson`.
- **`lower_mainland_victoria`** -- `lon_span=5.22`/`lat_span=3.24`: a
  true-zoom-derived `5.8`/`3.6` (tuned the same empirical way as
  `puget_sound`'s, for the same reason -- this region sits even further
  north, 49.05), then both shrunk 10% together (same ratio, so the data
  aspect ratio -- and with it, the rendered output's pixel dimensions --
  doesn't shift, only how tight the framing looks) for a requested zoom
  in. Center `(-122.93, 49.05)`. City list started from the one-off
  `lower-mainland-victoria-lightning-map/` project (Whistler, Hope, Port
  Renfrew, and Everett mark that domain's rough N/E/W/S extent), reused
  here since it already went through a round of real-world tuning (fixed
  a double border line and a cut-off Olympic Peninsula highway); since
  then Coquitlam, Sooke, Oak Harbor, and Boston Bar have been dropped and
  Courtenay, Merritt, and Mount Vernon added. `show_counties=False`, same
  reasoning as `full_bc`'s (this region's only US territory is the WA
  sliver at its south edge). Uses `America/Vancouver`. Roads:
  `british_columbia_roads.geojson`, `washington_roads.geojson`.

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                        # first time / fresh environment only
python3 fetch_lightning.py           # pull the 24h of GLM flashes ending now (all 8 regions read this)
python3 fetch_lightning.py --end-pt "14:00"               # ... ending 14:00 PT today
python3 fetch_lightning.py --end-pt "2026-07-16 14:00"    # ... ending 14:00 PT on a given date
python3 build_map.py --region columbia_basin
python3 build_map.py --region portland
python3 build_map.py --region pnw
python3 build_map.py --region bc_interior
python3 build_map.py --region offshore_pnw
python3 build_map.py --region full_bc
python3 build_map.py --region puget_sound
python3 build_map.py --region lower_mainland_victoria
```

## Notes

- **City label offset scales with the region's own span**: `POS_DX`/
  `POS_DY` (in `build_map()`, where city dots/labels are drawn) were a
  fixed degree offset from each dot regardless of region -- fine while
  every region was close to true-zoom scale, but a fixed degree offset
  renders as a much smaller pixel gap in a wide region than a narrow one,
  since every region's tight-cropped output lands in roughly the same
  pixel width/height regardless of its nominal span (see the "same
  output size" entry below). `full_bc` (roughly 4x a true-zoom region's
  span) had its labels sitting almost against their dots before this;
  `dx_scale`/`dy_scale` (`cfg`'s own `lon_span`/`lat_span` divided by the
  shared `LON_SPAN`/`LAT_SPAN` default) now scale the offset so the
  pixel gap reads the same across every region. `columbia_basin` (no
  span override, `dx_scale`/`dy_scale` both exactly 1) is unaffected.
- **`../maps/land_slim.json` widened for `full_bc`**: that file (shared
  by every other project in this repo too) is Natural Earth's 10m
  physical "land" polygons, hard-clipped to a fixed lon/lat box at some
  point in the past -- `full_bc`'s true (curved) NearsidePerspective
  boundary reaches to about lon -141.8 in its northwest corner, just past
  the original box's -141.0 edge, which showed up as a real, visible
  triangle of blank white "unmapped" space there (not ocean -- actual
  missing land). Fixed by appending one new feature: the same source
  shapefile's land, intersected with only the thin lon [-143, -141]
  sliver the original box was missing, added to the existing file's
  `features` list. The original 8 features are untouched (verified 7 of
  8 reproduce byte-for-byte from the same shapefile + the same original
  clip box; the 8th-closest match was a small Central American island
  apparently dropped by hand during the original curation, unrelated to
  this fix), so every other project reading this file renders exactly as
  before -- the new feature only ever enters frame for a region reaching
  that far northwest, which today is just `full_bc`.
- **Source and access**: GLM's Level 2+ "LCFA" (Lightning Cluster
  Filter Algorithm) product reports one record per detected flash --
  centroid latitude/longitude, radiant energy, and quality flags -- so no
  satellite fixed-grid projection math is needed, unlike ABI imagery.
  NOAA publishes it continuously and publicly on AWS Open Data
  (`s3://noaa-goes18/GLM-L2-LCFA/...`), readable anonymously with no AWS
  account or API key. Files are produced every 20 seconds (~4,320/day);
  `fetch_lightning.py` downloads the ones covering the last 24 hours
  concurrently (I/O-bound, so threads are safe there), then parses them
  sequentially -- the underlying HDF5/netCDF4 library isn't thread-safe,
  so parsing concurrently intermittently corrupts memory.
- **One shared fetch, eight regions**: `fetch_lightning.py`'s bounding box
  covers at least the union of all eight `REGIONS` extents (padded 0.5
  degrees), not just Columbia Basin's, and its east edge intentionally
  goes further still (see `bc_interior`'s Notes entry below) -- widening
  it doesn't add fetch cost, since GLM file listing/download is purely a
  function of the time window (GOES covers the full disk in every file),
  not the bbox. `build_map.py` filters down to each region's own tighter
  extent at render time, same pattern as
  `columbia-basin-alerts-map/fetch_alerts.py` -- so the fetched area and
  the rendered area are two different things by design, and the fetch is
  allowed to be the bigger of the two.
- **Filter flashes to the *actual* displayed extent, not the nominal
  one**: cartopy silently expands `ax.set_extent()`'s requested box to
  match this fixed-aspect axes' pixel shape whenever the two aspect
  ratios don't line up exactly -- true for every region here, not just
  the custom-span ones (`bc_interior`'s nominal 8.87-degree `lon_span`
  actually renders as ~9.95 degrees, about 0.54 degrees wider on each
  side). `build_map.py` calls `ax.get_extent(crs=pc)` right after
  `ax.set_extent()` and filters flashes against *that* box. Filtering
  against the nominal `region_extent()` box instead (the original
  approach) silently drops real, already-fetched flashes right at the
  edges of the visible frame -- this was the actual cause of a "gap"
  reported east of Nordegg that fine-grained data binning couldn't
  explain, since the data was never missing, just wrongly excluded from
  the plot.
- **Satellite choice**: GOES-18 is the current operational GOES-West
  satellite and the one with a clean view of the Pacific Northwest;
  GOES-East (GOES-19) views this domain at a much more oblique angle.
  If NOAA ever promotes a different satellite to the GOES-West slot,
  update `BUCKET` in `fetch_lightning.py`.
- **Quality flags**: `flash_quality_flag` values are kept as-is (not
  filtered) -- GLM's flash product only reports validated detections, and
  the flag mostly marks minor processing caveats (e.g. constituent event
  count/duration exceeding a threshold), not false positives.
- **Recency bands**: flashes are colored by age -- last hour (purple,
  matching the daily-archive map's single flash color), 1-6 hours ago
  (bright pink/red), 6-24 hours ago (orange). Age is derived from each source
  file's scan-start timestamp (20-second resolution), not the per-flash
  time-offset field within it, which is precise enough for hour-scale
  recency buckets. Bands are drawn oldest-first so more recent strikes
  render on top where tracks overlap.
- **Subtitle time zone label**: the subtitle shows each region's local
  time as `HH:MM PT` or `HH:MM PDT`/`PST`. `bc_interior` always labels
  itself `PDT` -- hardcoded, not computed from its zone, since BC no
  longer observes standard time and zoneinfo's `America/Vancouver` rules
  still assume a DST fallback that won't happen. Every other region sits
  on the US side (`America/Los_Angeles`, which still observes standard
  time) and gets a real `PDT`/`PST` computed from that zone, so it'll
  correctly flip to `PST` once winter arrives.
- **Two fixes ported from `columbia-basin-alerts-map/build_map.py`**,
  needed once `pnw`'s much wider extent came into play (invisible at
  Columbia Basin/Portland's tighter zoom):
  - `drop_long_segments()` -- `countries_slim.json`'s US/Canada/Mexico
    border has several segments over-simplified down to a single straight
    run several degrees long, which cuts across the more detailed
    `admin1_boundary_lines.json` line underneath at wide enough zoom.
  - `trim_offshore_segments()` -- Natural Earth's `admin1_boundary_lines.json`
    includes each coastal state's offshore 3-nautical-mile maritime
    boundary as an ordinary admin-1 line.
- **`MAPS_DIR`/`LOGO_PATH` are absolute**, derived from `build_map.py`'s
  own file location via `SCRIPT_DIR`, not the process's cwd at
  invocation -- a relative path here broke under cron (which starts with
  cwd set to the crontab user's home directory) even though it worked
  fine for a manual run after `cd`-ing into the project directory. Same
  bug, same fix, as `columbia-basin-alerts-map/build_map.py`.
- **Basemap raster caching**: land/countries/states/counties/roads are
  the same on every run -- only the flash scatter, city labels, and
  title/subtitle text actually change. Redrawing those static vector
  layers from scratch (tens of thousands of road segments alone) was
  measured at ~45-60s of a ~50-65s total render, so `build_map.py` now
  renders them once per region into a flat PNG raster under
  `basemap_cache/` and `ax.imshow()`s it back on every subsequent run --
  a warm run is ~2.5-3.3s instead of ~45-65s cold. The cache key
  (`_basemap_cache_key()`) hashes the region's own extent/center/roads
  params plus the `(mtime, size)` of every static `../maps/` file the
  static layers read from, so editing a `REGIONS` entry or regenerating
  a shared `maps/` file self-invalidates the cache automatically on the
  next run -- nothing to remember to clear by hand. Deleting
  `basemap_cache/` entirely is always safe; it just costs one slow
  rebuild per region on the next run. Not committed to git, same as the
  rendered output PNGs -- it's regenerable build output, not source.
  One subtlety if touching this code: `GeoAxes` shrinks its own
  displayed pixel box (not just the data extent) to hold `aspect=1`
  between projected data scale and display size, so the cache-build
  figure's raw canvas buffer has that shrink baked in as a blank pixel
  margin -- `_get_basemap_raster()` crops to the cache axes' actual
  post-shrink `get_position()` box before saving, or the saved raster
  carries a double-counted margin when replayed into the real (already
  shrunk) render axes.
- **All regions render at the same output size**: `fig = plt.figure(figsize=(12, 8.3), dpi=200)`
  is fixed regardless of region, but `plt.savefig(..., bbox_inches="tight")`
  crops to actual content, so a region's final pixel width still varies
  with its own aspect ratio (height doesn't vary -- it's pinned by the
  fixed title/subtitle/legend/attribution text). Every region here lands
  in a ~1510-1554px-wide band (at the fixed 1569px height) -- close
  enough not to notice on the site. Adding a new region: render it, check
  its output width lands in that same band, and if not, tune `lon_span`
  (see `puget_sound`/`lower_mainland_victoria`/`full_bc` above for how)
  rather than trusting a span computed by formula alone -- the ground-km/
  `cos(lat)` conversion keeps the real-world aspect ratio correct, which
  isn't quite the same thing as keeping the rendered pixel width
  consistent, especially for a very wide/tall region like `full_bc`.
