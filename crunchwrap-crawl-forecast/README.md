# Crunchwrap Crawl Race-Day Forecast

A taco-shop-themed spin on [`tri-cities-7day-forecast/`](../tri-cities-7day-forecast/),
built from [`halloween-trick-or-treat-forecast/`](../halloween-trick-or-treat-forecast/):
three cards for the Tri-Cities Crunchwrap Crawl, one per key moment of the
race:

| Card | Default | Why |
|---|---|---|
| **START** | 08:00 | gun time |
| **LAST YEAR WINNER - 4:59:24** | start + 4:59:24 (12:59) | where last year's winner would cross the line |
| **CUTOFF - 12:00:00** | start + 12:00:00 (20:00) | the time limit, where the last finishers are |

The card shows the actual clock time (12:59), but the weather on it comes
from the nearest top of the hour (13:00), since every feed here is hourly.

Deep purple background, white cards, magenta/cheese accents, a grilled
hexagonal crunchwrap with hot-sauce packets, tacos, and a checkered
finish-line strip. All of it is drawn in matplotlib from plain shapes and
food colors. It deliberately uses **no restaurant logos or slogans**, which
are trademarked and would make this read as an official or sponsored
graphic.

## Usage

```bash
bash setup.sh                 # first time / fresh environment only
export WB_API_KEY=...         # optional -- MetaMesh temps; NWS hourly otherwise

python3 fetch_forecast.py
python3 build_graphic.py      # -> crunchwrap_crawl_forecast.png

# Different date/start/record/limit
python3 build_graphic.py --date 2027-11-06 --start 07:30 --winner 4:52:10 --limit 12:00:00
```

`--date` defaults to the coming Saturday (today, if run on a Saturday).
`fetch_forecast.py` takes `--lat`/`--lon`/`--label`/`--station` like the
7-day's fetch scripts, defaulting to KPSC.

## Data

Same sources and per-frame logic as `halloween-trick-or-treat-forecast/`
(see its README for detail): NWS hourly conditions with night icons after
dark, MetaMesh temperature and feels-like (NWS fallback without a key),
chance of precip from the 50-member ECMWF ensemble over the 2 hours centered
on each card, and NWS wind/gusts. Differences:

- **Sunrise and sunset** are both shown (a race spans the whole day), and
  the light label covers `BEFORE DAWN`/`DAWN` as well as
  `DAYLIGHT`/`DUSK`/`AFTER DARK`.
- **Runner tips** (`runner_tips()`) replace the costume tips. They're keyed
  to feels-like but run about 15–20° lighter than what you'd tell a
  spectator, since runners warm up fast. Below that is a second nudge: pack a
  light shell for a lower rain chance, gusts of 25 mph or more, a headlamp
  and reflective gear in the dark, or a throwaway layer at a cold start.
- `fetch_forecast.py` retries Open-Meteo on HTTP 429. The free tier
  rate-limits per egress IP, and shared cloud IPs trip it intermittently.
