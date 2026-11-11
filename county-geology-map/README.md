# County Geology Map

A reusable, Instagram-ready (4:5, 2160 x 2700 px) geologic map for any
Washington or Oregon county. It shows rock units, faults, anticlines and
synclines, highways, county lines, nearby lakes and rivers, and
incorporated cities. Colors come from the shared table, so a rock class
looks the same in every county and state. `run_all.py` renders the
whole series: all 39 Washington and 36 Oregon counties.

| State | Geology source | Crosswalk to shared colors |
|---|---|---|
| WA | Washington DNR 1:100,000 statewide map (live service), patched from DNR 1:250,000 where the 100k data is defective | [`../maps/geology_wadnr.py`](../maps/geology_wadnr.py) |
| OR | DOGAMI Oregon Geologic Data Compilation, release 7 (OGDC-7) geodatabase, ~100 MB, downloaded once and cached | [`../maps/geology_ogdc.py`](../maps/geology_ogdc.py) |

## Files

- `fetch_geology.py --state WA|OR --county NAME` -- fetches what the map
  needs for one county into `data/` (not tracked):
  - map units, clipped to the county and tagged with a shared color class
  - faults, plus anticlines and synclines (monoclines are left out)
  - Census TIGER lakes, reservoirs and river reaches of 1.5 km² or more
    around the county, for context
  - highways in three classes. Census TIGER covers every state; its
    "primary road" class (MTFCC S1100: limited access, with interchanges)
    is the freeway class, so non-Interstate freeways (SR 520, SR 167, the
    Bend Parkway, OR 22 at Salem) count. Where the repo's OpenStreetMap
    extract (`../maps/*_roads.geojson`; Columbia Basin and I-5 corridor
    only) has data, it decides instead: TIGER freeway stretches that OSM
    maps as trunk are demoted to major highway, and OSM motorways TIGER
    missed are added. Major highway = US routes; the rest = state highway.
  - TIGER incorporated places in and around the county for city labels
  - full-resolution TIGER county boundaries for WA, OR, ID, CA and NV (the
    county outline, neighboring county lines, and state lines)

  Big downloads (the ~84 MB national TIGER county file and OGDC-7) are
  cached in `data/_cache/` after the first run.
- `build_map.py --state WA|OR --county NAME` -- renders
  `<state>_<county>_geology.png`, titled "<County> Co., <State> Geologic
  Map". Pass `--also-label "Moses Lake"` (repeatable) to label a city
  outside the county that falls on the map. Pass `--no-detail` to draw
  detail classes (Columbia River Basalt formations, loess, flood deposits)
  in their parent class's color.
- `run_all.py` -- batch-renders every county (or `--only "OR:Clatsop"
  "WA:King"`) into `series/Washington/` and `series/Oregon/`, then writes
  `series/contact_sheet.jpg`, `series/run_log.txt` and a zip with one
  folder per state. Each county runs in its own subprocess, so a failure is
  logged and the batch keeps going.
- `requirements.txt` / `setup.sh` -- Python + system dependencies.

## Usage

Run from inside this directory:

```bash
bash setup.sh                                         # first time / fresh environment only
python3 fetch_geology.py --state WA --county Adams
python3 build_map.py --state WA --county Adams --also-label "Moses Lake"
python3 fetch_geology.py --state OR --county Baker
python3 build_map.py --state OR --county Baker
python3 run_all.py                                    # the whole series (~1.5 h)
```

## Notes

- **Washington source**: [Washington DNR 1:100,000 surface geology (GeMS)](https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/100K_Surface_Geology_WA_GeMS/FeatureServer),
  queried live: no key, and every feature in the county is fetched by
  object id. This is far more detailed than the USGS SGMC compilation
  for Washington, which lumps the whole Columbia River Basalt Group into
  one unit.
