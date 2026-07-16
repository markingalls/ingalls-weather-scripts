# Current Wildfires Map

A one-off map of currently active wildfires across the same domain as
[`../dew-point-storm-map/`](../dew-point-storm-map/) (Prince George BC to
Winnemucca NV, Bella Coola BC to Yellowstone WY), merged from three
government sources since none of them alone covers the whole domain:
WildCAD-E (US dispatch centers), BC Wildfire Service, and Alberta
Wildfire. Markers are sized (log scale, no name labels) by acreage.

## Files

- `build_map.py` -- queries every WildCAD-E dispatch center whose area
  overlaps the map domain plus the BC and Alberta wildfire feature
  services, filters each to active wildfires, merges and dedups them, and
  renders the map. Also saves a `.json` snapshot of the fetched/filtered
  fire list to `output/` each run, so `--file` can re-render without
  re-fetching.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, apt-only). `setup.sh` also installs the Poppins font used
  for map labels, since it isn't packaged for apt.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`land_slim.json`, `states_lakes_slim.json`, `admin0_boundary_lines.json`.

The Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                                    # first time / fresh environment only
python3 build_map.py                             # current active wildfires
python3 build_map.py --lookback-days 45          # widen the WildCAD-E query window
python3 build_map.py --file output/snapshot_....json  # re-render, no fetch
```

## Data sources and methodology

### US -- WildCAD-E

WildCAD-E's public web app (wildwebe.net) is a React SPA that calls
`https://snknmqmon6.execute-api.us-west-2.amazonaws.com/centers/<DC>/incidents?fromDate=...&toDate=...`
for each dispatch center. There's no published API doc -- this was found
by inspecting the app's JS bundle. It's unauthenticated and returns JSON.

- **Longitude sign bug (theirs, worked around here)**: the API returns
  longitude as a bare positive magnitude (e.g. `"120.297895"` for a fire in
  Chelan County, WA, which is actually -120.297895). Every dispatch center
  queried here is west of the prime meridian, so `build_map.py` negates
  longitude unconditionally -- safe for this domain, would need revisiting
  for an eastern-hemisphere or Alaska/Hawaii extension.
- **Which dispatch centers**: every one whose area of responsibility falls
  inside or close to the map domain -- all of WA/OR/ID (each state fits
  entirely inside the domain), western/central Montana, northern Nevada,
  northern Utah, and NW Wyoming (see `DISPATCH_CENTERS` for the full list
  and per-state reasoning). Centers overlapping the domain only partially
  are queried anyway; results get filtered to the exact `LON_MIN`/`MAX`/
  `LAT_MIN`/`MAX` box regardless, so over-including a center costs nothing.
- **"Currently active" is inferred, not an explicit flag.** A fire counts
  if `type == "Wildfire"` (excluding Smoke Check, False Alarm, Debris
  Fire, Vehicle Fire, Structure Fire, Prescribed Fire, etc.) and its
  `fire_status.control` timestamp is null. WildCAD's `out` timestamp
  turns out to be essentially never populated -- even fires
  contained/controlled weeks ago usually still show `"out": null` -- so
  it's useless as an activity filter. `control` (not yet declared
  controlled) is the more reliable signal that suppression is still
  ongoing.
- **`--lookback-days`** (default 30) sets how far back each center is
  queried for incidents -- wide enough to catch a large fire that started
  weeks into the season and is still uncontrolled, without querying each
  center's entire multi-year history every run.

### British Columbia -- BC Wildfire Service

Found via its ArcGIS Hub listing ("Fire Locations - Current"):
`https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/BCWS_ActiveFires_PublicView/FeatureServer/0`.
Every fire this season is a point in this layer, active or not, each with
an explicit `FIRE_STATUS` (`Out`, `Out of Control`, `Being Held`, `Under
Control`, `Fire of Note`). "Currently active" here means `FIRE_STATUS !=
"Out"` -- a looser definition than WildCAD's "not yet controlled", because
BC's status model doesn't map cleanly onto WildCAD's and BC's own `Out` is
a clean, explicit signal that WildCAD's field of the same name isn't. Size
(`CURRENT_SIZE`) is in hectares, converted to acres (`x2.47105`) for a
consistent legend with the US side.

### Alberta -- Alberta Wildfire

Found via the public Experience Builder wildfire-status app's embedded
data sources ("wildfire_location_active"):
`https://services.arcgis.com/Eb8P5h4CJk8utIBz/arcgis/rest/services/wildfire_location_active/FeatureServer/0`.
This layer is already curated to active fires only (its name says so, and
querying it shows no `Out`-equivalent status among its handful of current
records), so no extra activity filtering is applied. Size
(`AREA_ESTIMATE`) is in hectares, converted the same way as BC's. It also
exposes no true ignition/discovery date field -- `FIRE_STATUS_DATE` (last
status change) is used as the age proxy instead (see "Age coloring"
below), a known imperfection.

### Merging

All three sources are fetched into one dict keyed by a source-prefixed ID
(`WC:<inc_num>`, `BC:<fire_id>`, `AB:<fire_number>`) so they can't collide
with each other, then flattened and sorted by acreage.

### Rendering

- **Marker sizing**: area (not radius) scales log-scale with acres, since
  fire size spans several orders of magnitude (0.1 to 10,000+ acres) in
  the combined dataset -- `marker_size_pts2()`.
- **Age coloring**: red if a fire was first reported within
  `NEW_FIRE_HOURS` (24 by default), orange otherwise -- including any fire
  whose age can't be determined, a safer default than implying "new" on
  missing data (in practice this never happens: every source currently
  supplies *some* date field). Each source's notion of "first reported"
  differs in reliability:
  - WildCAD: the incident's initial-report timestamp. It's naive (no UTC
    offset) and dispatch centers log in local time, not UTC -- treated as
    UTC here, so up to ~7 hours off depending on the center's time zone.
  - BC: `IGNITION_DATE`, a real Esri epoch-ms field -- exact.
  - Alberta: no true ignition field exists in the public service, so
    `FIRE_STATUS_DATE` (last status change) stands in. For a genuinely new
    fire this is usually close to its actual start (the first status is
    set on initial report); for an old fire that just had a status
    change, it can understate age and wrongly read as "new."
- **No name labels.** With 300+ active fires typically on the map at once,
  no label-density threshold reads as anything but clutter -- size/color
  plus the legends carry the useful signal instead.
- **Ocean** is shaded a flat pastel blue (`ax.patch`, since land geometries
  are drawn on top and don't cover water) rather than left the neutral
  basemap tone the rest of this repo's scripts use, since there's no
  temperature/index raster here competing for attention underneath it.
