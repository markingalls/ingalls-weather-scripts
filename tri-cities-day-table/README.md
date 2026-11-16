# Tri-Cities Single-Day Forecast Table

Generates a single-day forecast table for the Tri-Cities (Pasco, Kennewick,
Richland, WA) for Ingalls Weather's Instagram: one column per time of day
(6 AM, 9 AM, Noon, 3 PM, 6 PM, 9 PM), with a **temperature** row and a
**chance of precip** row. Same canvas footprint, fonts, palette, and
logo/title treatment as `tri-cities-7day-forecast/`.

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA) and the **next
Wednesday** (today included); pass `--day` for any other weekday. Works
anywhere NWS covers via `fetch_forecast.py --lat/--lon/--label` — see the
Hermiston example below.

## Files

- `fetch_forecast.py` — pulls NWS's hourly forecast (temperature row, plus
  the point's IANA timezone) and Open-Meteo's 50-member ECMWF IFS ensemble
  hourly precipitation/snowfall (chance-of-precip row) and writes
  `forecast.json`. No API keys needed.
- `build_table.py` — renders `forecast.json` into
  `<label>_<day>_table.png` (e.g. `tri_cities_wednesday_table.png`,
  `hermiston_wednesday_table.png`), named from the location label so
  renders for different points don't overwrite each other.
- `fonts/easy_weather_icons_font.ttf` — raindrop/snowflake glyphs, copied
  from `tri-cities-7day-forecast/fonts/` (MIT license, see
  `fonts/LICENSE-easy-weather-icons-font.txt`).
- `requirements.txt` / `setup.sh` — Python dependencies and the Poppins font.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

python3 fetch_forecast.py
python3 build_table.py             # next Wednesday
python3 build_table.py --day friday

# Hermiston, OR (same point the other Ingalls Weather maps/charts use)
python3 fetch_forecast.py --lat 45.8404 --lon -119.2895 --label "Hermiston" \
    --output forecast_hermiston.json
python3 build_table.py --forecast forecast_hermiston.json   # -> hermiston_wednesday_table.png
```

## Notes

- **Temperature**: NWS's `forecastHourly` value for the period starting at
  each column's hour. MetaMesh (the 7-day graphic's high/low source) isn't
  used here since the table wants the hourly curve rather than a daily
  max/min, and NWS's hourly feed gives that without a WindBorne key. A
  column outside NWS's ~6.5-day hourly horizon shows "—".
- **Chance of precip**: the fraction of the 50 ECMWF members whose total
  over the three hourly steps labeled hour-1, hour, hour+1 exceeds
  0.254mm (0.01", measurable) — the 7-day graphic's 0.5mm threshold is a
  whole-day one and would be too strict over 3 hours. With Open-Meteo's
  preceding-hour accumulations, the six columns tile the 04:00-22:00 local
  stretch. Rounded to the nearest 5% (same as the 7-day). A snowflake
  replaces the raindrop when that column's NWS temperature is below
  freezing (under 32°F, `FREEZING_F` in `build_table.py`); only if there's
  no temperature for the column does it fall back to the 7-day's ensemble
  rule (at least half the members show measurable snowfall). Below 20%
  (the 7-day's display threshold) the glyph is faded and the number gray
  rather than hidden, since a table should have every cell filled.
