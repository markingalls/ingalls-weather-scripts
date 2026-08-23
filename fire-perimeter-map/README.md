# Fire Perimeter Map

A zoomed local map of a single wildfire's current NIFC-mapped perimeter --
not a point marker like [`../wildcad-fires-map/`](../wildcad-fires-map/),
the actual mapped burn-area polygon, against county lines, a highway
hierarchy (interstate/main/minor), and nearby towns, at a scale a regional
map can't provide. Defaults to the Colwash Fire (Yakima County, WA), but
every data layer besides the shared county basemap -- fire perimeter,
zoom/extent, roads, towns -- is fetched live and computed from whichever
fire it's pointed at, so it's meant to be reused for other fires, not
edited per fire.

## Files

- `build_map.py` -- fetches one fire's current perimeter from NIFC WFIGS,
  centers the map on it, pulls roads and towns for that area live from
  OpenStreetMap, and renders the map. See its module docstring for the
  full data-source/methodology writeup.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, apt-only). `setup.sh` also installs the Poppins font used
  for map labels, since it isn't packaged for apt.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`counties_wa_or_id.geojson` (WA/OR/ID only -- a fire outside those three
states renders with no county lines, see the module docstring).

The Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                                    # first time / fresh environment only
python3 build_map.py                             # Colwash Fire, WA (default)
python3 build_map.py --fire-name "Some Other Fire" --state OR
```

The default town/road layers are all fetched automatically, but a fresh
run for a new fire will often want a light touch-up pass, the same way
the Colwash map itself was refined over several rounds -- these don't
require editing the script:

```bash
# Drop an auto-picked town, add one OSM doesn't tag as a village/town
# (e.g. a locally-relevant hamlet)
python3 build_map.py --exclude-town Zillah --add-town "Satus,-120.1503,46.2701"

# Widen or narrow the zoom (default is 1.00 x 0.50 degrees, tuned for
# Colwash's elongated footprint -- a more compact fire may want less)
python3 build_map.py --zoom-lon-deg 1.5 --zoom-lat-deg 0.8

# Fewer/more auto-fetched town labels (default cap is 10)
python3 build_map.py --max-towns 6

python3 build_map.py --out output/my_custom_name.png
```

`--exclude-town` and `--add-town` are both repeatable. Run
`python3 build_map.py --help` for the full flag list.

## Data sources and methodology

See the module docstring at the top of `build_map.py` -- it covers the
WFIGS perimeter query, how the extent/figure layout are computed from the
fire's own bounding box at runtime, the Overpass road/town queries (and
why roads no longer read from a static per-state file), and known
limitations (counties only cover WA/OR/ID; an Overpass outage now means
no roads/towns at all, not just no minor-highway tier, since there's no
static fallback file anymore).
