# Western U.S. Extreme Heat Hazard Map

Renders the "Western U.S. Extreme Heat Hazard" map — CPC's Day 8–14 outlook
(Great Basin / Desert Southwest / Interior West domain), styled to match
Ingalls Weather's regional-scale map house style.

## Files

- `build_map.py` — parses the CPC KML and renders the map using the shared
  basemap files in `../maps/`. Writes `western_us_extreme_heat_hazard.png`
  to `output/`.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):

- `land_slim.json`, `countries_slim.json`, `states_lakes_slim.json` —
  coastline / country / state-province+lake boundaries (US, Canada,
  Mexico), clipped to North America and shared across map projects.

The Ingalls Weather logo (placed bottom-right on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Data source

NOAA/CPC does not provide a stable, live-fetchable feed for this product —
the KML must be downloaded by hand each time from CPC's site and dropped
into `data/`:

- Probabilistic (Slight/Moderate/High Risk — preferred):
  https://www.cpc.ncep.noaa.gov/products/predictions/threats/excess_heat_prob_D8_14.kml
- Categorical (single "Extreme Heat" category — fallback if the
  probabilistic file isn't available that day):
  https://www.cpc.ncep.noaa.gov/products/predictions/threats/temp_D8_14.kml

## Usage

```bash
bash setup.sh                                        # first time / fresh environment only
python build_map.py --kml data/excess_heat_prob_D8_14.kml
```

Output lands in `output/`.

## Notes

- The script auto-detects which of the two KML formats you've handed it,
  auto-extracts the valid date range from the KML itself for the subtitle,
  and only legends whichever risk categories are actually present that day.
- The map domain, city labels, colors, etc. are all defined near the top
  of `build_map.py` — edit directly to adjust.
