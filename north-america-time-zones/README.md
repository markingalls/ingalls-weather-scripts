# North America Time Zone Map (Winter 2026–27)

A styled map of North America's time zones after the **November 1, 2026**
fall-back, the first winter in which much of Western and Central Canada
stops changing clocks. Fill color is each area's UTC offset this winter.
Hatching marks places that keep the same time year-round. A dashed red
outline marks the area that stopped changing clocks in 2026. Cities are
labelled with their clock time when it's noon in Seattle, which makes the
new oddities easy to read: Vancouver is an hour ahead of Seattle, Calgary
matches Chicago, and Winnipeg matches Toronto.

## What changed in Canada (as of Nov 1, 2026)

| Area | Winter 2026–27 | Notes |
|---|---|---|
| British Columbia (most) | UTC−7, year-round | Last clock change Mar 8, 2026. New "Pacific Time" |
| BC Peace region, Creston | UTC−7, year-round | Unchanged (never observed DST) |
| East Kootenay (RDEK) + Golden | UTC−6, year-round | Year-round Mountain Daylight Time; still matches Alberta |
| Alberta (incl. Lloydminster) | UTC−6, year-round | "Alberta Time", Official Time Act 2026 |
| Northwest Territories | UTC−6, year-round | |
| Manitoba + NW Ontario Central-time area (Kenora, Rainy River) | UTC−5, year-round | Year-round Central Daylight Time |
| Saskatchewan | UTC−6, year-round | Unchanged |
| Yukon | UTC−7, year-round | Unchanged since 2020 |
| Rest of Ontario, Quebec, Atlantic, NL, Nunavut | Standard time | Still fall back |

These are pinned in `CANADA_2026` near the top of `build_map.py`, so the
map is correct even on a machine whose tz database predates 2026e. The
script prints a note if the local tz database disagrees. Everything
outside Canada (US, Mexico, Caribbean, Greenland) comes from the system
tz database.

## Files

- `build_map.py` renders the map. No network access needed.
- `prepare_basemap.py` is a one-time job that regenerates the shared
  basemap files in [`../maps/`](../maps/):
  - `tz_boundaries_north_america.json` holds the IANA zone polygons from
    the `timezonefinder` package, which bundles
    timezone-boundary-builder's OSM-derived boundaries.
  - `na_land_50m.json`, `na_lakes_50m.json` and
    `na_admin1_lines_50m.json` are continent-wide Natural Earth 50m
    layers. The existing `*_slim.json` files stop at −85° lon.
- `requirements.txt` / `setup.sh` install the dependencies and the
  Poppins font.

## Usage

```bash
bash setup.sh                 # first time / fresh environment only
python3 build_map.py          # -> output/north_america_time_zones_2026.png
python3 prepare_basemap.py    # only to refresh ../maps/ tz/land layers
```

## Notes

- The tz polygons are geography only: they say which tzid a place belongs
  to. The polygons cover more than their namesake city. `America/Edmonton`
  includes East Kootenay, Golden, Lloydminster and most of the NWT.
  `America/Winnipeg` includes Kenora and Rainy River.
- Zone fills are clipped to Natural Earth land, minus the large lakes, so
  coastlines and the Great Lakes stay crisp.
- The 2026 outline is lightly smoothed (a 0.35° closing buffer) so it
  traces the region, not every offshore islet.
- The projection is Lambert Conformal, framed as a projected rectangle
  from `FRAME_POINTS`. The figure height is derived from that rectangle,
  so the frame never gets gutters.
