# Thanksgiving Forecast

An autumn-themed spin on [`tri-cities-7day-forecast/`](../tri-cities-7day-forecast/),
built from [`crunchwrap-crawl-forecast/`](../crunchwrap-crawl-forecast/):
four cards across Thanksgiving Day in the Tri-Cities.

| Card | Default |
|---|---|
| **TURKEY TROT** | 07:00 |
| **TRAVEL + PREP** | 11:00 |
| **DINNER TIME** | 15:00 |
| **PIE + LEFTOVERS** | 19:00 |

The theme uses a deep roasted-brown background, cream cards, and burnt-orange,
gold and cranberry accents. Decorations are a cartoon turkey, maple leaves,
pumpkin pies, and a row of fallen leaves along the bottom. All of it is drawn
in matplotlib from plain shapes.

## Usage

```bash
bash setup.sh                 # first time / fresh environment only
export WB_API_KEY=...         # optional -- MetaMesh temps; NWS hourly otherwise

python3 fetch_forecast.py
python3 build_graphic.py      # -> thanksgiving_forecast.png

# Other hours/labels
python3 fetch_forecast.py --hours 8 12 16 20
python3 build_graphic.py --hours 8 12 16 20 --labels "Trot" "Kickoff" "Dinner" "Pie"
```

`--date` defaults to this year's Thanksgiving (the fourth Thursday of
November), or next year's once it has passed. `--labels` takes one label per
`--hours` entry. `fetch_forecast.py` takes `--lat`/`--lon`/`--label`/`--station`
like the 7-day's fetch scripts, defaulting to KPSC.

## Data

The sources and per-card logic are the same as `crunchwrap-crawl-forecast/`
and `halloween-trick-or-treat-forecast/`:

- NWS hourly conditions, with night icons after dark.
- MetaMesh temperature and feels-like, falling back to NWS without a key.
- Chance of precip from the 50-member ECMWF ensemble, over the 2 hours
  centered on each card.
- NWS sustained wind and direction.
- **Gusts from NOAA RRFS** (3km CONUS, `GUST:surface`) at each card's hour.
  `fetch_forecast.py` picks the newest 00/06/12/18Z cycle, which runs to
  84h, that NOMADS has already published far enough out. It then
  byte-range downloads just the gust record (about 1.2 MB) from each hour's
  GRIB2 file and takes the grid point nearest KPSC. It falls back to NWS's
  gridded gusts if RRFS can't be reached, and adds RRFS to the attribution
  line when it's used. Pass the same `--date`/`--hours` to
  `fetch_forecast.py` as to `build_graphic.py`.
- Sunrise and sunset from NOAA's solar equations, which drive the
  `BEFORE DAWN`/`DAWN`/`DAYLIGHT`/`DUSK`/`AFTER DARK` label.

**Holiday tips** (`holiday_tips()`) replace the costume and runner tips.

The first line is what to wear, keyed to feels-like. When the precip chance
is 50% or higher, it's rain or snow gear instead.

The second line is one nudge, in this priority order:

1. Fog on the roads, or freezing fog at 32° and below. Fog is common in the
   Tri-Cities' late-November inversions.
2. Umbrella or road caution when the precip chance is lower.
3. A turkey-fryer warning when wind or gusts reach 15 mph or more.
4. Headlights at dawn, at dusk, or in the dark.

**Layout:** the rain/snow chance is centered as one icon-plus-label unit, and
it's left blank when there's no chance. Wind is always on the row beneath
it, so it lines up across all four cards.
