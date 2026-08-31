"""
Fetches today's NWS forecast high temperature for a point and writes
forecast.json. build_chart.py uses this (if present) to extend the y-axis
to cover today's forecast high, for the part of the day the Tempest
station's own observations haven't reached yet.

No API key needed -- api.weather.gov is free, but requires a User-Agent
identifying the requester.
"""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}

# Default point: Highland Hills, this project's default Tempest station
# (see fetch_tempest.py's STATION_LABEL_OVERRIDES) -- Hermiston, OR area.
DEFAULT_LAT = 45.83553
DEFAULT_LON = -119.271


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
    ap.add_argument("--output", default="forecast.json")
    args = ap.parse_args()

    data = fetch(args.lat, args.lon)
    tz = ZoneInfo(data["timezone"])
    today = datetime.now(tz).date()

    # NWS periods alternate day/night starting from whichever is current --
    # once today's daytime period has scrolled off (it's evening and the
    # next daytime period is tomorrow's), there's no forecast high left to
    # report for today; the observed max is already the real one by then.
    today_period = next(
        (p for p in data["properties"]["periods"]
         if p["isDaytime"] and datetime.fromisoformat(p["startTime"]).astimezone(tz).date() == today),
        None,
    )

    out = {
        "source": "NWS api.weather.gov forecast (day/night periods)",
        "lat": args.lat,
        "lon": args.lon,
        "timezone": data["timezone"],
        "date": today.isoformat(),
        "period_name": today_period["name"] if today_period else None,
        "forecast_high_f": today_period["temperature"] if today_period else None,
        "updated": data["properties"].get("updateTime"),
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    if today_period:
        print(f"Saved {args.output}: {out['period_name']} forecast high {out['forecast_high_f']}°F")
    else:
        print(f"Saved {args.output}: no daytime forecast period left for {today} "
              f"(already past today's daytime window)")
