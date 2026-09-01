# WM-6 Ensemble Mean MSLP & 3-Hour Precipitation Map

One-off styled map of mean sea level pressure and 3-hour accumulated
precipitation, from WindBorne's WeatherMesh-6 global ensemble mean, for a
single valid time. Same domain, projection, and basemap styling
(including the major-lakes layer) as
[`../500mb-height-wind-map/`](../500mb-height-wind-map/) -- centered on
Portland, OR, wide enough north to reach SE Alaska.

MSLP is contoured every 4 hPa (the standard surface-analysis interval).
Precipitation is shaded in a standard NWS-style QPF ramp (green through
yellow, orange, red, to magenta for the heaviest amounts), starting at a
0.5 mm floor and fading in by alpha up to 2 mm (rather than switching on
hard at the floor), same fade-in technique as the sibling maps.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
export WB_API_KEY=...
python build_map.py --date 2026-09-02 --hour 0      # 2026-09-02 00Z
python build_map.py --file output/snapshot_2026-09-02_00z.npz  # re-render without re-fetching
```

`--date`/`--hour` are UTC, same convention as
[`../500mb-height-wind-map/`](../500mb-height-wind-map/).

## Data source

WindBorne WeatherMesh-6 (global, 0.25 deg), ensemble mean of
`pressure_msl` (Pa, converted to hPa) and `total_precipitation_3h` (mm,
used as-is). Both are archived as flat `(lat, lon)` arrays under
`ensemble_mean/` -- confirmed directly against a real archive while
building this, so unlike
[`../500mb-height-wind-map/`](../500mb-height-wind-map/)'s pressure-level
fields there was no array-layout guesswork needed here.
`total_precipitation_3h`'s `long_name` ("ensemble mean of total
precipitation 3 hour") doesn't explicitly document direction, but its
value is treated as the accumulation over the 3 hours *ending* at the
requested valid time -- the standard NWP convention (matches e.g. GFS's
3-hourly APCP) and the one "3-hour precip for a given valid time" implies.

Fetches an archived run's presigned URL the same way as
[`../tpw-wm6-ensemble-map/`](../tpw-wm6-ensemble-map/)'s
`fetch_wm6_fields()` (see that README for the full explanation of why).

## Files

- `build_map.py` -- fetches the ensemble-mean MSLP/precip grids for the
  requested UTC date/hour and renders the map. Map domain, MSLP contour
  interval, and the precip color table are all defined near the top --
  edit directly to adjust.
- `requirements.txt` / `setup.sh` -- identical to
  `../500mb-height-wind-map/`'s.

Shared basemap data lives one level up in [`../maps/`](../maps/). Output
PNG (and, unless rendering from `--file`, a `.npz` snapshot) lands in
`output/`.
