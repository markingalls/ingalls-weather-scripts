# Western U.S. NOAA Outlook Maps

Renders NOAA outlook products over the same Western U.S. frame (Great Basin
/ Desert Southwest / Interior West domain), styled to match Ingalls
Weather's regional-scale map house style. One script, one `--product` flag
per outlook.

## Products

| `--product`   | Outlook                                    | Source |
|---------------|---------------------------------------------|--------|
| `heat_d8_14`  | Extreme Heat, Day 8–14 (default)             | CPC |
| `temp_6_10`   | Temperature Outlook, 6–10 Day                | CPC |
| `precip_6_10` | Precipitation Outlook, 6–10 Day              | CPC |
| `temp_8_14`   | Temperature Outlook, 8–14 Day                | CPC |
| `precip_8_14` | Precipitation Outlook, 8–14 Day              | CPC |
| `temp_wk34`   | Temperature Outlook, Week 3–4                | CPC |
| `precip_wk34` | Precipitation Outlook, Week 3–4              | CPC |
| `spc_fire`    | Fire Weather Outlook, Day 1                  | SPC |
| `spc_fire_day2` | Fire Weather Outlook, Day 2                | SPC |
| `spc_severe`  | Severe Weather (Categorical) Outlook, Day 1  | SPC |
| `wpc_precip`  | Excessive Rainfall Outlook, Day 1            | WPC |
| `drought_monitor` | U.S. Drought Monitor (D0–D4)             | NDMC |

## Usage

```bash
bash setup.sh                        # first time / fresh environment only
python build_map.py                  # heat_d8_14 (default)
python build_map.py --product temp_8_14
python build_map.py --product spc_severe
```

Each product's current KML/KMZ is fetched live over HTTPS — no manual
download step. Output PNG lands in `output/` (filename varies by product,
e.g. `western_us_temp_8_14.png`).

To render from a file you already have instead of fetching (useful for
testing, or if a source is temporarily down), pass `--file path/to/thing.kml`
(or `.kmz`) — drop such files in `data/` by convention.

## Files

- `build_map.py` — the product registry (`PRODUCTS` dict), KML parsers, and
  map renderer. To add another NOAA outlook, add an entry to `PRODUCTS`
  pointing at a fetch URL, a parser (`parse_kml_named` or
  `parse_kml_extended_data` — see the module docstring for which fits a
  new source), and a style function.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):

- `land_slim.json`, `countries_slim.json`, `states_lakes_slim.json` —
  coastline / country / state-province+lake boundaries (US, Canada,
  Mexico), clipped to North America and shared across map projects.

The Ingalls Weather logo (placed bottom-right on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- Every product auto-extracts its own valid date/period for the subtitle
  and only legends whichever categories actually fall inside the Western
  US frame that day (nationwide products like the CPC temp/precip and SPC/WPC
  outlooks routinely have shading well outside this map's extent).
- CPC's temperature/precipitation outlooks are a continuous probability
  (33–90% confidence) rather than a handful of fixed categories, so their
  fill color is sampled from a colormap by probability (blue/orange-red for
  temperature, brown/green for precipitation) rather than a hand-picked
  swatch per tier.
- SPC and WPC outlooks use small, fixed category sets (e.g. Marginal /
  Slight / Moderate / High), styled with a hand-picked swatch per category
  in `build_map.py`.
- The map domain, city labels, etc. are all defined near the top of
  `build_map.py` — edit directly to adjust.
