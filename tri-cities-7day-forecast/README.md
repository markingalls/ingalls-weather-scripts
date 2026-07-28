# Tri-Cities 7-Day Forecast Graphic

Generates a TV-style 7-day forecast strip for the Tri-Cities (Pasco,
Kennewick, Richland, WA) for Ingalls Weather's Instagram: one card per day
with day-of-week, date, a daytime-condition icon, chance-of-precip indicator,
notable wind, and the high/low temperatures. Same canvas footprint and fonts
as the other Ingalls Weather graphics (`columbia-basin-alerts-map/`,
`850-700-temp-chart/`).

Defaults to **KPSC** (Tri-Cities Airport, Pasco, WA), but works anywhere NWS
covers — pass different `--lat`/`--lon` (and a MetaMesh `--station`) to the
fetch scripts. Conditions/icons come from the NWS forecast; high/low
temperatures come from WindBorne's MetaMesh, queried directly by station ID.
The local timezone is resolved per-location from NWS's own `/points`
response, not hardcoded, so the time-of-day logic below works correctly
wherever it's pointed.

## Files

- `fetch_forecast.py` — pulls the current NWS 7-day forecast (day/night
  periods, condition icon codes, and the point's IANA timezone) for a point
  from api.weather.gov and writes `forecast.json`. Also pulls
  windSpeed/windGust/windDirection from the same point's `forecastGridData`
  (the wind indicator's source — see below). No API key needed.
- `fetch_metamesh_forecast.py` — pulls the MetaMesh point temperature
  forecast for a station from WindBorne and writes `metamesh_forecast.json`.
  Requires `WB_API_KEY` in the environment (get one at
  https://app.windbornesystems.com/api_tokens).
- `fetch_openmeteo_forecast.py` — pulls Open-Meteo's daily weather-code
  forecast (16-day horizon) for a point and writes `openmeteo_forecast.json`.
  No API key needed. Only actually used by `build_graphic.py` for renders
  after 3pm local (see below) — harmless to skip otherwise, but cheap enough
  to just always run alongside the others.
- `fetch_ecmwf_ensemble_forecast.py` — pulls Open-Meteo's 50-member ECMWF
  IFS ensemble (hourly precipitation + snowfall) for a point and writes
  `ecmwf_ensemble_forecast.json`. No API key needed. Source for the
  chance-of-precip indicator (see below).
- `build_graphic.py` — renders `forecast.json` + `metamesh_forecast.json` +
  `ecmwf_ensemble_forecast.json` (+ `openmeteo_forecast.json`, conditionally)
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
python3 fetch_openmeteo_forecast.py
python3 fetch_ecmwf_ensemble_forecast.py
python3 build_graphic.py

# Anywhere else MetaMesh has a supported METAR station
python3 fetch_forecast.py --lat 45.5898 --lon -122.5951 --label "Portland, OR"
python3 fetch_metamesh_forecast.py --station kpdx
python3 fetch_openmeteo_forecast.py --lat 45.5898 --lon -122.5951
python3 fetch_ecmwf_ensemble_forecast.py --lat 45.5898 --lon -122.5951
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
    against the live API. Confirmed response shape: `forecasts` is a
    WM-6-style nested list (one inner list per requested station), each
    record a flat dict with `time`/`temperature_2m` (°C) directly (no
    `distribution` sub-object, since it's deterministic). Since a future
    account/plan or multi-station query could plausibly return a flat list
    instead, `metamesh_temp_series()` still handles both shapes.
- **What "today" means depends on when the graphic is rendered**, in the
  forecast location's own local time (`local_tz` in `main()`, resolved from
  `forecast.json`'s `timezone` field — see below), because a "forecast" high
  or low that's already happened isn't really a forecast anymore. The
  Tri-Cities' daily trough lands ~6-7am local and the peak ~3-5pm (checked
  against real MetaMesh hourly data — the sampled extremes were within
  ~0.1°F of a continuous curve fit, so hourly resolution isn't the limiting
  factor here, the clock is) — the 7am/3pm cutoffs below are pinned to that
  check and haven't been re-verified for other latitudes/climates:
  - **Before 7am**: today's high hasn't happened yet and its low (tonight's,
    per the day/night pairing above) is still hours off too — show both
    normally, no special-casing.
  - **7am-3pm**: this morning's low already happened and tonight's low is
    still far off, so a "low" here would be neither a completed nor a
    near-term forecast — `main()` blanks `columns[0]["low"]` to `None`
    (renders as "—") after `attach_metamesh_temps()` runs, without touching
    the high.
  - **After 3pm**: today's high has already happened or is happening, so
    today stops being forward-looking at all. `daily_columns(..., drop_today=True)`
    drops the Today/Tonight pair and the window starts tomorrow. This can
    leave only 6 NWS-backed columns (NWS's feed only reaches ~7 days out
    from whenever it was fetched, so dropping one day and not gaining a new
    one at the end comes up one short) — `main()` backfills a 7th
    (`synthetic_column()`) using MetaMesh for high/low (15-day horizon, so
    it already reaches this far) and Open-Meteo's daily `weathercode` (16-day
    horizon) mapped through `WMO_ICON_MAP` for the condition icon, since NWS
    has nothing that far out. The synthetic day's own window uses NWS's own
    6am-6pm/6pm-6am local split (`local_day_window()`) for consistency with
    every other column.
  - `drop_today` only drops something if NWS's own feed still names its
    first period "Today" — if the feed was fetched late enough that NWS has
    already moved past today on its own (periods[0] is already tomorrow,
    since today's day period stops being returned once it's over), there's
    nothing further to drop, so a render at, say, 9pm doesn't double-skip
    to the day after tomorrow just because the underlying fetch also
    happened in the evening.
- **Timezone resolution**: `fetch_forecast.py` stores NWS's own
  `properties.timeZone` (from the `/points` lookup it already makes) as
  `forecast.json`'s `timezone` field, and `build_graphic.py` reads it into
  `local_tz` at the top of `main()` — nothing is hardcoded to Pacific time
  anymore. `fetch_openmeteo_forecast.py` and `fetch_ecmwf_ensemble_forecast.py`
  independently pass `timezone=auto` to Open-Meteo, which resolves the same
  way from the lat/lon given (confirmed against the live API for both
  Tri-Cities and a Virginia Beach, VA test render — both endpoints agreed
  with NWS's own timezone).
- Saturdays, Sundays, and US federal holidays get a green outline
  (`HIGHLIGHT_EDGE`, the same forest green as the logo's pine tree) and a
  green day label (`is_weekend_or_holiday()`), rather than today getting
  singled out. Holidays (including floating ones like Memorial Day and
  Thanksgiving, with observed-date shifting) come from the `holidays`
  package's `holidays.US()` — hand-rolling the US federal holiday calendar
  isn't worth it. Every card shows the three-letter day abbreviation
  (`TUE`, `WED`, ...) regardless of highlighting.
- **Chance-of-precip indicator**: a raindrop/snowflake + probability, with a
  P25-P75 total underneath, shown on any card where the chance of precip is
  ≥20% (`POP_DISPLAY_THRESHOLD` in `build_graphic.py`). WM-6's own precip
  variable (`total_precipitation_3h`) was tried first, but confirmed
  directly against the live API to expose only fixed threshold-exceedance
  probabilities (`gt_0p25mm`, `gt_2p5mm`, `gt_6mm`, `gt_12p5mm`, `gt_25mm`,
  `gt_50mm`) and mean/std — no percentiles, no raw members, and no exact
  0.5mm threshold, unlike temperature's distribution on the same endpoint
  (which does have `p01`/`p25`/`p75`/etc). So this instead uses Open-Meteo's
  ensemble API, which exposes all 50 raw ECMWF IFS members for
  `precipitation` (mm) and `snowfall` (cm):
  - **Probability**: the fraction of the 50 members whose full local
    calendar-day total precipitation exceeds `POP_THRESHOLD_MM` (0.5mm) —
    an exact threshold, not an approximation, since raw members are
    available (`precip_summary()` in `build_graphic.py`).
  - **Rain vs. snow**: a day is classified as snow if at least half the
    members (the median) show measurable snowfall; otherwise rain. Mixed
    rain/snow days just get classified one way or the other, no in-between
    indicator.
  - **P25-P75 total**: the 25th/75th percentile (via `numpy.percentile`)
    across the 50 members' daily totals, in inches, for whichever of
    rain/snow applies. Rain always shows two decimal places (nearest quarter
    inch, nearest tenth below 0.3") via `round_rain_inches()`; snow always
    shows one decimal place (nearest half inch) via `round_snow_inches()`.
    Shown as a single value instead of a range when both ends round to the
    same number.
  - Each ensemble member's daily total is summed over `PRECIP_DAY_START_HOUR`
    (05:00) through 23:59 local, not the full calendar day and not the NWS
    6am-6pm/6pm-6am day/night split used for temperature — the 00:00-04:59
    stretch reads more like "overnight" than "today" on a TV-style forecast,
    and a single combined day+night indicator per card doesn't need
    temperature's day/night split.
  - **Suppressed when it would just read "0.00"**: if the rounded P75 total
    is zero (common at the low end of `POP_DISPLAY_THRESHOLD`, e.g. a 25%
    chance where even the 75th percentile member is still ~dry),
    `precip_summary()` returns `None` instead of a probability with a blank
    amount under it.
  - **Overrides NWS's own condition icon** when the chance of precip is
    ≥70% (`SIGNIFICANT_POP_THRESHOLD`), replacing it with a plain
    `RAINday`/`SNOWday` regardless of what NWS's `icon` field says —
    `attach_precip()` does this right after computing `precip_summary()`.
    NWS's icon reflects its own forecast text, which can undersell the
    chance our ensemble-derived probability shows (e.g. NWS says "Sunny" but
    the ensemble says 85% chance of rain); at that level of confidence the
    ensemble wins. Also sets `sun_relevant` to `False` for that column, same
    reasoning as excluding persistent rain from `SUN_RELEVANT_NWS_CODES`.
  - **AM/PM timing**: `precip_timing()` splits each day's precip-weighted
    signal (each hour's precipitation averaged across members) at noon; if
    ≥75% (`TIMING_DOMINANT_FRAC`) of it falls before noon the card gets an
    "AM" label at the bottom-right of the main condition icon, ≥75% at/after
    noon gets "PM", and anything more evenly split (spans midday, or runs
    through most of the day) gets no label.
  - **Sun behind the main icon**: when a day's condition is an
    isolated/scattered storm (`SUN_RELEVANT_NWS_CODES`:
    `tsra_hi`/`tsra_sct`/`rain_showers_hi`) and the precip is either a
    low-confidence chance (`pop < LOW_POP_THRESHOLD`, 50%) or confined to
    part of the day (has an AM/PM label), a `CLEARday` sun glyph is drawn
    behind the main icon (lower `zorder`, offset up-left, white disc masking
    it where it overlaps the icon) so a day coded as, say, isolated
    thunderstorms still reads as "mostly sunny" rather than "guaranteed
    storm." Deliberately excludes `skc`/`few`/`sct` even though those are
    "chance of sun" conditions too: `CLEARday`/`FAIRday`/`PCLOUDYday` already
    draw their own sun, so stacking another one behind them just doubles up
    (confirmed visually — a `skc` day with a low/partial precip chance
    produced two overlapping suns before this was scoped down). Also
    excludes persistent/guaranteed precip (`rain`, `tsra`, `bkn`/`ovc` etc.)
    where there's no real sun to show.
- **Wind indicator**: compass direction + sustained speed range on one line,
  gusts on the line below (same tight vertical spacing as the
  chance-of-precip line and its rainfall/snowfall total), shown only when a
  day's wind is notable enough to call out — sustained speed over 15mph
  (`WIND_SPEED_DISPLAY_THRESHOLD`) and/or gusts over 20mph
  (`WIND_GUST_DISPLAY_THRESHOLD`), per `attach_wind()` in `build_graphic.py`.
  - Sourced from NWS's raw gridpoints feed (`forecastGridData`), not the
    human-readable periods forecast — the periods' `windSpeed` field is only
    a plain-text range with no gust figure at all, while the gridpoints feed
    carries proper windSpeed/windGust/windDirection time series.
    `fetch_forecast.py` pulls only those three properties (the full grid
    response is ~50x bigger and covers dozens of fields this project has no
    use for) and converts km/h to mph at fetch time.
  - Each value is reduced over the same day+night window as a card's
    high/low (`col["day_start"]` through `col["night_end"]`, i.e. this day's
    6am-6pm plus the night immediately following) via `reduce_grid_window()`:
    minimum and maximum sustained speed for the range, maximum for the gust.
    The gridpoints feed's values come as `start/duration` intervals
    (`parse_valid_time()`/`parse_iso8601_duration()` parse NWS's ISO8601
    format), not point samples, so the reduction is over every interval that
    overlaps the window rather than an exact-match lookup. All three are
    rounded to the nearest 5mph (`round_to_5_mph()`) for display — precision
    NWS's own gridded wind data doesn't really support anyway.
  - **Direction** is whichever compass point (`N`/`NE`/`E`/`SE`/`S`/`SW`/`W`/`NW`
    — 8-point, not 16-point, since a single/double-letter label was wanted)
    covers the most hours of the window (`dominant_wind_direction()`),
    rather than a single sample, since direction can shift over a day.
  - Blank (no wind row at all) when neither threshold is crossed, same as
    the precip indicator being blank below 20% — the reserved vertical zone
    just stays empty rather than the layout shifting to fill it.
- Chart styling (fonts, colors, dimensions, logo placement) mirrors
  `columbia-basin-alerts-map/build_map.py` — edit `build_graphic.py`
  directly to adjust.
