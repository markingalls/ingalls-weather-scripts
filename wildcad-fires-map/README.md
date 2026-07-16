# Current Wildfires (WildCAD-E) Map

A one-off map of currently active wildfires across the same domain as
[`../dew-point-storm-map/`](../dew-point-storm-map/) (Prince George BC to
Winnemucca NV, Bella Coola BC to Yellowstone WY), sourced from WildCAD-E --
the interagency dispatch CAD system used by nearly every US wildland fire
dispatch center. Markers are sized (log scale) by acreage, with the
largest fires labeled by name.

**BC/Alberta are not covered.** WildCAD is a US-only system; British
Columbia and Alberta run their own separate systems (BC Wildfire Service,
Alberta Wildfire). Any fires currently burning in the Canadian part of the
domain simply won't appear -- this is a real gap in the underlying data,
not a bug, and the map's subtitle says so.

## Files

- `build_map.py` -- queries every WildCAD-E dispatch center whose area
  overlaps the map domain, filters to active wildfires, and renders the
  map. Also saves a `.json` snapshot of the fetched/filtered fire list to
  `output/` each run, so `--file` can re-render without re-fetching.
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
python3 build_map.py --lookback-days 45          # widen the incident query window
python3 build_map.py --file output/snapshot_....json  # re-render, no fetch
```

## Data source and methodology

- **API**: WildCAD-E's public web app (wildwebe.net) is a React SPA that
  calls `https://snknmqmon6.execute-api.us-west-2.amazonaws.com/centers/<DC>/incidents?fromDate=...&toDate=...`
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
- **Dedup**: incidents are merged into one dict keyed by `inc_num` (falling
  back to `uuid`), since a fire near a shared dispatch boundary can
  legitimately appear in more than one center's feed.
- **`--lookback-days`** (default 30) sets how far back each center is
  queried for incidents -- wide enough to catch a large fire that started
  weeks into the season and is still uncontrolled, without querying each
  center's entire multi-year history every run.
- **Marker sizing**: area (not radius) scales log-scale with acres, since
  fire size spans several orders of magnitude (0.1 to 10,000+ acres) in
  the same dataset -- `marker_size_pts2()`.
- **Labeling**: only fires at/above `LABEL_MIN_ACRES` (1,000 by default)
  get a name+acreage label, and a greedy declutter pass
  (`LABEL_MIN_SEPARATION_DEG`) skips labeling a fire that's too close to
  an already-labeled one, capped at `LABEL_MAX_COUNT` regardless -- a
  fire season with dozens of large, tightly-clustered fires (this domain,
  as of writing) would otherwise turn the map into text soup. A fire
  sitting almost exactly on top of a city (it happens) can still visually
  collide with that city's label; this isn't corrected for.
