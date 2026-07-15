# BC / WA / OR / ID Dew Point Depression + Thunderstorm Map

A one-off styled map covering British Columbia, Washington, Oregon, and
Idaho: today's maximum dew point depression (2m temperature minus 2m
dewpoint) as shading, with a white-outlined dashed red contour around
where ECMWF IFS's fields are consistent with thunderstorms today, and a
gray shade over everything outside that contour so the flagged area pops.
Everything comes from a single source, ECMWF's free Open Data IFS
distribution (0.25°, 3-hourly), fetched live via Herbie.

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
python3 build_map.py                   # today, BC/WA/OR/ID
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
  `build_map.py` if a run looks over- or under-flagged. Before contouring,
  the flagged mask goes through a morphological opening + closing pass
  (`clean_small_features()`, radius `MIN_FEATURE_CELLS`) that drops
  isolated single-cell-scale specks in both directions — lone flagged
  cells and lone unflagged holes — so the boundary reads as a handful of
  coherent regions instead of a speckled mess; this can also bridge
  nearby separate patches into one contiguous area, which is usually the
  desired effect but is worth knowing about if the shape looks broader
  than expected. The contour is drawn twice (a thick white pass under a
  thin red pass, both sharing an explicit dash pattern so they stay in
  phase) for a white-outlined look that reads against dark DPD colors,
  and everything outside the >=0.5 contour level gets a translucent gray
  overlay so the flagged area stands out.
- **Color table** runs wet-to-dry: green (near-saturated) through yellow
  (comfortable) through gray (transitional) to brown (very dry — the
  fire-weather-relevant end of the scale), fixed Fahrenheit control points
  in `DPD_COLOR_TABLE_F` (not rescaled per map, so a given shade always
  means the same DPD across runs).
- The colorbar's primary (bottom) axis is Fahrenheit; a secondary (top)
  axis mirrors it in Celsius via a *difference* conversion (`f_diff_to_c`
  /`c_diff_to_f` — no -32/+32 offset, since DPD is already a delta, not an
  absolute temperature).
- The map domain is the bounding box of BC + WA + OR + ID, padded slightly
  (`LON_MIN`/`LON_MAX`/`LAT_MIN`/`LAT_MAX` near the top of `build_map.py`).
- Uses `PlateCarree`, not `NearsidePerspective` (used by the other scripts
  in this repo): this domain is unusually tall north-south, and both
  NearsidePerspective and Lambert Conformal fit the axes to a rectangle
  bounding the *projected* (curved) shape of the requested lon/lat box —
  on a box this tall, that bounding rectangle's corners fall outside the
  box itself, leaving a real gap near the NW corner no amount of data
  padding fixes. PlateCarree has no such gap, at the cost of some
  east-west compression near the domain's north end (~60N) versus its
  south end — a standard tradeoff for a wide-latitude-range map.
