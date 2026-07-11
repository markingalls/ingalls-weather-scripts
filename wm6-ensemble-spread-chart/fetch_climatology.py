"""
Fetches 1991-2020 monthly climatology (mean) for air temperature at a given
pressure level and point from the NCEP/NCAR Reanalysis 1, served by NOAA
PSL's public OPeNDAP endpoint. Writes climatology.json. This has nothing to
do with the current model run, so it only needs to be re-run if you change
location/level, or want to refresh it against a newer climate normal period.

Data source: air.mon.mean.nc (monthly means, 1948-present, 2.5-degree grid)
at https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/
We pull each calendar month's 1991-2020 time series directly via OPeNDAP
array slicing (12 small requests) rather than downloading the full file, and
average it ourselves -- this matches NOAA's own published long-term monthly
normals. build_chart.py fits a smooth annual-cycle curve through these 12
points rather than plotting them as a stepped monthly series.

No API key required.
"""
import argparse
import json
import re
import statistics

import requests

BASE_URL = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/pressure/air.mon.mean.nc"

# Pressure levels available in this dataset, in on-disk order.
LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10]

BASE_YEAR = 1948  # first year in air.mon.mean.nc's time dimension
CLIMO_START_YEAR = 1991
CLIMO_END_YEAR = 2020

VALUE_RE = re.compile(r"\[(\d+)\]\[0\]\[0\],\s*(-?[\d.]+)")


def nearest_index(value, first, step, count):
    idx = round((value - first) / step)
    return max(0, min(count - 1, idx))


def grid_indices(lat, lon, level):
    lat_idx = nearest_index(lat, 90, -2.5, 73)        # lat runs 90 -> -90
    lon_idx = nearest_index(lon % 360, 0, 2.5, 144)   # lon runs 0 -> 357.5 east
    level_idx = min(range(len(LEVELS)), key=lambda i: abs(LEVELS[i] - level))
    return lat_idx, lon_idx, level_idx


def fetch_month(level_idx, lat_idx, lon_idx, month):
    """1991-2020 (30 years) of monthly-mean values for one calendar month,
    pulled server-side via OPeNDAP array striding so we never download the
    ~270MB file itself."""
    n_years = CLIMO_END_YEAR - CLIMO_START_YEAR + 1
    start = (CLIMO_START_YEAR - BASE_YEAR) * 12 + (month - 1)
    end = (CLIMO_END_YEAR - BASE_YEAR) * 12 + (month - 1)
    url = (f"{BASE_URL}.ascii?air[{start}:12:{end}][{level_idx}:1:{level_idx}]"
           f"[{lat_idx}:1:{lat_idx}][{lon_idx}:1:{lon_idx}]")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    values = [float(v) for _, v in VALUE_RE.findall(r.text)]
    if len(values) != n_years:
        raise RuntimeError(f"Expected {n_years} years for month {month}, got {len(values)}")
    return values


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--level", type=int, default=850, help="Pressure level in hPa")
    ap.add_argument("--output", default="climatology.json")
    args = ap.parse_args()

    lat_idx, lon_idx, level_idx = grid_indices(args.lat, args.lon, args.level)

    monthly = []
    for month in range(1, 13):
        years = fetch_month(level_idx, lat_idx, lon_idx, month)
        mean = statistics.fmean(years)
        monthly.append({"month": month, "mean": round(mean, 3)})
        print(f"  month {month:2d}: mean {mean:6.2f} C ({len(years)} yrs)")

    out = {
        "source": "NCEP/NCAR Reanalysis 1 (NOAA PSL), nearest 2.5-degree grid point",
        "period": f"{CLIMO_START_YEAR}-{CLIMO_END_YEAR}",
        "level": LEVELS[level_idx],
        "grid_lat": 90 - lat_idx * 2.5,
        "grid_lon": lon_idx * 2.5,
        "monthly": monthly,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved {args.output} (grid point {out['grid_lat']}N, {out['grid_lon']}E, {out['level']} hPa)")
