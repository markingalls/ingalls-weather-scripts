# Largest Recorded Earthquake by County (WA / OR / ID)

A one-off styled map of every Washington, Oregon, and Idaho county, shaded
by the magnitude of the largest earthquake whose epicenter falls inside it
in the USGS ANSS Comprehensive Catalog (ComCat). Each county is labeled
with that magnitude, the top 8 events get a star at their epicenter, and a
box in the upper right lists them.

## Files

- `build_map.py` -- queries the USGS FDSN event service, assigns each event
  to a county by point-in-polygon, and renders the map. Also saves a
  `.json` snapshot of the per-county maxima to `output/` each run, so
  `--file` can re-render without re-fetching.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, apt-only). `setup.sh` also installs the Poppins font.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`counties_wa_or_id.geojson`, `land_slim.json`, `states_lakes_slim.json`,
`admin1_boundary_lines.json`, `admin0_boundary_lines.json`. The logo
(bottom-right) is [`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                                          # first time / fresh environment only
python3 build_map.py                                   # fetch live + render
python3 build_map.py --file output/snapshot_2026-11-10.json   # re-render, no fetch
```

## Data source and methodology

`https://earthquake.usgs.gov/fdsnws/event/1/query` (GeoJSON,
unauthenticated), always with `eventtype=earthquake` (drops quarry blasts,
explosions, etc.) and `orderby=magnitude`, so the first event that lands
in a county is that county's maximum.

- **Pass 1**: every M2.5+ event in a box around the three states, all of
  ComCat's history (~11.8k events, under the service's 20,000-per-request
  cap). Covers ~104 of 119 counties.
- **Pass 2**: for each county pass 1 left empty, query that county's own
  bounding box with no magnitude floor, largest first (paging if the box
  overlaps busier neighbors), and take the first event actually inside the
  polygon.
- Counties with nothing even after pass 2 are drawn in gray ("None in
  catalog"). As of Nov 2026 that's 9 counties: Ada, Twin Falls, Jerome,
  Gooding, Minidoka, Jefferson, Madison, and Payette in Idaho, plus Asotin,
  WA. This was double-checked against ComCat directly, padding each
  county's box 0.3 deg and dropping the `eventtype` filter. There really
  are zero cataloged events inside those polygons, even though nearby
  counties have plenty. Two reasons: most of them sit on the Snake River
  Plain, a well-known seismically quiet zone ringed by the active "seismic
  parabola" around it, and southern Idaho has sparse seismic network
  coverage, so small quakes there mostly never make it into ComCat.

### Caveats

- **Epicenter, not shaking.** A county is credited only with quakes
  centered inside it. Counties next to a big event (e.g. King and Thurston
  around Nisqually) felt much more than their own number shows.
- **Historic events have rough locations and magnitudes.** Pre-instrumental
  events (the 1872 Lake Chelan quake, the 1873 event USGS places at
  42.0N 124.2W on the OR/CA line and credits here to Curry Co.) come from
  felt reports, so their epicenters can be tens of km off and their
  magnitudes are estimates. Curry's M6.9 in particular is an epicenter
  sitting right on the state line.
- **Mixed magnitude types.** ComCat mixes Mw, ML, Md, mb, etc. The map
  uses each event's preferred magnitude as published.
- **Offshore events don't count.** Cascadia subduction-zone and Blanco
  Fracture Zone quakes fall outside every county polygon.

### Rendering

- Whole-magnitude color bins (each step is ~32x the energy), with the top
  bin split at 6.5 so the major events stand apart from the M6.0s.
- Same NearsidePerspective look and basemap colors as
  `../columbia-basin-alerts-map/`. The extent is padded into the Pacific
  to fit the legend clear of SW Oregon, and into WY/MT to fit the logo
  clear of SE Idaho.
- Magnitude labels sit at each county's pole of inaccessibility (the
  point farthest from any edge, via `shapely.ops.polylabel`) rather than
  `representative_point()`, which often hugged one edge (e.g. Walla
  Walla). A label is nudged up 9pt only when its county's star would
  otherwise sit on it.
