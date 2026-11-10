# Wallowa County Geology Map

A styled geologic map of Wallowa County, OR for Ingalls Weather's social
posts. It shows rock units grouped into six legend classes, mapped faults
(black; dashed where approximate or concealed), highways, county lines,
cities, Wallowa Lake, and a red circle at the most recent M3+ earthquake.
The circle is styled and sized the same way as on
[`../wallowa-earthquakes-map/`](../wallowa-earthquakes-map/).

## Files

- `build_geology_layers.py` -- one-time builder. It downloads the USGS
  State Geologic Map Compilation (SGMC) Oregon file, clips the units and
  faults to Wallowa County, tags each unit with a legend group, and writes
  `../maps/wallowa_county_geology.geojson` and
  `../maps/wallowa_county_faults.geojson`. Both are committed, so rerun it
  only for a newer SGMC release or to change the grouping (`GROUPS`).
- `fetch_earthquake.py` -- pulls the earthquake to mark from USGS ComCat
  and writes `earthquake.json`. It defaults to the most recent M3.0+ event
  in and around the county. Pass `--event-id` to choose a specific one.
- `build_map.py` -- renders `wallowa_geology.png` at exactly 2160 x 2700
  px (4:5, Instagram's tallest feed shape; a clean 2x of 1080 x 1350).
- `requirements.txt` / `setup.sh` -- Python + system dependencies.

Smaller highways and Wallowa Lake come from the shared TIGER layers
built by `../wallowa-earthquakes-map/build_basemap_extras.py`.

## Usage

Run from inside this directory:

```bash
bash setup.sh                     # first time / fresh environment only
python3 fetch_earthquake.py       # or: --event-id uw714136981
python3 build_map.py              # render wallowa_geology.png
```

## Notes

- **Source and scale**: for Oregon, SGMC is Walker & MacLeod's
  1:500,000 *Geologic Map of Oregon* (1991). It's right for a
  county-overview graphic, but faults and contacts are generalized. Many
  smaller mapped faults aren't shown, and line positions can be off by
  hundreds of meters. For detailed work, use DOGAMI's larger-scale
  quadrangle maps.
- **Grouping**: SGMC maps 24 units in the county. `GROUPS` in
  `build_geology_layers.py` collapses them into the six legend classes.
  The ages in the legend are approximate, for a general audience.
- **Geology is shaded inside Wallowa County only.** Neighboring
  counties are plain basemap, since each state's SGMC units don't match
  across the Idaho/Washington lines.
- **Faults vs. the earthquake**: the map shows where faults are mapped
  at the surface. It doesn't say which fault, if any, slipped. The
  Nov 9, 2026 M4.3 plots on Grande Ronde Basalt a few miles east of the
  southeast end of the mapped range-front faults near Wallowa Lake. USGS
  hasn't published a focal mechanism for it.
