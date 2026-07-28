"""
Fetches the MetaMesh deterministic point forecast (temperature_2m) for a
station from WindBorne and writes metamesh_forecast.json. MetaMesh blends
NOAA (HRRR, GFS), ECMWF (IFS, AIFS), and WindBorne's own models with
station-specific bias correction for its 349 supported METAR stations, so
this queries by station identifier (KPSC) rather than by lat/lon. Run this
alongside fetch_forecast.py (which supplies the day/night structure and NWS
condition icons) any time you want the graphic's high/low numbers to
reflect the latest model run.

Requires WB_API_KEY (same WindBorne account/key as WM-6). Get one at
https://app.windbornesystems.com/api_tokens.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import requests

# Bare point_forecast (no model segment in the path) is hard-coded to serve
# MetaMesh -- confirmed directly against the API, since this isn't
# documented anywhere public. /forecasts/v1/<model>/point_forecast is the
# general form for picking a different model (e.g. wm-6).
API_URL = "https://api.windbornesystems.com/forecasts/v1/point_forecast"

DEFAULT_STATION = "kpsc"  # Tri-Cities Airport, Pasco, WA


def fetch(station, max_days):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")
    now = datetime.now(timezone.utc)
    params = {
        "stations": station,
        "min_forecast_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_forecast_time": (now + timedelta(days=max_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(API_URL, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station", default=DEFAULT_STATION,
                     help="ICAO identifier, one of MetaMesh's 349 supported METAR stations")
    ap.add_argument("--max-days", type=int, default=8,
                     help="How many days out to request (needs to clear 7 days of "
                          "day+night periods with room to spare)")
    ap.add_argument("--output", default="metamesh_forecast.json")
    args = ap.parse_args()

    data = fetch(args.station, args.max_days)

    with open(args.output, "w") as f:
        json.dump(data, f)

    records = data.get("forecasts", [])
    n_points = len(records[0]) if records and isinstance(records[0], list) else len(records)
    print(f"Saved {args.output}: {n_points} timesteps for {args.station} "
          f"(init {data.get('initialization_time')})")
