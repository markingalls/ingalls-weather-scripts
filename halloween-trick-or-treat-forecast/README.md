# Halloween Trick-or-Treat Forecast

A Halloween-themed spin on [`tri-cities-7day-forecast/`](../tri-cities-7day-forecast/):
instead of seven day cards, three time-of-day cards (default **4 PM, 6 PM,
and 8 PM** local) for trick-or-treat night, on a dark night-sky background
with a full moon, bats, and jack-o'-lanterns. Same canvas size, fonts,
logo placement, icon font, and card layout conventions as the 7-day.

Preset locations (each one's airport ASOS, so NWS/ECMWF/MetaMesh all
describe the same spot):

| `--location` | Point | MetaMesh station |
|---|---|---|
| `tri-cities` | KPSC, Pasco, WA | `kpsc` |
| `yakima` | KYKM, Yakima, WA | `kykm` |
| `hermiston` | KHRI, Hermiston, OR | `khri` |

## Usage

```bash
bash setup.sh                 # first time / fresh environment only
export WB_API_KEY=...         # optional -- see "Temperature" below

for loc in tri-cities yakima hermiston; do
  python3 fetch_forecast.py --location $loc
  python3 build_graphic.py --location $loc
done
# -> tri_cities_trick_or_treat_forecast.png, yakima_..., hermiston_...

# Other dates/times
python3 build_graphic.py --location yakima --date 2026-10-31 --hours 17 19 21
```

`--date` defaults to **tomorrow** in the location's own timezone (meant to
be run the evening before Halloween); the forecast feeds only reach a few
days out, so render within ~3 days of the target date.

## What each card shows

- **Time** and a **light label** — `DAYLIGHT` before sunset, `DUSK` within
  35 minutes after (civil twilight this far north in late October),
  `AFTER DARK` past that. The dusk/dark cards get a pumpkin-orange outline.
  Sunset itself (in the subtitle) is computed from NOAA's solar equations
  in `sunset_local()` — accurate to about a minute, no extra dependency.
- **Condition icon + text** from the NWS hourly forecast at that hour. NWS's
  own day/night flag picks the glyph: after dark, sun glyphs swap to their
  moon twin (the icon font places each night glyph at the day glyph's
  codepoint + 1). Overcast uses a plain cloud with no sun or moon, unlike
  the 7-day's `CLOUDYday`, which reads wrong next to "Cloudy" at night.
- **Temperature** — MetaMesh `temperature_2m` at that exact hour when
  `WB_API_KEY` is set and MetaMesh covers the station; otherwise NWS's
  own hourly temperature. The attribution line reads `NWS/ECMWF/WM-6` only
  when all three cards came from MetaMesh.
- **Feels like** — from the same source as the temperature: MetaMesh's
  `apparent_temperature` alongside a MetaMesh temp, otherwise NWS gridpoints
  `apparentTemperature`. Mixing the two put "feels like" above the actual
  temperature on a cool evening.
- **Chance of precip** — the share of the 50 ECMWF IFS ensemble members
  (Open-Meteo) with more than 0.25 mm (~0.01") in the 2 hours centered on
  the card's time, rain vs. snow by the median member's snowfall. It is
  hidden below 20%, and at 70% or higher it replaces the condition icon
  with plain rain/snow. These are the same thresholds the 7-day uses, applied
  to a window that fits a walk around the neighborhood.
- **Wind** — NWS hourly speed/direction (rounded to 5 mph, "Calm" at 0),
  plus gusts from the gridpoints feed when over 20 mph.
- **Costume tips** — up to two lines from `costume_tips()`: a what-to-wear
  line keyed to feels-like temperature (or rain/snow gear at ≥50% precip),
  then "umbrella just in case" for a lower precip chance, a hat warning for
  gusts ≥25 mph, or a glow-stick/flashlight reminder once it's dark.
