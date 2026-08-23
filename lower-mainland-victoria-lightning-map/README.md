# Lower Mainland / Victoria Lightning Map (One-Off)

A one-off styled map zoomed to Whistler (N), Hope (E), Port Renfrew (W),
and Everett (S) -- covering Metro Vancouver, the Fraser Valley, southern
Vancouver Island, and the northwest Puget Sound corridor: GLM (Geostationary
Lightning Mapper) flash detections for a single full calendar day (Pacific
time), sourced from GOES-18, for Ingalls Weather's Instagram.

Unlike [`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/)
(a rolling 24-hour lookback ending "now"), this pulls one specific calendar
day in the past -- built for "yesterday's lightning," not a live snapshot,
so it follows the single-color styling of the canonical
`columbia-basin-lightning-daily-map/` (on the `digitalocean` deploy branch)
rather than the age-banded style of the rolling-lookback lightning maps.

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections for one full
  Pacific-time calendar day out of NOAA's public `noaa-goes18` bucket on
  AWS Open Data and writes `output/lightning_<date>.json`. Defaults to
  yesterday.
- `build_map.py` -- renders the map from `output/lightning_<date>.json`
  plus the static basemap files in `../maps/` and this project's own
  `coastline_10m.geojson`. Writes
  `output/lower_mainland_victoria_lightning_<date>.png`.
- `coastline_10m.geojson` -- full-resolution Natural Earth 10m land +
  minor islands, clipped to this domain (see Notes below).
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip; the Poppins
  font used for map labels isn't packaged for apt either).

Shared basemap data lives one level up in [`../maps/`](../maps/), including
`bc_roads.geojson` (this project's own addition -- see Notes). The
Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                            # first time / fresh environment only
python3 fetch_lightning.py               # pull yesterday's flashes (Pacific time)
python3 fetch_lightning.py --date 2026-08-22   # ... for a specific date
python3 build_map.py                     # render yesterday's map
python3 build_map.py --date 2026-08-22   # ... for a specific date
```

## Notes

- **Source and access**: same GLM-L2-LCFA product and AWS Open Data access
  pattern as `../columbia-basin-lightning-map/` -- see that project's
  README for background on the flash product and file layout. This
  script's only difference is that it fetches one fixed Pacific-time
  calendar day (00:00-24:00) instead of a rolling 24-hour window ending
  now.
- **Domain**: bounding box is the exact Whistler/Hope/Port Renfrew/Everett
  extremes, padded 0.5 degrees for the flash fetch (so strikes right at
  the map edge aren't dropped pre-plot) and 0.2 degrees for the rendered
  map extent.
- **Projection**: PlateCarree, not the `NearsidePerspective` used by the
  other lightning/temperature maps in this repo -- at this domain's
  tighter, more elongated shape, `NearsidePerspective`'s curved projected
  rectangle left visible blank corners; see the same tradeoff noted in
  `../dew-point-storm-map/build_map.py`.
- **Single flash color**: a full archived day has no meaningful "how
  recent" axis the way a live nowcast does, so flashes are all plotted in
  one color (`#8B2FC9`, matching `columbia-basin-lightning-daily-map/`'s
  `FLASH_COLOR`, the canonical daily-archive lightning style posted to
  the website) rather than the age bands the rolling-lookback lightning
  maps use.
- **Coastline resolution**: `../maps/land_slim.json` is simplified for
  continental-scale maps and reads visibly blocky at this domain's tight
  zoom (Gulf Islands, Howe Sound, the Fraser River mouth). `build_map.py`
  instead uses `coastline_10m.geojson`, a one-time pull of full-resolution
  Natural Earth 10m `ne_10m_land` + `ne_10m_minor_islands` (from
  `raw.githubusercontent.com/martynafford/natural-earth-geojson`), clipped
  to a padded box around this domain and checked in locally rather than
  fetched at build time. The US/Canada border uses `../maps/
  admin0_boundary_lines.json` (a dedicated boundary-line layer, not
  `countries_slim.json`'s simplified polygon edges) for the same reason --
  see `../dew-point-storm-map/build_map.py` for the same choice.
- **BC roads**: `../maps/` had motorway/trunk road data for WA/OR/ID only,
  not British Columbia. `../maps/bc_roads.geojson` fills that in -- OSM
  motorway/trunk/motorway_link/trunk_link ways pulled from a public
  Overpass API mirror for this domain's bounding box, clipped to the
  Canadian side (via `../maps/countries_slim.json`'s Canada polygon) so it
  doesn't duplicate roads already covered by `washington_roads.geojson`,
  in the same `{"highway": <tag>}`/`LineString` schema as the existing
  per-state road files so `build_map.py` can style it identically.
  `../maps/washington_roads.geojson` itself was also refreshed from the
  `digitalocean` deploy branch's newer pull (33k features vs. the old 18k)
  -- the old file had zero coverage on the Olympic Peninsula (nothing west
  of about -124.2), which cut off US-101 well east of Port Angeles; the
  refreshed file's `trunk`-tagged coverage runs the full width of this
  domain.
- **No admin1 (state/province) boundary layer**: the only state/province
  line this domain touches is WA's own northern edge, which *is* the
  international border already drawn from `admin0_boundary_lines.json` --
  Natural Earth's admin1 lines don't flag "this segment is shared with an
  admin0 border," so adding that layer back drew a visible double line
  right along the border. Skipped entirely rather than filtered, since it
  contributes nothing else within this domain.
- **City labels**: side (`"left"`/`"right"`) controls which side of the
  dot the label sits on; `LABEL_DX` controls the gap. Both are manually
  tuned per city to avoid overlaps in this label-dense metro area -- no
  automatic collision avoidance.
