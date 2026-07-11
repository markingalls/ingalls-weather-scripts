"""
Fetches the 1991-2020 long-term-mean climatology, at full 6-hourly (four
times daily -- 00/06/12/18Z) precision, for air temperature at a given
pressure level and point from the NCEP/NCAR Reanalysis 1, served by NOAA
PSL's public OPeNDAP endpoint. Writes climatology.json. This has nothing to
do with the current model run, so it only needs to be re-run if you change
location/level, or want to refresh it against a newer climate normal period.

Data source: air.4Xday.ltm.1991-2020.nc -- NOAA's own precomputed 1991-2020
long-term mean at 6-hourly resolution (365 days x 4 obs/day = 1460 points),
covering a synthetic non-leap reference year. This already *is* the 30-year
average (not raw per-year data), so unlike the old monthly-mean approach we
don't need to average years ourselves -- one small OPeNDAP request for the
whole year at our grid point gets the full-precision series. Because it's
long-term-meaned at each 6-hour slot rather than daily/monthly-averaged
first, the seasonal cycle *and* the diurnal cycle are both preserved --
build_chart.py fits smooth harmonics through this raw series (annual +
semiannual for the seasonal trend, plus diurnal + semidiurnal for the daily
bumps) rather than plotting the raw 1460 points directly.

No API key required.
"""
import argparse
import json
import re

import requests

BASE_URL = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/air.4Xday.ltm.1991-2020.nc"

# Pressure levels available in this dataset, in on-disk order.
LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10]

CLIMO_PERIOD = "1991-2020"
N_TIMESTEPS = 1460  # 365 days x 4 obs/day (00/06/12/18Z), non-leap reference year
HOURS_PER_STEP = 6

VALUE_RE = re.compile(r"\[(\d+)\]\[0\]\[0\],\s*(-?[\d.]+)")


def nearest_index(value, first, step, count):
    idx = round((value - first) / step)
    return max(0, min(count - 1, idx))


def grid_indices(lat, lon, level):
    lat_idx = nearest_index(lat, 90, -2.5, 73)        # lat runs 90 -> -90
    lon_idx = nearest_index(lon % 360, 0, 2.5, 144)   # lon runs 0 -> 357.5 east
    level_idx = min(range(len(LEVELS)), key=lambda i: abs(LEVELS[i] - level))
    return lat_idx, lon_idx, level_idx


def fetch_series(level_idx, lat_idx, lon_idx):
    """The full 1460-point (6-hourly, 1991-2020 long-term mean) annual cycle
    at one grid point, pulled server-side via OPeNDAP so we never download
    the full multi-point file."""
    url = (f"{BASE_URL}.ascii?air[0:1:{N_TIMESTEPS - 1}][{level_idx}:1:{level_idx}]"
           f"[{lat_idx}:1:{lat_idx}][{lon_idx}:1:{lon_idx}]")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    values_k = [float(v) for _, v in VALUE_RE.findall(r.text)]
    if len(values_k) != N_TIMESTEPS:
        raise RuntimeError(f"Expected {N_TIMESTEPS} timesteps, got {len(values_k)}")
    return [round(v - 273.15, 3) for v in values_k]  # degK -> degC


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--level", type=int, default=850, help="Pressure level in hPa")
    ap.add_argument("--output", default="climatology.json")
    args = ap.parse_args()

    lat_idx, lon_idx, level_idx = grid_indices(args.lat, args.lon, args.level)

    values = fetch_series(level_idx, lat_idx, lon_idx)
    # t_days: fractional day-of-year (0.0 = Jan 1 00Z) for each 6-hourly slot.
    t_days = [i * HOURS_PER_STEP / 24 for i in range(N_TIMESTEPS)]

    print(f"  fetched {len(values)} six-hourly points, "
          f"range {min(values):.2f} C .. {max(values):.2f} C")

    out = {
        "source": "NCEP/NCAR Reanalysis 1 (NOAA PSL), nearest 2.5-degree grid point, "
                   "6-hourly long-term mean",
        "period": CLIMO_PERIOD,
        "level": LEVELS[level_idx],
        "grid_lat": 90 - lat_idx * 2.5,
        "grid_lon": lon_idx * 2.5,
        "hours_per_step": HOURS_PER_STEP,
        "t_days": t_days,
        "mean_c": values,
    }
    with open(args.output, "w") as f:
        json.dump(out, f)
    print(f"Saved {args.output} (grid point {out['grid_lat']}N, {out['grid_lon']}E, {out['level']} hPa)")
