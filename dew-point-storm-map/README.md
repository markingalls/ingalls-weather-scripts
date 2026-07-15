# Pacific Northwest Dew Point Depression + Thunderstorm Map

A one-off styled map zoomed to Prince George BC (N), Bella Coola BC (W),
Winnemucca NV (S), and Yellowstone WY (E) — covering southern/central BC,
WA, OR, ID, and slivers of NV/MT/WY: today's maximum dew point depression
(2m temperature minus 2m dewpoint) as shading, with a white-outlined
dashed red contour around where ECMWF IFS's fields are consistent with
thunderstorms today, and a translucent gray shade over everything outside
that contour so the flagged area pops. Everything comes from a single
source, ECMWF's free Open Data IFS distribution (0.25°, 3-hourly),
fetched live via Herbie.

## Files

- `build_map.py` — fetches ECMWF IFS 2t/2d/mucape for today and renders
  the map. Also saves a `.npz` snapshot of the fetched data to `output/`
  each run, so `--file` can re-render without re-fetching.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL; cfgrib/eccodes need libeccodes; both apt-only). `setup.sh`
  also installs the Poppins font used for map labels, since it isn't
  packaged for apt.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`land_slim.json`, `states_lakes_slim.json`, `admin1_boundary_lines.json`,
`admin0_boundary_lines.json` — already clipped to US/Canada/Mexico,
including British Columbia.

The Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                          # first time / fresh environment only
python3 build_map.py                   # today
python3 build_map.py --date 2026-07-16
python3 build_map.py --file output/snapshot_2026-07-15.npz  # re-render, no fetch
```

## Methodology notes

- **Dew point depression** is the max of (2m temp − 2m dewpoint) sampled
  every 3 hours across the local (Pacific time) day, at ECMWF IFS's native
  0.25° resolution, then linearly resampled onto a finer regular grid for
  smoother shading.
- **Thunderstorm outline** is a proxy, not an official product. ECMWF does
  define an instantaneous lightning flash density parameter (`litoti`),
  but it's only in ECMWF's paid MARS archive — confirmed absent from the
  free Open Data feed this script uses by checking today's `oper`, `enfo`,
  and `aifs` index files directly, no `lit*` param in any of them. Instead,
  a grid cell is flagged if, in any 3-hourly window today, most-unstable
  CAPE reaches `MUCAPE_THRESHOLD_JKG` (200 J/kg by default, tuned low for
  the Pacific Northwest/BC interior's generally modest summertime
  instability, not Great Plains-scale severe setups). This is CAPE alone,
  with no precipitation check, so it flags convective *potential* —
  airmass instability consistent with thunderstorms — not confirmation
  that a storm actually fired; adjust the constant near the top of
  `build_map.py` if a run looks over- or under-flagged.
- The flagged mask is heavily gaussian-smoothed (`sigma=7.0` on the
  resampled grid) before contouring, rather than cleaned up with binary
  morphology first — a binary opening/closing pass's square structuring
  element produces visible right-angle steps at the native 0.25° grid's
  scale, which read as "blocky." Smoothing the continuous (pre-threshold)
  field does double duty: it rounds the boundary into a natural curve, and
  it washes out minor single-cell-scale specks on its own (their
  contribution gets diluted below the 0.5 contour level by the
  surrounding opposite-signed area), no separate cleanup pass needed. This
  can also merge nearby separate patches into one contiguous area, which
  is usually the desired effect but is worth knowing about if the shape
  looks broader than expected — reduce `sigma` if a run looks over-smoothed.
- The contour is drawn twice (a thick white pass under a thin red pass,
  both sharing an explicit dash pattern so they stay in phase) for a
  white-outlined look that reads against dark DPD colors, and everything
  outside the >=0.5 contour level gets a translucent gray overlay
  (`alpha=0.55`) so the flagged area stands out.
- **Color table** runs wet-to-dry: green (near-saturated) through yellow
  (comfortable) through gray (transitional) to brown (very dry — the
  fire-weather-relevant end of the scale), fixed Fahrenheit control points
  in `DPD_COLOR_TABLE_F` (not rescaled per map, so a given shade always
  means the same DPD across runs).
- The colorbar's primary (bottom) axis is Fahrenheit; a secondary (top)
  axis mirrors it in Celsius via a *difference* conversion (`f_diff_to_c`
  /`c_diff_to_f` — no -32/+32 offset, since DPD is already a delta, not an
  absolute temperature).
- The map domain is the bounding box of the four named landmarks, padded
  so each sits clearly inside the frame rather than right at the edge
  (`LON_MIN`/`LON_MAX`/`LAT_MIN`/`LAT_MAX` near the top of `build_map.py`).
  `FIG_WIDTH_IN` is chosen so the axes box's aspect ratio matches the
  domain's lon/lat span ratio — change one, re-check the other, or cartopy
  shrinks one dimension to preserve the projection's aspect and leaves
  empty gutters on the sides.
- Uses `PlateCarree`, not `NearsidePerspective` (used by the other scripts
  in this repo): a prior, taller version of this domain hit a real
  rendering gap with both NearsidePerspective and Lambert Conformal (they
  fit the axes to a rectangle bounding the *projected*, curved shape of
  the requested lon/lat box, and on a tall-enough box that rectangle's
  corners fall outside the box itself). PlateCarree has no such gap
  regardless of domain shape, at the cost of some east-west compression
  toward the domain's north end versus its south end — a standard
  tradeoff for a wide-latitude-range map, though a smaller one now that
  the domain is more square than the original BC-to-OR framing.
