# Blue Mountains Downslope Wind Map

One-off map of the latest NOAA **RTMA** (Real-Time Mesoscale Analysis,
2.5 km) 2m temperature over the Tri-Cities, Walla Walla Valley, Umatilla
Basin and northern Blue Mountains, with **10m wind streamlines** and
1,000 ft terrain contours on top. Built to show downslope flow off the
Blues mixing warmer air down into Pendleton and Hermiston while the
Tri-Cities and Walla Walla stay stuck in the basin cold pool.

Temperature uses the preferred Ingalls Weather color table, the same
fixed Kelvin-to-RGB `TEMP_COLOR_TABLE` as
[`../columbia-basin-temps/`](../columbia-basin-temps/), so a given shade
means the same temperature here as on every other temp map. Canvas, fonts,
borders, highways, city labels, colorbar (°F bottom / °C top, only the
visible slice) and logo placement all match that project.

## Usage

```bash
bash setup.sh                                   # first time / fresh environment only
python build_map.py                             # latest RTMA hour on AWS
python build_map.py --time "2026-11-18 15:00"   # a specific analysis hour (UTC)
python build_map.py --title "Downslope Winds Off the Blues"
```

No API key: Herbie pulls just the TMP / WIND / WDIR / HGT records from
NOAA's `noaa-rtma-pds` AWS bucket. The script prints each city's
temperature, wind and elevation (nearest native RTMA grid point) to the
console, which is handy for writing the caption. Output lands in `output/`.

## Notes

- **Wind direction.** RTMA's UGRD/VGRD are grid-relative to its Lambert
  conformal grid (rotated about 10° from true north out here), so u/v are
  rebuilt from WIND + WDIR, which are earth-relative.
- **Streamlines** are computed on a coarser (140×100) regular grid after a
  light Gaussian smooth, since RTMA's wind field is noisy at full
  resolution. Line width scales with speed (thicker = stronger, saturating
  near 18 mph). Streamlines are only drawn where the smoothed wind is at
  least 3 mph (`STREAM_MIN_MPH`), so calm cold-pool areas stay clean and
  each line stops where it runs into one. For PlateCarree input, cartopy reads vectors as
  d(lon)/d(lat) rates, so the eastward component is divided by cos(lat) to
  keep the true compass direction once projected.
- **City temperatures** come from the nearest native RTMA grid point, not
  the resampled raster. RTMA is an analysis (observations blended into a
  short-range model background), so it can differ from a single station
  ob by a degree or two.
- Domain, cities, contour levels and streamline density are constants
  near the top of `build_map.py`.
