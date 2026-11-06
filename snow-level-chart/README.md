# Snow Level Charts

Generates a styled 5-day snow level chart for a mountain pass or ski area,
for Ingalls Weather's Instagram. Same canvas footprint, fonts, and logo
placement as the [850/700 mb temp chart](../850-700-temp-chart/).

Two sites are built in (see `sites.py`):

- **`snoqualmie`** — Snoqualmie Pass, with a dotted line at pass level
  (3,022 ft).
- **`hood`** — Mount Hood, with dotted lines at Government Camp (3,980 ft),
  Mt. Hood Meadows base (4,523 ft), and Timberline Lodge (5,960 ft).

Each chart shows the WindBorne WeatherMesh-6 snow level (solid blue), with
the area above it tinted as "snow".

## Files

- `sites.py` — site definitions: the point the model profile is pulled at,
  the chart title, and the reference lines (label + elevation in feet).
  Optional `label_fontsize` per site and `label_below` per line control the
  labels (Mount Hood uses both, since its three lines sit close together).
  Add a site here to chart somewhere new.
- `fetch_forecast.py` — pulls WM-6 temperature + geopotential on every
  pressure level from 1000 to 500 mb (13 requests) for one site and writes
  `forecast_<site>.json`. Requires `WB_API_KEY`
  (https://app.windbornesystems.com/api_tokens).
- `build_chart.py` — derives the snow level from the profile and renders
  `snow_level_<site>.png`.
- `requirements.txt` / `setup.sh` — Python dependencies. Poppins needs
  installing too (see `../columbia-basin-alerts-map/setup.sh`).

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export WB_API_KEY=...              # your WindBorne API key

python3 fetch_forecast.py --site snoqualmie
python3 build_chart.py --site snoqualmie

python3 fetch_forecast.py --site hood
python3 build_chart.py --site hood

# Options
python3 build_chart.py --site hood --days 3    # shorter window
```

## Method

WM-6 has no snow level field, so `build_chart.py` builds one from the
model's vertical temperature profile at each 3-hourly step:

1. Convert each pressure level's geopotential (m²/s²) to height (÷ 9.80665).
2. Scan from the top of the column down to find the **highest height where
   the air is still ≥ +1.6 °C**, interpolating linearly between levels.
   That's the snow level. 1.6 °C is where precipitation is ~50% snow by mass
   on a Cascades-tuned air-temperature snow-fraction curve; the 0 °C
   freezing level typically sits ~1,000 ft above it.
3. If the whole column is colder than that, the snow level is plotted at
   0 ft (sea level).

Scanning from the top means a shallow warm layer aloft resolves to the top of
the warm air, and a cold pool trapped in the lowest levels (e.g. east-side
cold air in a pass) doesn't drag the snow level down.

## Notes

- **This is a temperature-only snow level.** It doesn't include the cooling
  from melting and evaporation that heavy precipitation brings, and the
  profile comes from a ~25 km grid that can't resolve cold air pooled in a
  pass. Expect it to run high compared with the NWS snow level in dry or
  showery warm periods, and to agree more closely during steady
  precipitation.
- Times on the x-axis are Pacific time (labelled ticks at local midnight).
- The y-axis runs from 0 ft to the highest data or reference line, rounded
  up to the next 1,000 ft with some headroom.
- Reference elevations: Snoqualmie Pass 3,022 ft (as requested);
  Government Camp 3,980 ft, Mt. Hood Meadows base 4,523 ft, and Timberline
  Lodge 5,960 ft are commonly published figures. Edit `sites.py` to change
  them.
