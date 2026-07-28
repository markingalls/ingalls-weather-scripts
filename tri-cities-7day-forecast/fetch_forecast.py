"""
Fetches the current NWS 7-day forecast (day/night periods, temperatures,
icon codes) for a point and writes forecast.json. Run this before
build_graphic.py any time you want the graphic to reflect the latest
forecast package.

Also fetches windSpeed/windGust/windDirection from the same point's raw
gridpoints data (forecastGridData) -- the human-readable periods above carry
a windSpeed range but no windGust field at all, so the wind indicator needs
this separate, finer-grained feed. Only those three properties are kept
(the full grid response is ~50x bigger and covers dozens of fields this
project doesn't use); values come back in km/h and are converted to mph
here so build_graphic.py never has to think about units.

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

KM_H_TO_MPH = 0.621371


def _convert_speeds(values):
    return [{"validTime": v["validTime"],
              "value": v["value"] * KM_H_TO_MPH if v["value"] is not None else None}
             for v in values]


def fetch(lat, lon):
    points = requests.get(f"https://api.weather.gov/points/{lat},{lon}",
                           headers=HEADERS, timeout=30)
    points.raise_for_status()
    point_props = points.json()["properties"]

    forecast = requests.get(point_props["forecast"], headers=HEADERS, timeout=30)
    forecast.raise_for_status()
    data = forecast.json()
    data["timezone"] = point_props["timeZone"]

    grid = requests.get(point_props["forecastGridData"], headers=HEADERS, timeout=30)
    grid.raise_for_status()
    grid_props = grid.json()["properties"]
    data["wind"] = {
        "speed": _convert_speeds(grid_props["windSpeed"]["values"]),
        "gust": _convert_speeds(grid_props["windGust"]["values"]),
        "direction": grid_props["windDirection"]["values"],  # degrees, no conversion needed
    }
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
