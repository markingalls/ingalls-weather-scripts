# WM-6 Ensemble Mean TPW Map

One-off styled map of total precipitable water (TPW, i.e. total column
water vapour) for a single valid time, from WindBorne's WeatherMesh-6
global ensemble. Domain runs from Hawaii (SW) to central Alberta/
Saskatchewan (NE) -- the North Pacific, US West Coast, Great Basin, and
Western Canada in one frame. Rendered under Lambert Conformal Conic (the
standard NOAA/NWS projection for regional weather maps -- conformal,
shows the earth's actual curvature via converging meridians and bowed
parallels) rather than a flat PlateCarree rectangle; see build_map()'s
comment on projection choice for why that's a real tradeoff at this
domain's size, not just an aesthetic pick (compared against five other
curved projections -- NearsidePerspective, Orthographic, Stereographic,
AzimuthalEquidistant, Gnomonic -- all show the same shape gap, since it's
a function of this domain's angular width, not the specific projection).
The fetch/basemap-clip padding is deliberately asymmetric and generous in
longitude (see `FETCH_PAD_LON_DEG`) to fill in that gap with real,
correctly-located data -- meridians converge toward the pole, so the same
rectangular lon/lat crop that reaches the frame's edges at the domain's
south end falls well short at the north end, and simply padding a few
degrees in every direction (as earlier passes at this map did) doesn't
fix that. Unlike a true perspective/satellite-view projection (which has
a hard horizon cutoff), LambertConformal is conic and has no such limit
-- inverse-transforming the frame's actual corner pixels back to lon/lat
gives a real, finite answer even there, so with enough padding the
corners really do fill in completely (not just mostly); see
`imshow_antimeridian_safe()` for the other half of making that work, once
the padding was wide enough to actually cross the antimeridian. The color
table runs 0.5"-3.5" TPW, power-law spaced so the middle color lands on
1.5" rather than the range's literal midpoint (2.0") -- more of the
ramp's color variation falls across the more common lower/moderate range,
with the upper range comparatively compressed (see `TPW_IN_MID`).

Land (`LAND_COLOR`, pastel yellow) and ocean (`OCEAN_COLOR`, pastel blue)
are both drawn as a plain basemap fill beneath the TPW field, which fades
in by alpha rather than switching on/off hard at its 0.5" floor -- fully
transparent below it, ramping up to fully opaque by 0.75"
(`TPW_ALPHA_FADE_END_IN`) -- so sparse/dry areas still read as a real map
(dry land vs. dry ocean) instead of blank space, with the TPW color
easing in on top as it picks up.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
export WB_API_KEY=...
python build_map.py                 # tomorrow, 12:00 PM Pacific
python build_map.py --date 2026-07-30 --hour 12
python build_map.py --file output/snapshot_2026-07-30_12.npz  # re-render without re-fetching
```

`--date` is local (Pacific) time, default tomorrow. `--hour` is the local
target hour (0-23), default 12 (noon). WM-6's global gridded product
publishes 3-hourly steps, so the map is titled off whichever step actually
comes back (e.g. requesting `--hour 12` can render titled "11:00 AM PT" if
that's the nearest available step) rather than the exact hour requested.

## Data source

WindBorne WeatherMesh-6 (global, 0.25 deg), ensemble mean of
`total_column_water_vapour`, via the WindBorne gridded forecast API
(`WB_API_KEY` required -- get one at
https://app.windbornesystems.com/api_tokens).

Every run this was built against had already moved to archived storage by
the time it was fetched (WM-6 archives a run shortly after it finishes),
at which point the API's `variable=`/`include_distribution=` filtering is
rejected outright and only the complete per-forecast-hour file (every
variable, level, and product -- deterministic, ensemble mean/std, members,
percentiles -- roughly 2 GB compressed) is servable, via a presigned URL
(`as_url=true` with `variable=all`). `fetch_tcwv_mean()` in `build_map.py`
avoids pulling that whole archive: it uses
[`remotezip`](https://github.com/gtsystem/python-remotezip) to make HTTP
range requests against the presigned URL for just the handful of zarr
entries this map needs (the latitude/longitude coordinate arrays and the
TCWV ensemble-mean field), a few MB total instead of ~2 GB, then decodes
them with `zarr` from a small local directory built to mirror those
entries' paths (zarr's own codec pipeline handles WM-6's zstd/blosc +
zarr v3 sharding-indexed encoding; no manual codec work needed).

WM-6 (global) is a plain regular 0.25 deg lat/lon grid, unlike the
curvilinear native grids `wm6-3km`/HRRR fetches use elsewhere in this
repo, so the map bbox crop is a direct index slice -- no `griddata`
resampling step needed to handle a curvilinear source. The crop's
longitude bounds are unwrapped around `CENTER_LON` before comparing
against `LON_MIN`/`LON_MAX` (rather than compared as plain -180..180
values), so `FETCH_PAD_LON_DEG`'s generous padding can cross the
antimeridian -- as it does for this map's domain -- without the crop
window splitting into two disjoint, wrongly-ordered pieces. It's then
upsampled (`resample_to_finer_grid()`, linear interpolation via
`RegularGridInterpolator`) to a finer grid before rendering, since WM-6's
native ~28 km spacing is coarser than a screen pixel at this map's zoom
level and would otherwise look blocky once warped into the curved
LambertConformal view (a separate step from the crop/upsample, which is
why `scipy` is a dependency -- see `requirements.txt`).

Rendering that antimeridian-crossing data needs its own workaround:
`ax.imshow(..., extent=[...])` silently fails to warp the portion of an
extent that falls outside standard -180..180 (cartopy's `img_transform`
assumes a plain-range source), which left a blank gap even though the
fetched data was right there. `imshow_antimeridian_safe()` converts back
to standard signed longitude and splits into one `imshow` call per
contiguous piece wherever that wraps, with a small deliberate overlap
between pieces (harmless -- it's the same data on both sides) to paper
over a hairline antialiasing seam at the join.

Country/state/border-line basemap geometries are clipped to the map's bbox
(`MAP_CLIP_BOX`) and densified (`shapely.segmentize`) before being handed
to cartopy: at this domain's size, a real, mostly-straight-in-lon/lat run
like the US/Canada border tracking the 49th parallel for ~2000 km can be
represented with very few vertices, which is fine under PlateCarree but
draws as a visibly wrong straight chord once reprojected into
LambertConformal's curved view without enough intermediate points to bend
along.

## Files

- `build_map.py` -- fetches the ensemble-mean TPW grid for the requested
  local date/hour and renders the map. Map domain and the color table are
  both defined near the top -- edit directly to adjust.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`countries_slim.json` (full US/Canada/Mexico country polygons -- used
here instead of `land_slim.json`, which is clipped to the Pacific
Northwest and doesn't reach Hawaii), `states_lakes_slim.json` (state/
province polygons, lakes excluded), and `admin0_boundary_lines.json`
(international border line dataset).

Output PNG (and, unless rendering from `--file`, a `.npz` snapshot of the
fetched grid) lands in `output/`.
