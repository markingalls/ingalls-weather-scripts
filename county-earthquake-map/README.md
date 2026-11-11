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
- **Idaho Geological Survey supplement** (`SUPPLEMENTAL_EVENTS`): three
  instrumental events from IGS's *Catalog of Idaho Earthquakes, 1872-1993*
  ([IC-56](https://idahogeology.org/product/I-56)), recorded by regional
  networks that never fed ComCat, are merged in at render time. Each one
  replaces a county's value only if it's larger, and the saved snapshot
  stays pure ComCat. IGS is credited in the map's attribution line; the
  labels themselves aren't marked:
  - Canyon, M3.6, 1989-05-30, 20 km WNW of Caldwell (Montana Bureau of
    Mines network). ComCat's max there is M2.2.
  - Jefferson, M2.3, 1989-10-10 (Bureau of Reclamation Teton network).
  - Madison, M1.6, 1991-08-20 (INEL network).

  Left out on purpose: IGS places the 1916-05-13 M5.3 at Boise (Ada Co.),
  but ComCat has the same event at 44.2N 116.5W (Washington Co.), and the
  ComCat location is kept. Intensity-only felt reports with no magnitude
  (Gooding and Twin Falls, 1932) are also left out.
- Counties with nothing in either source are drawn in gray ("None in
  catalog"). As of Nov 2026 that's 7 counties: Ada, Twin Falls, Jerome,
  Gooding, Minidoka, and Payette in Idaho, plus Asotin, WA. PNSN's own
  catalog was also checked for these: its only hits inside them are
  events flagged as probable blasts. This was double-checked against ComCat directly, padding each
  county's box 0.3 deg and dropping the `eventtype` filter. There really
  are zero cataloged events inside those polygons, even though nearby
  counties have plenty. Two reasons: most of them are on or beside the Snake River
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
  magnitudes are estimates. Curry's M6.9 (1873-11-23) in particular: ComCat's
  preferred origin (California Division of Mines and Geology) is 42.0N
  124.2W, about 0.4 km north of the OR/CA line, rounded to a tenth of a
  degree and inferred from damage reports. The heaviest damage was in
  California's Smith River valley and at Crescent City (MMI VIII). USGS's
  other origin for the same event (Stover & Coffman) is 42.0N 124.0W,
  ML 6.7, which also falls in Curry. So it's "in Curry" only within
  location uncertainty, and could as easily have been centered in Del
  Norte Co., CA.
- **Mixed magnitude types.** ComCat mixes Mw, ML, Md, mb, etc. The map
  uses each event's preferred magnitude as published.
- **Offshore events don't count.** Cascadia subduction-zone and Blanco
  Fracture Zone quakes fall outside every county polygon.

### Rendering

- Half-magnitude color bins, 11 in all from "Under 2.0" to "6.5+", on one
  cream-to-maroon ramp. Label text flips to white from M5.0 up. All bins
  always show in the legend. Classification uses
  the magnitude rounded to one decimal, so e.g. Walla Walla's 5.99 (shown
  as "6.0") is colored as 6.0+.
- The attribution line credits both sources and notes that positions of
  older (pre-instrumental) earthquakes are approximate.
- State lines are clipped to land, which drops the coastal states'
  offshore state-waters boundaries (along the coast and through the
  Strait/Puget Sound). The US/Canada border is drawn unclipped.
- The top-events card lists each event with a magnitude chip in its class
  color, the county, and the event's name/year. An event is named only if
  it has its own English Wikipedia article, using that article's name
  (`WIKIPEDIA_NAMES`, checked Nov 2026): Borah Peak (1983), Nisqually
  (2001), North Cascades (1872), Klamath Falls (1993), State Line (1936).
  The 1873 Curry Co., 1975 Oneida Co. and 1999 Grays Harbor Co. events
  have no article, so they show only the year. It's sized to stay clear
  of the Idaho panhandle.
- Same NearsidePerspective look and basemap colors as
  `../columbia-basin-alerts-map/`. The extent is padded into the Pacific
  to fit the legend clear of SW Oregon, and into WY/MT to fit the logo
  clear of SE Idaho.
- Magnitude labels sit at each county's pole of inaccessibility (the
  point farthest from any edge, via `shapely.ops.polylabel`) rather than
  `representative_point()`, which often hugged one edge (e.g. Walla
  Walla). A label is nudged up 9pt only when its county's star would
  otherwise sit on it.
