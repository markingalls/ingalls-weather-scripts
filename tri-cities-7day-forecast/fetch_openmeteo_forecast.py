"""
Fetches Open-Meteo's daily weather-code forecast for a point and writes
openmeteo_forecast.json. Open-Meteo forecasts out to 16 days, well past
NWS's ~7-day coverage, so this exists only to backfill a condition icon for
the one extra day build_graphic.py adds when the forecast window shifts to
start tomorrow (renders after 3pm local -- see README). No API key needed.
"""
import argparse
import json

import requests

API_URL = "https://api.open-meteo.com/v1/forecast"

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189


def fetch(lat, lon, forecast_days):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "weathercode",
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
                     help="Only the day beyond NWS's own coverage actually gets used, "
                          "but a little slack keeps this from coming up short")
    ap.add_argument("--output", default="openmeteo_forecast.json")
    args = ap.parse_args()

    data = fetch(args.lat, args.lon, args.forecast_days)

    with open(args.output, "w") as f:
        json.dump(data, f)

    n_days = len(data["daily"]["time"])
    print(f"Saved {args.output}: {n_days} days at {args.lat},{args.lon} "
          f"(timezone {data['timezone']})")
