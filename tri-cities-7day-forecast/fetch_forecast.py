"""
Fetches the current NWS 7-day forecast (day/night periods, temperatures,
icon codes) for a point and writes forecast.json. Run this before
build_graphic.py any time you want the graphic to reflect the latest
forecast package.

No API key needed -- api.weather.gov is free, but requires a User-Agent
identifying the requester.
"""
import argparse
import json

import requests

HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189
DEFAULT_LABEL = "Tri-Cities, WA"


def fetch(lat, lon):
    points = requests.get(f"https://api.weather.gov/points/{lat},{lon}",
                           headers=HEADERS, timeout=30)
    points.raise_for_status()
    point_props = points.json()["properties"]

    forecast = requests.get(point_props["forecast"], headers=HEADERS, timeout=30)
    forecast.raise_for_status()
    data = forecast.json()
    data["timezone"] = point_props["timeZone"]
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--label", default=DEFAULT_LABEL,
                     help="Human-readable location shown in the graphic title")
    ap.add_argument("--output", default="forecast.json")
    args = ap.parse_args()

    data = fetch(args.lat, args.lon)
    data["label"] = args.label
    data["lat"] = args.lat
    data["lon"] = args.lon

    with open(args.output, "w") as f:
        json.dump(data, f)

    n_periods = len(data["properties"]["periods"])
    print(f"Saved {args.output}: {n_periods} periods for {args.label} "
          f"(updated {data['properties'].get('updateTime')}, timezone {data['timezone']})")
