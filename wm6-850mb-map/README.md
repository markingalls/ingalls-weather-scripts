# WM-6 Ensemble Mean 850 mb Heights & Temperature Map

One-off styled map of 850 mb temperature (shaded) and geopotential height
(contoured) over the Pacific Northwest for a single valid time, from
WindBorne's WeatherMesh-6 global ensemble mean, with "L" markers at closed
850 mb height lows. The domain (`LON_MIN`..`LAT_MAX`) runs a bit wider than
[`../dew-point-storm-map/`](../dew-point-storm-map/)'s BC/WA/OR/ID frame so
offshore lows and the northern Rockies side of the pattern stay in view.
Rendered under Lambert Conformal Conic, same as
[`../tpw-wm6-ensemble-map/`](../tpw-wm6-ensemble-map/).

- **Temperature shading** uses Ingalls Weather's standard temperature color
  table -- the same fixed Kelvin-to-RGB curve as
  [`../columbia-basin-temps/`](../columbia-basin-temps/), copied verbatim,
  so a given color means the same absolute temperature on both maps. The
  colorbar shows only the slice of the table visible on the map (rounded
  out to 5 °C), Celsius on the bottom (the upper-air convention) with
  Fahrenheit mirrored on top.
- **Height contours** every 30 m (3 dam, the standard 850 mb interval),
  labeled in dam, drawn black so they stay legible over the table's dark
  cold end. Labels come from a second, invisible contour pass over just the
  visible box: `clabel()` on the padded full grid often put a contour's only
  label out in the off-screen padding.
- **Lows** come from `find_height_lows()`: the same sliding-minimum +
  prominence filter as the TPW map's `find_pressure_extrema()` (a center has
  to sit at least one contour interval below its wider surroundings), plus
  a dedupe step. WM-6's quantized output can leave several separate cells
  tied at a low's exact minimum, which drew three stacked "L"s on one low
  before that step was added. Each "L" carries its central height in dam.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
export WB_API_KEY=...
python build_map.py                 # tomorrow, 12:00 PM Pacific
python build_map.py --date 2026-10-30 --hour 5
python build_map.py --file output/snapshot_2026-10-30_12.npz  # re-render without re-fetching
```

`--date` is local (Pacific) time, default tomorrow. `--hour` is the local
target hour (0-23), default 12. WM-6 publishes 3-hourly steps, so the map
is titled off the step that actually comes back (both local and UTC valid
times are shown).

## Data source

WindBorne WeatherMesh-6 (global, 0.25 deg), ensemble mean of
`temperature_850` (K) and `geopotential_850` (m²/s², divided by g for
geopotential height in m), via the WindBorne gridded forecast API
(`WB_API_KEY` required). Fetched exactly like the TPW map: the archived
run's full per-hour zarr zip is opened via presigned URL and only the
needed arrays are range-requested with `remotezip` (a few MB, not ~2 GB).
See [`../tpw-wm6-ensemble-map/README.md`](../tpw-wm6-ensemble-map/README.md)
for the details. This domain doesn't come near the antimeridian, so that
map's unwrapped crop and split `imshow` workarounds aren't needed here.

## Files

- `build_map.py` -- fetches the grids and renders the map. Domain, contour
  interval, and color table are defined near the top.
- `requirements.txt` / `setup.sh` -- same dependencies as the TPW map.

Output PNG (and, unless rendering from `--file`, a `.npz` snapshot of the
fetched grid) lands in `output/`.
