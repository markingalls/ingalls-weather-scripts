# Pacific Northwest MSLP + 3-Hour Precip Map

One-off styled map of MSLP isobars and 3-hour precipitation for a single
valid time, from WindBorne's WeatherMesh-6 global model. The domain matches
[`../dew-point-storm-map/`](../dew-point-storm-map/): Prince George BC (N),
Bella Coola BC (W), Winnemucca NV (S), Yellowstone WY (E). Precip is drawn
on a ~3 km terrain grid. Where that terrain sits at or above the model's
freezing level, it gets a snow color table (ice blue to violet) in place
of the rain one (green, yellow, red). So a frontal band crossing the Coast
Mountains or Cascades shows snow on the ridges and rain in the valleys and
fjords, at terrain resolution rather than the model's ~28 km.

The basemap is the same terrain, hillshaded over the pastel land fill from
`../tpw-wm6-ensemble-map/`. The precip shading fades in from fully
transparent at 0.01" to nearly opaque by 0.05", and the hillshade
multiplies through it at reduced strength. Its strength eases along with
that fade. A hard switch at the 0.01" floor drew a visible brightness step
across flat terrain.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
export WB_API_KEY=...
python build_map.py                                   # tomorrow, 12z
python build_map.py --valid 2026-10-25T06             # deterministic (default)
python build_map.py --valid 2026-10-25T06 --product mean   # ensemble mean
python build_map.py --file output/snapshot_det_2026-10-25T06.npz  # re-render without re-fetching
```

`--valid` is in UTC, `YYYY-MM-DDTHH`, and must be a multiple of 3 hours
(WM-6 publishes 3-hourly steps). The title shows the local (Pacific) time.
The precip is the 3 hours ending at the valid time.

### Deterministic vs. ensemble mean

`--product det` is the default. Averaging the ensemble's bands, each in a
different place, smears 3-hour precip into a broad, light field. On the
2026-10-25 06z test case the mean peaked at 0.14" and the deterministic
run at 1.9". That washes out the terrain-driven rain/snow split this map
is built to show. `--product mean` is still there, and it's the better
central estimate at long leads.

## Freezing level

WM-6 has no freezing-level field, so `compute_freezing_level()` derives one
per grid column from the chosen product's temperature and geopotential on
17 pressure levels (1000 to 300 hPa). It takes the *highest* 0 °C crossing,
interpolated linearly between the bracketing levels. That's the same
definition as GFS's `HGT:0C isotherm`, and it means a shallow surface cold
pool under a warm layer doesn't pull the freezing level down to the valley
floor. A column that's subfreezing top to bottom counts as snow everywhere.
The freezing level is interpolated bilinearly onto the terrain grid and
compared against terrain height directly. Ocean cells compare at sea
level, not their bathymetric depth.

This is the freezing level, not a snow level. Snow usually reaches about
1,000 ft below it, so the snow shading errs low (if anything, too little
snow). It's also a pure terrain-vs-temperature split, with no surface
p-type: WM-6's `p_type` field sits at the model's own ~28 km terrain, which
would defeat the point of the 3 km grid.

## Data sources

- **WindBorne WeatherMesh-6** (global, 0.25°): `total_precipitation_3h`
  (already in mm per the array's zarr `units` attribute, not meters as
  ERA5/IFS store it), `pressure_msl`, and `temperature_*`/`geopotential_*`
  at each level. Fetched with the same presigned-URL + `remotezip`
  range-request approach as `../tpw-wm6-ensemble-map/` (see that README),
  pulling 36 arrays out of the ~2 GB per-hour file. `WB_API_KEY` is
  required.
- **NOAA NCEI ETOPO 2022** (60 arc-second surface elevation), via NCEI's
  THREDDS OPeNDAP server, block-averaged 2×2 to 2 arc-minutes. That's about
  3.7 km N-S and 2.5 km E-W at 47° N. It's cached at
  [`../maps/pnw_terrain_3km.npz`](../maps/) (int16 meters, about 0.7 MB,
  covering 131°W to 106°W and 37°N to 58°N). If that file is missing,
  `fetch_terrain()` regenerates it (about 20 MB of transfer).

MSLP isobars, the L/H markers (`find_pressure_extrema()`), the city list
and the PlateCarree framing all follow the TPW map and the dew-point map.
The pressure-center separation drops to 4° from 6° for this smaller
domain.

## Files

- `build_map.py`: fetches the grids for the requested valid time and
  renders the map. The domain, color tables and hillshade strengths are
  defined near the top. Edit them there to adjust.
- `requirements.txt` / `setup.sh`: Python and system dependencies (cartopy
  needs GDAL, which only installs via apt) plus the Poppins font.

Output PNG (and, unless rendering from `--file`, a `.npz` snapshot of the
fetched grids) lands in `output/`.
