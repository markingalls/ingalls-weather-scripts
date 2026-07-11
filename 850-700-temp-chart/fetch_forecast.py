"""
Fetches the WM-6 ensemble distribution forecast (mean, percentiles, std) for
a single point/level from WindBorne and writes forecast.json. Run this
before build_chart.py any time you want the chart to reflect the latest
model run.

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
DEFAULT_STATION = "KPSC"
DEFAULT_LABEL = "Pasco, WA"


def fetch(lat, lon, level, max_hour):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")
    params = {
        "coordinates": f"{lat},{lon}",
        "variable": "temperature",
        "level": level,
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
    ap.add_argument("--station", default=DEFAULT_STATION,
                     help="Short station identifier shown in the chart title, e.g. KPSC")
    ap.add_argument("--label", default=None,
                     help="Human-readable location, e.g. 'Pasco, WA' (defaults to blank unless --station is left at KPSC)")
    ap.add_argument("--level", type=int, default=850, help="Pressure level in hPa")
    ap.add_argument("--max-hour", type=int, default=360,
                     help="Max forecast hour to request (WM-6 ensemble runs out to 360h / 15 days)")
    ap.add_argument("--output", default="forecast.json")
    args = ap.parse_args()

    label = args.label
    if label is None and args.station == DEFAULT_STATION:
        label = DEFAULT_LABEL

    data = fetch(args.lat, args.lon, args.level, args.max_hour)
    data["station"] = args.station
    data["label"] = label
    data["lat"] = args.lat
    data["lon"] = args.lon
    data["level"] = args.level

    with open(args.output, "w") as f:
        json.dump(data, f)

    n_points = len(data["forecasts"][0]) if data.get("forecasts") else 0
    print(f"Saved {args.output}: {n_points} timesteps for {args.station} at {args.level} hPa "
          f"(init {data.get('initialization_time')})")
