# Pacific Northwest Sunrise Time Map

A styled map of local clock sunrise time across WA, OR, ID, western MT,
southern BC (north to about 100 Mile House) and southwestern Alberta. It
defaults to **Sunday, November 1, 2026**, the first fall-back where B.C.
and Alberta don't turn their clocks back. Sunrise across the border jumps
about an hour: Seattle is 6:54 AM PST and Vancouver is 8:01 AM. In the
East Kootenay and Alberta it reaches about 8:30 AM: Cranbrook 8:32,
Calgary 8:29, Golden 8:41.

## Usage

```bash
bash setup.sh                            # first time / fresh environment only
python3 build_map.py                     # Nov 1, 2026
python3 build_map.py --date 2026-12-21   # any other date
```

## Method

- **Sunrise** uses the NOAA solar calculator equations, vectorized over a
  0.01° grid. It's the upper limb on a sea-level horizon with the
  standard −0.833° refraction allowance; terrain is ignored. Results match
  the `astral` package to the minute.
- **Clock time**: each grid point gets the UTC offset of the time zone
  polygon it falls in (`../maps/tz_boundaries_north_america.json`; see
  [`../north-america-time-zones/`](../north-america-time-zones/)). US
  offsets come from the system tz database for the morning of the target
  date, after the 2 AM fall-back. Canada's 2026 offsets are pinned in
  `CANADA_2026`:
  - BC (incl. Peace region and Creston): UTC−7.
  - Alberta, East Kootenay and Golden: UTC−6.
- **15-minute isochrones** are contoured separately inside each offset
  region, so they end at time zone lines instead of stacking up where the
  clock jumps.
- Borders are densified (`densify()`) before plotting so straight lon/lat
  segments follow LambertConformal's curved parallels. Otherwise the
  49th parallel draws as two separate lines (the tz data and Natural
  Earth each have their own few vertices along it).
