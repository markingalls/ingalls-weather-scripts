"""
Fetches the MetaMesh deterministic point forecast (temperature_2m) for a
station -- or, with --lat/--lon, an arbitrary coordinate -- from WindBorne
and writes metamesh_forecast.json. MetaMesh blends NOAA (HRRR, GFS), ECMWF
(IFS, AIFS), and WindBorne's own models. By station identifier (KPSC) it
additionally applies station-specific bias correction for its 349 supported
METAR stations; by coordinate it's the gridded model interpolated straight
to that point, no bias correction, but not limited to station locations --
notably better for a remote/high-elevation point with no nearby station,
where the nearest station's own elevation can be wildly different from the
target point's (confirmed directly: for a ~3000ft Cascades point with no
nearby METAR, the nearest station -- Yakima, ~1000ft, in the valley --
overshot a NWS-forecast 46F high by 14 degrees; the coordinate query matched
NWS's own forecast closely instead). Run this alongside fetch_forecast.py
(which supplies the day/night structure and NWS condition icons) any time
you want the graphic's high/low numbers to reflect the latest model run.

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
# general form for picking a different model (e.g. wm-6). The endpoint
# accepts EITHER 'stations' or 'coordinates' (a bare "lat,lon" string, no
# parens) -- also undocumented, found by triggering its own 400 error
# message ("At least one of 'coordinates' or 'stations' is required").
API_URL = "https://api.windbornesystems.com/forecasts/v1/point_forecast"

DEFAULT_STATION = "kpsc"  # Tri-Cities Airport, Pasco, WA


def fetch(max_days, station=None, lat=None, lon=None):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")
    now = datetime.now(timezone.utc)
    params = {
        "min_forecast_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_forecast_time": (now + timedelta(days=max_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if lat is not None:
        params["coordinates"] = f"{lat},{lon}"
    else:
        params["stations"] = station
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(API_URL, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station", default=None,
                     help="ICAO identifier, one of MetaMesh's 349 supported METAR stations "
                          f"(default {DEFAULT_STATION!r} if --lat/--lon aren't given)")
    ap.add_argument("--lat", type=float, help="Query by coordinate instead of --station")
    ap.add_argument("--lon", type=float, help="Query by coordinate instead of --station")
    ap.add_argument("--max-days", type=int, default=8,
                     help="How many days out to request (needs to clear 7 days of "
                          "day+night periods with room to spare)")
    ap.add_argument("--output", default="metamesh_forecast.json")
    args = ap.parse_args()

    if (args.lat is None) != (args.lon is None):
        ap.error("--lat and --lon must be given together")
    if args.lat is not None and args.station is not None:
        ap.error("--station and --lat/--lon are mutually exclusive")

    if args.lat is not None:
        data = fetch(args.max_days, lat=args.lat, lon=args.lon)
        label = f"{args.lat},{args.lon}"
    else:
        data = fetch(args.max_days, station=args.station or DEFAULT_STATION)
        label = args.station or DEFAULT_STATION

    with open(args.output, "w") as f:
        json.dump(data, f)

    records = data.get("forecasts", [])
    n_points = len(records[0]) if records and isinstance(records[0], list) else len(records)
    print(f"Saved {args.output}: {n_points} timesteps for {label} "
          f"(init {data.get('initialization_time')})")
