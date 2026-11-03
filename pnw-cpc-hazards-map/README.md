# Pacific Northwest CPC 8–14 Day Hazards Map

Styled map of the NWS Climate Prediction Center's Day 8–14 probabilistic
hazard outlooks over the Pacific Northwest and interior West: WA/OR/ID/MT
plus northern CA/NV/UT and WY, with only a thin strip of southern
BC/Alberta (CPC's outlook is US-only). The domain reaches east to the
Front Range so hazard areas spanning the interior West show their full
in-region edge. Three hazards share one map, layered top to bottom:

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

- Colors are CPC's own. Each KML's per-category `<Style>` color is read at
  runtime, so the map follows any palette change CPC makes. The `HAZARDS`
  list in `build_map.py` keeps the same values as a fallback. Fills use
  CPC's 70% opacity.

- Wind Moderate/High hatching is drawn above the rain fills (still below
  snow), since a hatch under a 70%-opaque fill all but disappears. Wind
  Slight, an outline, stays under the rain. State and country borders draw
  above every hazard layer so they stay readable through the fills.
- Borders come from Natural Earth's dedicated boundary-line files, using
  the same approach as `western-us-noaa-outlooks/`. Outlining state
  polygons instead left the 49th parallel as straight chords that split
  away from the curved US/Canada line under this map's perspective
  projection.
- Fills are translucent, so a lower layer stays visible under a higher one
  (e.g. the wind hatch shows through the rain fill). Within one hazard, a
  hatched or filled Slight area has any higher category cut out of it so the
  hatch doesn't muddy the fill it surrounds.
- CPC's hazards outlook is CONUS-only — nothing is ever drawn over BC/Alberta.
  Because CPC clips its polygons at the border, the outline-only wind
  Slight Risk has any edge along the US/Canada border removed; otherwise it
  just reads as a recolored border line.
- Hatch patterns, fill/hatch/outline modes, and the layer order live in the
  `HAZARDS` list near the top of `build_map.py`; the domain and figure
  geometry are just above it.