- **Oregon source**: [DOGAMI OGDC-7](https://pubs.oregon.gov/dogami/dds/p-OGDC-7.htm)
  compiles the best available published mapping statewide, so detail
  varies by area. In Baker County, a few mining districts were mapped in
  much more detail, so their faults show up as dense clusters. Every
  polygon has standardized statewide "thematic" fields (rock type, age,
  terrane, formation), which the crosswalk reads. It classifies every
  distinct OGDC-7 unit except one with no data. Faults are the
  non-contact lines in `ContactsAndFaults`. Folds come from
  `GeologicLines`, with minor folds left out.
- **Colors** come from the shared table in
  [`../maps/geology_classes.json`](../maps/geology_classes.json). DNR
  units are sorted into it by
  [`../maps/geology_wadnr.py`](../maps/geology_wadnr.py), which reads
  DNR's map-unit symbol scheme (age prefix + lithology letters) and unit
  names. It classifies all but 3 of about 1,850 DNR units statewide. An
  unknown unit stops the fetch with an error rather than getting a wrong
  color, so a new county either just works or tells you which rule to
  add. Oregon maps use the same table via
  [`../maps/geology_sgmc.py`](../maps/geology_sgmc.py).
- **Defects in DNR's 1:100,000 data**: a few published 100k polygons are
  corrupted. Around Clarkston and Asotin, for example, they show as
  fan-shaped wedges converging on one point, and DNR's own map service
  draws them the same way. `fetch_geology.py` finds straight segments
  longer than 5 km that don't run along the state or national line (real
  1:100k contacts never run that straight). It fills only the hull those
  segments span, plus 500 m, from DNR's 1:250,000 map. The corrupted
  polygons themselves can be huge (the Asotin fans belong to basalt
  polygons reaching into Garfield and Columbia counties), so whole-polygon
  replacement would swap out lots of clean data. If the patch would cover
  more than 15% of a county, it uses 1:250,000 county-wide instead, so
  there are no seams; Asotin County needs this. The credit line says
  which scale(s) were used.
- **Layout**: the legend is built first. The map then takes the rest of
  the 4:5 canvas, and its extent is stretched around the county to fill
  that box. Wide counties like Adams get extra context north and south,
  tall ones east and west.
- **Folds** are drawn in purple, with the standard symbol at each
  segment's midpoint: arrows pointing away from the axis for an
  anticline, toward it for a syncline. They're dashed where DNR marks
  them concealed.
- **Shoreline and water**: the map background is water. Land is Natural
  Earth (for Canada) plus the TIGER counties, with TIGER water (ocean
  within 3 nmi, Puget Sound, estuaries, big rivers and lakes) drawn on
  top. Each county's geology is clipped to its land (the legal TIGER
  county runs 3 nmi offshore and to mid-river). The black outline follows
  the shoreline along edge water: the ocean, the Sound, border rivers
  (water bodies with at least 20% of their perimeter on the county line).
  Interior rivers and lakes stay inside the outline.
- **Polygon cleanup**: rounding coordinates, and some zero-area DNR
  slivers, produce polygons that cartopy fills as the whole map. King and
  Okanogan counties came out solid blue before this fix. `clean_polygon`
  in `fetch_geology.py` fixes validity and drops slivers, both when data
  is written and when it's drawn.
- **Legend** is centered under the map. `build_map.py` tries layouts from
  roomiest to most compact (smaller font, more columns) until the map gets
  at least 56% of the canvas height, so counties with many rock classes
  get a smaller legend while the image stays exactly 4:5.
- **Boundaries**: the repo's shared `../maps/counties_wa_or_id.geojson`
  is simplified and cuts corners along rivers at county scale. These maps
  instead clip geology to, and outline, the full-resolution TIGER county,
  so the line follows the Snake and Palouse rivers.
- **City labels**: incorporated places in the county, largest by land area
  first (up to 18), then up to 4 nearby cities outside it with at least
  15 km² of land, plus any `--also-label`. Each label tries right, left,
  above and below its dot, and is dropped if it would overlap another
  label, a dot, the logo corner or the frame. Unincorporated towns
  (Imnaha, Greenhorn's neighbors...) aren't in the Census list, so they
  aren't labeled.
