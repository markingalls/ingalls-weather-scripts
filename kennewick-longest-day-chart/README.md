# "Longest Day of the Year" DST Chart (Kennewick, WA)

A styled 4:5 portrait chart (1600×2000, Instagram feed size) for the
fall-back weekend. It shows three days in
Kennewick as horizontal bars on a shared 25-hour track. Each bar is drawn
to its true length and shaded night/day by actual sunrise and sunset. The
hours a shorter day doesn't have show as a hatched gray stub:

| Bar | Day (default) | Length |
|---|---|---|
| Top | Sun, Nov 1, 2026 (fall back) | 25 h. The repeated 01:00 hour is outlined |
| Middle | Mon, Jun 21, 2027 (summer solstice) | 24 h, most daylight of the year |
| Bottom | Sun, Mar 14, 2027 (spring forward) | 23 h. The skipped 02:00 is marked |

## Usage

```bash
bash setup.sh                        # first time / fresh environment only
python3 build_chart.py               # -> output/longest_day_2026.png
python3 build_chart.py --fall-year 2027
```

## Method

- Dates are computed, not hard-coded:
  - fall back: first Sunday of November
  - spring forward: second Sunday of March in the following year
  - June solstice: Meeus' solstice polynomial for the following year
- Day length is the time between consecutive local midnights in
  `America/Los_Angeles`, straight from the tz database. Every hour tick is
  labelled with the local clock time at that instant, so the doubled "01"
  and the missing "02" come from the data.
- Sunrise and sunset use the NOAA solar equations, the same as
  `../pnw-sunrise-map/`: upper limb on a sea-level horizon, −0.833°
  refraction, terrain ignored. Times are rounded to the nearest minute and
  agree with the `astral` package within a minute.
