# Fire History Map

All wildfire burn perimeters from a given year that fall inside a fixed
map domain -- unlike [`../fire-perimeter-map/`](../fire-perimeter-map/)
(one incident, the map centers and zooms on it), this holds the domain
fixed and shows every fire that intersects it, each a different color. A
fire that extends past the frame is simply clipped there, not a bug to
work around -- cartopy does this automatically.

Defaults to the same domain as `fire-perimeter-map`'s Second Street Fire
render (Benton City, WA, 2026 season).

## Files

- `build_map.py` -- fetches every WFIGS year-to-date perimeter
  intersecting the domain, pulls roads/towns for that area live from
  OpenStreetMap (same approach as `fire-perimeter-map`, kept as a
  near-duplicate rather than a shared import -- see its module docstring
  for why), and renders the map. See the module docstring for the full
  data-source/methodology writeup.
- `requirements.txt` / `setup.sh` -- same dependencies as
  `fire-perimeter-map` (cartopy needs GDAL, apt-only; Poppins font for
  labels).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`counties_wa_or_id.geojson` (WA/OR/ID only).

The Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                                    # first time / fresh environment only
python3 build_map.py                             # Benton City, WA, 2026 (default)
python3 build_map.py --year 2025
python3 build_map.py --center-lon -120.5 --center-lat 46.6 --label "Yakima" \
    --zoom-lon-deg 1.0 --zoom-lat-deg 0.5
python3 build_map.py --local-roads               # add unnumbered local roads (narrow gray)
python3 build_map.py --exclude-town Richland
```

Run `python3 build_map.py --help` for the full flag list.

## Data sources and methodology

See the module docstring at the top of `build_map.py` -- it covers the
WFIGS "Interagency Perimeters YearToDate" query (bbox-intersects, not by
name, since the point is finding every fire in the domain), the
year-filter defensive check, and the same Overpass road/town approach
`fire-perimeter-map` uses.
