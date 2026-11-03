# Pacific Northwest CPC 8–14 Day Hazards Map

Styled map of the NWS Climate Prediction Center's Day 8–14 probabilistic
hazard outlooks over the canonical Pacific Northwest domain (same as
[`../wildcad-fires-map/`](../wildcad-fires-map/) and
[`../dew-point-storm-map/`](../dew-point-storm-map/): Prince George BC to
Winnemucca NV, Bella Coola BC to Yellowstone WY). Three hazards share one
map, layered top to bottom:

| Layer  | Hazard              | Slight Risk   | Moderate Risk | High Risk   |
|--------|---------------------|---------------|---------------|-------------|
| Top    | Heavy Snow          | hatched (`\\`) | solid fill    | solid fill  |
| Middle | Heavy Precipitation | solid fill    | solid fill    | solid fill  |
| Bottom | High Winds          | outline only  | hatched (`//`) | hatched (denser) |

The legend below the map uses the same top-to-bottom order, one row per
hazard, and lists only categories present in the frame. Each category
carries its own valid dates, since CPC often gives a Moderate/High Risk a
shorter window than the full 8–14 day period.

## Usage

```bash
bash setup.sh                           # first time / fresh environment only
python3 build_map.py                    # fetch live and render
python3 build_map.py --data-dir data/   # re-render from the last fetch, no network
```

Output lands in `output/pnw_cpc_hazards_<period start>.png`.

## Data

CPC publishes a stable "latest" KML per hazard, fetched live each run (and
saved into `data/` for `--data-dir`):

- `snow_prob_D8_14.kml` — Heavy Snow
- `prcp_prob_D8_14.kml` — Heavy Precipitation
- `wind_prob_D8_14.kml` — High Winds

all under `https://www.cpc.ncep.noaa.gov/products/predictions/threats/`.

## Notes

- Fills are translucent, so a lower layer stays visible under a higher one
  (e.g. the wind hatch shows through the rain fill). Within one hazard, a
  hatched or filled Slight area has any higher category cut out of it so the
  hatch doesn't muddy the fill it surrounds.
- CPC's hazards outlook is CONUS-only — nothing is ever drawn over BC/Alberta.
  Because CPC clips its polygons at the border, the outline-only wind
  Slight Risk has any edge along the US/Canada border removed; otherwise it
  just reads as a recolored border line.
- Category colors, hatch patterns, and the layer order live in the `HAZARDS`
  list near the top of `build_map.py`.
