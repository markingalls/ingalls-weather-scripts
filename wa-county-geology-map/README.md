# Washington County Geology Map

A reusable, Instagram-ready (4:5, 2160 x 2700 px) geologic map for any
Washington county. It shows rock units, faults, anticlines and synclines, highways, county
lines, nearby lakes and rivers, and incorporated cities. The geology comes
from Washington DNR's statewide 1:100,000 geologic map. First used for Adams County.

## Files

- `fetch_geology.py --county NAME` -- fetches what the map needs for one
  county into `data/` (not tracked):
  - DNR 1:100,000 map units, clipped to the county and tagged with a
    shared color class
  - DNR faults, plus anticlines and synclines (monoclines are left out)
  - Census TIGER lakes, reservoirs and river reaches of 1.5 km² or more
    around the county, for context
  - Census TIGER US/state highways for the smaller-highway layer
  - TIGER incorporated places in and around the county for city labels
- `build_map.py --county NAME` -- renders `<county>_geology.png`. The title reads "<County> Co., Washington
  Geologic Map". Pass `--also-label "Moses Lake"` (repeatable) to label
  a city outside the county that falls on the map. Pass
  `--no-detail` to draw detail classes (Columbia River Basalt formations,
  loess, flood deposits) in their parent class's color.
- `requirements.txt` / `setup.sh` -- Python + system dependencies.

## Usage

Run from inside this directory:

```bash
bash setup.sh                              # first time / fresh environment only
python3 fetch_geology.py --county Adams
python3 build_map.py --county Adams --also-label "Moses Lake"   # -> adams_geology.png
```

## Notes

- **Source**: [Washington DNR 1:100,000 surface geology (GeMS)](https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/100K_Surface_Geology_WA_GeMS/FeatureServer),
  queried live: no key, and every feature in the county is fetched by
  object id. This is far more detailed than the USGS SGMC compilation
  for Washington, which lumps the whole Columbia River Basalt Group into
  one unit.
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
- **Layout**: the legend is built first. The map then takes the rest of
  the 4:5 canvas, and its extent is stretched around the county to fill
  that box. Wide counties like Adams get extra context north and south,
  tall ones east and west.
- **Folds** are drawn in purple, with the standard symbol at each
  segment's midpoint: arrows pointing away from the axis for an
  anticline, toward it for a syncline. They're dashed where DNR marks
  them concealed.
- **City labels** are TIGER incorporated places and always sit to the
  right of the dot. Label collisions aren't handled; fine for rural
  counties, but check dense ones.
