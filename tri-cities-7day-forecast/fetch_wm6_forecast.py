"""
Fetches the WM-6 ensemble 2m-temperature distribution forecast for a single
point from WindBorne and writes wm6_forecast.json. Run this alongside
fetch_forecast.py (which supplies the day/night structure and NWS condition
icons) any time you want the graphic's high/low numbers to reflect the
latest model run.

Requires WB_API_KEY to be set in the environment. Get a key at
https://app.windbornesystems.com/api_tokens.
"""
import argparse
import json
import os

import requests

API_URL = "https://api.windbornesystems.com/forecasts/v1/wm-6/point_forecast/interpolated"

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189


def fetch(lat, lon, max_hour):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")
    params = {
        "coordinates": f"{lat},{lon}",
        "variable": "temperature_2m",
        "include_distribution": "true",
        "max_forecast_hour": max_hour,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(API_URL, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--max-hour", type=int, default=180,
                     help="Max forecast hour to request (needs to clear 7 days of "
                          "day+night periods with room to spare)")
    ap.add_argument("--output", default="wm6_forecast.json")
    args = ap.parse_args()

    data = fetch(args.lat, args.lon, args.max_hour)

    with open(args.output, "w") as f:
        json.dump(data, f)

    n_points = len(data["forecasts"][0]) if data.get("forecasts") else 0
    print(f"Saved {args.output}: {n_points} timesteps at {args.lat},{args.lon} "
          f"(init {data.get('initialization_time')})")
