# Tri-Cities 7-Day Forecast Graphic

Generates a TV-style 7-day forecast strip for the Tri-Cities (Pasco,
Kennewick, Richland, WA) for Ingalls Weather's Instagram: one card per day
with day-of-week, date, a daytime-condition icon, and the high/low
temperatures. Same canvas footprint and fonts as the other Ingalls Weather
graphics (`columbia-basin-alerts-map/`, `850-700-temp-chart/`).

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA), but any lat/lon works.

## Files

- `fetch_forecast.py` — pulls the current NWS 7-day forecast (day/night
  periods, temperatures, icon codes) for a point from api.weather.gov and
  writes `forecast.json`. No API key needed. Run this first, any time you
  want the graphic to reflect the latest forecast package.
- `build_graphic.py` — renders `forecast.json` into
  `tri_cities_7day_forecast.png`. Icon/color mapping and card layout are
  defined near the top — edit directly to adjust.
- `fonts/easy_weather_icons_font.ttf` — the day/night condition icon glyphs,
  from [easy-weather-icons-font](https://github.com/boxbot6/easy-weather-icons-font)
  (MIT license, see `fonts/LICENSE-easy-weather-icons-font.txt`).
- `requirements.txt` / `setup.sh` — Python dependencies (no system packages
  needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only

python3 fetch_forecast.py
python3 build_graphic.py

# Anywhere else
python3 fetch_forecast.py --lat 45.5898 --lon -122.5951 --label "Portland, OR"
python3 build_graphic.py
```

## Notes

- **Data source**: NWS's `/gridpoints/.../forecast` endpoint, which returns
  14 alternating day/night periods (7 of each) with a temperature, a
  `shortForecast`, and an `icon` URL per period. `daily_columns()` in
  `build_graphic.py` pairs each daytime period with the night immediately
  following it — that night's temperature becomes the "low" shown under
  that day's card, matching how TV weathercasts pair them (not a true
  overnight low spanning the previous evening into that morning). If the
  feed happens to start overnight (fetched after sunset before a "Today"
  period exists), that leading night period is dropped since it has no
  daytime pair to lead a column.
- **Icon mapping**: the NWS `icon` URL's last path segment before the query
  string (e.g. `.../land/day/tsra,40?size=medium` → `tsra`) is looked up in
  `NWS_ICON_MAP` to pick a glyph name and color from the
  easy-weather-icons-font set and the palette defined near the top of
  `build_graphic.py`. Only "day" glyph variants are used, since the graphic
  always shows the daytime condition regardless of period. A handful of
  NWS's less common codes (`hot`, `cold`) don't have a close equivalent in
  the icon set and fall back to a plain clear/wind glyph; anything
  completely unmapped falls back to the font's `UNKNOWN` glyph rather than
  raising.
- Today's card gets a green outline (`TODAY_EDGE`, the same forest green as
  the logo's pine tree) instead of the day-of-week name, so it stands out
  as the current conditions column.
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `columbia-basin-alerts-map/build_map.py` — edit `build_graphic.py`
  directly to adjust.
