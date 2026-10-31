# Pacific Northwest Sunrise Time Map

A styled map of local clock sunrise time across WA, OR, ID, western MT,
southern BC (north to about 100 Mile House) and southwestern Alberta. It
defaults to **Sunday, November 1, 2026**, the first fall-back where B.C.
and Alberta don't turn their clocks back. Sunrise across the border jumps
about an hour: Seattle is 06:54 PST and Vancouver is 08:01. In the
East Kootenay and Alberta it reaches about 08:30: Cranbrook 08:32,
Calgary 08:29, Golden 08:41. All times are 24-hour.

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
  date, after the 02:00 fall-back. Canada's 2026 offsets are pinned in
  `CANADA_2026`:
  - BC (incl. Peace region and Creston): UTC−7.
  - Alberta, East Kootenay and Golden: UTC−6.
- **15-minute isochrones** are contoured separately inside each offset
  region, so they end at time zone lines instead of stacking up where the
  clock jumps.
- National and state border segments within `TZ_LINE_SNAP_DEG` (0.1°) of
  a time zone line are dropped, so the dashed tz line is the only line
  there. Same-offset zones are merged with a tiny closing buffer, so
  hairline gaps (e.g. Boise vs. Denver zones on the ID/MT line) don't draw
  as stray dashes.
- Borders are densified (`densify()`) before plotting so straight lon/lat
  segments follow LambertConformal's curved parallels. Otherwise the
  49th parallel draws as two separate lines (the tz data and Natural
  Earth each have their own few vertices along it).
