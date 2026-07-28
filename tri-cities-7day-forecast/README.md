# Tri-Cities 7-Day Forecast Graphic

Generates a TV-style 7-day forecast strip for the Tri-Cities (Pasco,
Kennewick, Richland, WA) for Ingalls Weather's Instagram: one card per day
with day-of-week, date, a daytime-condition icon, and the high/low
temperatures. Same canvas footprint and fonts as the other Ingalls Weather
graphics (`columbia-basin-alerts-map/`, `850-700-temp-chart/`).

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA). Conditions/icons come
from the NWS forecast; high/low temperatures come from WindBorne's MetaMesh,
queried directly by station ID.

## Files

- `fetch_forecast.py` — pulls the current NWS 7-day forecast (day/night
  periods, condition icon codes) for a point from api.weather.gov and
  writes `forecast.json`. No API key needed.
- `fetch_metamesh_forecast.py` — pulls the MetaMesh point temperature
  forecast for a station from WindBorne and writes `metamesh_forecast.json`.
  Requires `WB_API_KEY` in the environment (get one at
  https://app.windbornesystems.com/api_tokens). Run both fetch scripts any
  time you want the graphic to reflect the latest forecast/model run.
- `build_graphic.py` — renders `forecast.json` + `metamesh_forecast.json`
  into `tri_cities_7day_forecast.png`. Icon/color mapping and card layout
  are defined near the top — edit directly to adjust.
- `fonts/easy_weather_icons_font.ttf` — the day/night condition icon glyphs,
  from [easy-weather-icons-font](https://github.com/boxbot6/easy-weather-icons-font)
  (MIT license, see `fonts/LICENSE-easy-weather-icons-font.txt`).
- `requirements.txt` / `setup.sh` — Python dependencies (no system packages
  needed here, unlike the map projects).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export WB_API_KEY=...              # your WindBorne API key

python3 fetch_forecast.py
python3 fetch_metamesh_forecast.py
python3 build_graphic.py

# Anywhere else MetaMesh has a supported METAR station
python3 fetch_forecast.py --lat 45.5898 --lon -122.5951 --label "Portland, OR"
python3 fetch_metamesh_forecast.py --station kpdx
python3 build_graphic.py
```

## Notes

- **Conditions/icons**: NWS's `/gridpoints/.../forecast` endpoint, which
  returns 14 alternating day/night periods (7 of each) with a
  `shortForecast` and an `icon` URL per period. The NWS `icon` URL's last
  path segment before the query string (e.g.
  `.../land/day/tsra,40?size=medium` → `tsra`) is looked up in
  `NWS_ICON_MAP` to pick a glyph name and color from the
  easy-weather-icons-font set and the palette defined near the top of
  `build_graphic.py`. Only "day" glyph variants are used, since the graphic
  always shows the daytime condition regardless of period. A handful of
  NWS's less common codes (`hot`, `cold`) don't have a close equivalent in
  the icon set and fall back to a plain clear/wind glyph; anything
  completely unmapped falls back to the font's `UNKNOWN` glyph rather than
  raising. Icons are drawn bold: the font itself is a thin-stroke outline
  face with no bold weight, so each glyph is stroked in its own fill color
  (`set_path_effects([pe.withStroke(...)])`) to fatten the outline instead.
- **High/low temperatures**: come from MetaMesh's `temperature_2m`, not from
  NWS's own temperature fields. MetaMesh is a deterministic multi-model
  blend (ECMWF IFS/AIFS, NOAA GFS/HRRR, and WindBorne's own models,
  bias-corrected against the target METAR station's observations) rather
  than an ensemble, so there's a single forecast value per timestep, not a
  distribution/median to pick from. `fetch_metamesh_forecast.py` queries it
  by station ID (`kpsc`) rather than lat/lon, since MetaMesh's per-station
  bias correction only covers its 349 supported METAR stations.
  `daily_columns()` in `build_graphic.py` keeps each NWS period's start/end
  time (rather than its temperature) and pairs each daytime period with the
  night immediately following it, same as TV weathercasts (the paired
  night's window becomes the "low" shown under that day's card — not a true
  overnight low spanning the previous evening into that morning).
  `attach_metamesh_temps()` then reduces the MetaMesh series over each
  period's exact window (max for the high, min for the low) and converts
  °C to °F. If `metamesh_forecast.json` wasn't fetched far enough out to
  cover a given period, that card shows "—" instead of guessing. If the NWS
  feed happens to start overnight (fetched after sunset before a "Today"
  period exists), that leading night period is dropped since it has no
  daytime pair to lead a column.
  - MetaMesh's exact JSON response envelope isn't publicly documented — the
    endpoint (`/forecasts/v1/point_forecast`, which is hard-coded to serve
    MetaMesh when no model is specified in the path) was confirmed directly
    against the live API, but `metamesh_temp_series()` handles both a flat
    list of per-timestep records and a WM-6-style nested list (one inner
    list per requested station) since which shape it actually returns
    hasn't been verified against real credentials yet — check the parsing
    if `fetch_metamesh_forecast.py`'s output looks off.
- Today's card gets a green outline (`TODAY_EDGE`, the same forest green as
  the logo's pine tree) and a green day label, so it stands out as the
  current-conditions column. Every card, including today's, shows the
  three-letter day abbreviation (`TUE`, `WED`, ...).
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `columbia-basin-alerts-map/build_map.py` — edit `build_graphic.py`
  directly to adjust.
