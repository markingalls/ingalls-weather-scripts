# RRFS Low-Level Wind Cross Section

Generates a styled vertical cross section of NOAA RRFS (3 km CONUS) winds
along a straight line between two points, from the ground up to the 700 mb
surface. Defaults to **Irrigon, OR → Tollgate, OR** (Columbia Basin floor up
the west slope of the Blue Mountains).

- **Shading:** wind speed (mph), using the same color table as the Tempest
  station wind chart (`tempest-wind-chart/build_chart.py`'s
  `WIND_COLOR_TABLE`).
- **Arrow:** the downslope jet off the Blue Mountains -- a white, smoothed
  trace of the fastest wind in the lowest 3,000 ft above the ground/inversion,
  from near the mountain end down to just short of where the inversion top
  rises again west of its low point (the cold pool that keeps the jet off
  the Basin floor).
- **Dashed line:** top of the low-level inversion -- the top of the warm
  layer above the ground (at least 1 °C warmer than 2 m, including any
  near-isothermal cap within 0.5 °C of the warmest point), lightly smoothed
  along the section. Columns where the mean wind from the ground to the
  inversion top is 30+ mph are left out as mechanically mixed. Toward the
  mountains, the line is held level from its lowest point (near Adams on
  the default section) out to where it meets the slope -- the cold-pool
  top that keeps the downslope jet off the Basin floor.
- **Terrain:** RRFS model terrain, filled; vertical scale is exaggerated
  (~20×, printed in the footer). Nearby towns are labeled at their
  along-section position.

## Files

- `fetch_cross_section.py` — finds the newest RRFS cycle on NOMADS that
  covers the requested valid time (default: the next 02z), byte-ranges just
  the needed GRIB messages (HGT/UGRD/VGRD/TMP at 1000–700 mb every 25 mb, plus
  surface height/pressure, 2 m temperature and 10 m wind), samples them along the line, and
  writes `cross_section.json`.
- `build_chart.py` — renders `cross_section.json` to
  `rrfs_wind_cross_section_<YYYYMMDD>_<HH>z.png`.
- `requirements.txt` / `setup.sh` — Python deps and the Poppins font.

## Usage

```bash
bash setup.sh                                   # first time only
python3 fetch_cross_section.py                  # next 02z, newest run
python3 build_chart.py

python3 fetch_cross_section.py --valid 2026-11-13T02 --run 2026-11-12T12
python3 fetch_cross_section.py --start '{"label":"Pasco","lat":46.2396,"lon":-119.1006}' \
                               --end   '{"label":"Dayton","lat":46.3207,"lon":-117.9772}'
```

## Notes

- RRFS's old AWS prefix (`noaa-rrfs-pds/rrfs_a/`) is empty now that RRFS is
  operational, so data comes straight from
  `nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod/`. Use HTTP/1.1 if you
  curl it by hand — NOMADS's padded `Content-Length` header breaks HTTP/2.
- Pressure levels below the model ground are dropped; the lowest point in
  each column is the 10 m wind.
- `NEARBY_TOWNS` in the fetcher only lists towns near the default line, in
  label priority order; a lower-priority label that has no room (e.g. Adams
  vs. Pendleton) is dropped. Pendleton is ~11 mi off the line but gets a
  wider allowance via `max_offset_km`. Add your own for other sections.
