"""
Fetches Open-Meteo's ECMWF IFS ensemble (50 members) hourly precipitation
and snowfall for a point and writes ecmwf_ensemble_forecast.json. Used by
build_graphic.py to derive each day's chance of precip (fraction of members
whose daily total exceeds 0.5mm) and its P25-P75 rainfall/snowfall total.

WM-6's own precipitation variable (total_precipitation_3h) was tried first,
but its distribution only exposes fixed threshold-exceedance probabilities
(gt_0p25mm, gt_2p5mm, gt_6mm, gt_12p5mm, gt_25mm, gt_50mm) and mean/std --
no percentiles, no raw members, and no 0.5mm threshold -- confirmed directly
against the live API, not assumed. Open-Meteo's ensemble endpoint instead
exposes all 50 raw ECMWF members per variable, so an exact 0.5mm threshold
and a real P25/P75 can both be computed directly from them. No API key
needed.
"""
import argparse
import json

import requests

API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189


def fetch(lat, lon, forecast_days):
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,snowfall",
        "timezone": "auto",  # resolves to the point's own local timezone
        "forecast_days": forecast_days,
    }
    r = requests.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--forecast-days", type=int, default=10,
                     help="Only 7-8 days actually get used, but a little slack keeps "
                          "this from coming up short")
    ap.add_argument("--output", default="ecmwf_ensemble_forecast.json")
    args = ap.parse_args()

    data = fetch(args.lat, args.lon, args.forecast_days)

    with open(args.output, "w") as f:
        json.dump(data, f)

    hourly = data["hourly"]
    n_members = sum(1 for k in hourly if k.startswith("precipitation_member"))
    print(f"Saved {args.output}: {len(hourly['time'])} hourly steps, "
          f"{n_members} ensemble members, at {args.lat},{args.lon} "
          f"(timezone {data['timezone']})")
