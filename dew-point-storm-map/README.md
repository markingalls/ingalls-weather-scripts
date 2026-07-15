# BC / WA / OR / ID Dew Point Depression + Thunderstorm Map

A one-off styled map covering British Columbia, Washington, Oregon, and
Idaho: today's maximum dew point depression (2m temperature minus 2m
dewpoint) as shading, with a dashed red outline around where ECMWF IFS's
fields are consistent with thunderstorms today. Everything comes from a
single source, ECMWF's free Open Data IFS distribution (0.25°, 3-hourly),
fetched live via Herbie.

## Files

- `build_map.py` — fetches ECMWF IFS 2t/2d/mucape/tp for today and renders
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

The Ingalls Weather logo (bottom-right on the map) lives in
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
- **Thunderstorm outline** is a proxy, not an official product: ECMWF's
  Open Data distribution has no convective-precipitation or
  lightning/thunder field on its own. A grid cell is flagged if, in any
  3-hourly window today, most-unstable CAPE reaches `MUCAPE_THRESHOLD_JKG`
  (300 J/kg by default) *and* precipitation actually fell in that window
  (`PRECIP_THRESHOLD_MM`, 1.0 mm by default) — i.e. the airmass was
  unstable enough to convect, and that instability actually released as a
  shower/storm rather than being capped. Both thresholds are tuned for the
  Pacific Northwest/BC interior's generally modest summertime instability,
  not Great Plains-scale severe setups; adjust the constants near the top
  of `build_map.py` if a run looks over- or under-flagged.
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
