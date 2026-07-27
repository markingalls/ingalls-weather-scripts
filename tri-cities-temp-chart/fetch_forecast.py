"""
Fetches WindBorne WeatherMesh-6 (WM-6) forecast daily high temperatures for
the next N days at a point and writes forecast.json. Run this any time you
want the chart to reflect the latest model run.

A day's forecast high is the max of WM-6's point-forecast temperature_2m
samples (native 3-hourly cadence) falling in the 8am-8pm local window --
same daytime-high definition used by columbia-basin-temps/build_map.py's
"high" metric, so this chart's forecast segment and that project's maps
stay consistent with each other.

Requires WB_API_KEY in the environment. Get a key at
https://app.windbornesystems.com/api_tokens.
"""
import argparse
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

API_URL = "https://api.windbornesystems.com/forecasts/v1/wm-6/point_forecast/interpolated"

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189
DEFAULT_STATION = "KPSC"
DEFAULT_LABEL = "Pasco, WA"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
HIGH_WINDOW = (8, 20)  # local hours


def c_to_f(c):
    return c * 9 / 5 + 32


def fetch(lat, lon, max_forecast_hour):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")
    params = {
        "coordinates": f"{lat},{lon}",
        "variable": "temperature_2m",
        "max_forecast_hour": max_forecast_hour,
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
    ap.add_argument("--days", type=int, default=7, help="Number of forecast days, starting today")
    ap.add_argument("--output", default="forecast.json")
    args = ap.parse_args()

    label = args.label
    if label is None and args.station == DEFAULT_STATION:
        label = DEFAULT_LABEL

    # +1 day of buffer past the requested window, since 8pm local on the
    # last requested day can fall into the next UTC calendar day.
    data = fetch(args.lat, args.lon, (args.days + 1) * 24)
    points = data["forecasts"][0]

    by_local_date = {}
    for p in points:
        t_local = datetime.fromisoformat(p["time"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        if HIGH_WINDOW[0] <= t_local.hour <= HIGH_WINDOW[1]:
            by_local_date.setdefault(t_local.date(), []).append(p["temperature_2m"])

    today_local = datetime.now(LOCAL_TZ).date()
    days_out = []
    for d in sorted(by_local_date):
        if not (today_local <= d < today_local + timedelta(days=args.days)):
            continue
        temps_c = by_local_date[d]
        days_out.append({
            "date": d.isoformat(),
            "maxt_f": round(c_to_f(max(temps_c)), 1),
            "n_samples": len(temps_c),
        })

    out = {
        "source": "WindBorne WeatherMesh-6 (WM-6), temperature_2m, 8am-8pm local max",
        "station": args.station,
        "label": label,
        "lat": args.lat,
        "lon": args.lon,
        "initialization_time": data["initialization_time"],
        "days": days_out,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {args.output}: {len(days_out)} forecast days for {args.station} "
          f"(init {data['initialization_time']})")
