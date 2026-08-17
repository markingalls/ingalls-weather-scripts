# WM-6 Ensemble Mean 500 mb Heights & Wind Map

One-off styled map of 500 mb geopotential height and wind speed, from
WindBorne's WeatherMesh-6 global ensemble mean, for a single valid time.
Domain is centered on Portland, OR and wide enough north to reach SE
Alaska (Ketchikan/Sitka/Juneau) -- the Northeast Pacific, US West Coast,
Great Basin, and Western Canada in one frame. Rendered under Lambert
Conformal Conic, same projection choice (and same reasoning -- see that
map's README) as
[`../tpw-wm6-ensemble-map/`](../tpw-wm6-ensemble-map/), re-derived for
this map's own wider-than-tall domain: inverse-transforming the rendered
frame's actual corner pixels back to lon/lat shows the top corners need
~18.3 deg of extra longitude beyond `LON_MIN`/`LON_MAX` and the bottom
edge dips ~4.1 deg south of `LAT_MIN` at its corners, both comfortably
inside `FETCH_PAD_LON_DEG`/`FETCH_PAD_LAT_DEG`.

Heights are contoured every 6 dam (60 m -- the standard synoptic 500 mb
analysis interval, and the user-requested one), labeled with the
conventional truncated 3-digit dam value (e.g. "564" for 5640 m).
Wind speed is shaded in a varied purple ramp starting at 30 kt, fading in
by alpha between 30 and 40 kt (rather than switching on hard at the
floor) so the basemap still shows through faintly right at the edge of
the shaded band -- same fade-in technique as the TPW map's moisture
field, see `WIND_ALPHA_FADE_END_KT`.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
export WB_API_KEY=...
python build_map.py --date 2026-08-22 --hour 0      # 2026-08-22 00Z
python build_map.py --file output/snapshot_2026-08-22_00z.npz  # re-render without re-fetching
```

`--date`/`--hour` are UTC (500 mb charts are conventionally labeled in Z
time, unlike the TPW map's Pacific-local default) -- `--hour` accepts any
0-23 but 0/6/12/18 (standard synoptic hours) are the sensible choices.
WM-6's global gridded product publishes 3-hourly steps, so the map is
titled off whichever step actually comes back rather than the exact hour
requested.

## Data source

WindBorne WeatherMesh-6 (global, 0.25 deg), ensemble mean of `geopotential`,
`wind_u`, and `wind_v` at 500 hPa, via the WindBorne gridded forecast API
(`WB_API_KEY` required -- get one at
https://app.windbornesystems.com/api_tokens). Geopotential height is
computed from geopotential by dividing by standard gravity
(`STANDARD_GRAVITY`, 9.80665 m/s^2); wind speed is `hypot(wind_u, wind_v)`
converted from m/s to knots.

Fetches an archived run's presigned URL the same way as
[`../tpw-wm6-ensemble-map/`](../tpw-wm6-ensemble-map/)'s `fetch_wm6_fields()`
(see that README for the full explanation of why -- WM-6 archives a run
shortly after it finishes, at which point only the complete ~2 GB
per-forecast-hour file is servable, so this uses `remotezip` range
requests to pull just the needed zarr entries instead of the whole
archive). One difference from that map: `geopotential`/`wind_u`/`wind_v`
are *pressure-level* variables (25 levels, 10-1000 hPa), and WindBorne's
public docs don't specify how a multi-level variable is laid out inside
the archived Zarr file -- `fetch_pressure_level_field()` in `build_map.py`
tries a level-specific array first (e.g. `ensemble_mean/geopotential_500`),
then falls back to a single 3D `(level, lat, lon)` array plus a level
coordinate array (trying several likely coordinate names), and raises a
clear error listing everything actually found under `ensemble_mean/` if
neither guess matches. This was written and the rendering pipeline
validated end-to-end against a synthetic snapshot (no `WB_API_KEY` was
available in the environment this was built in) -- the first real fetch
is what actually confirms which archive layout WM-6 uses; if it hits the
fallback error, paste the printed array listing back and the fetch logic
can be adjusted to match.

## Files

- `build_map.py` -- fetches the ensemble-mean 500 mb geopotential/wind_u/
  wind_v grids for the requested UTC date/hour and renders the map. Map
  domain, height contour interval, and the wind color table are all
  defined near the top -- edit directly to adjust.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip). Identical to
  `../tpw-wm6-ensemble-map/`'s.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`countries_slim.json` (full US/Canada/Mexico country polygons -- used here
instead of `land_slim.json`, which is clipped to the Pacific Northwest and
doesn't reach SE Alaska), `states_lakes_slim.json`, and
`admin0_boundary_lines.json`.

Output PNG (and, unless rendering from `--file`, a `.npz` snapshot of the
fetched grid) lands in `output/`.
