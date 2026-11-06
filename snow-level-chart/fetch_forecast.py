"""
Fetches the WM-6 vertical temperature profile (temperature + geopotential on
every pressure level from 1000 to 500 mb) for one site from WindBorne and
writes forecast_<site>.json. Run this before build_chart.py any time you want the
chart to reflect the latest model run.

Requires WB_API_KEY to be set in the environment. Get a key at
https://app.windbornesystems.com/api_tokens.
"""
import argparse
import json
import os

import requests

from sites import SITES

API_URL = "https://api.windbornesystems.com/forecasts/v1/wm-6/point_forecast/interpolated"

# 1000-500 mb covers sea level to ~18,000 ft -- every snow level the
# Cascades will ever see.
LEVELS = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500]


def fetch_level(lat, lon, level, max_hour, api_key):
    params = {
        "coordinates": f"{lat},{lon}",
        "variable": "temperature,geopotential",
        "level": level,
        "max_forecast_hour": max_hour,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(API_URL, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def flatten_level(resp, level):
    """Point-forecast responses key values as e.g. temperature_700; keep just
    time / temperature (C) / geopotential (m2/s2)."""
    out = []
    for p in resp["forecasts"][0]:
        out.append({
            "time": p["time"],
            "temperature": p.get(f"temperature_{level}", p.get("temperature")),
            "geopotential": p.get(f"geopotential_{level}", p.get("geopotential")),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", choices=sorted(SITES), required=True)
    ap.add_argument("--max-hour", type=int, default=123,
                     help="Max forecast hour to request (default 123: five days plus one step)")
    ap.add_argument("--output", default=None, help="Defaults to forecast_<site>.json")
    args = ap.parse_args()

    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")

    site = SITES[args.site]
    lat, lon = site["lat"], site["lon"]

    levels = {}
    meta = None
    for level in LEVELS:
        resp = fetch_level(lat, lon, level, args.max_hour, api_key)
        meta = meta or {k: resp.get(k) for k in ("initialization_time", "forecast_zero")}
        levels[str(level)] = flatten_level(resp, level)

    data = {"site": args.site, "lat": lat, "lon": lon, **meta,
            "levels": levels}

    output = args.output or f"forecast_{args.site}.json"
    with open(output, "w") as f:
        json.dump(data, f)

    n = len(next(iter(levels.values())))
    print(f"Saved {output}: {len(levels)} levels x {n} timesteps for {site['title']} "
          f"(init {data['initialization_time']})")


if __name__ == "__main__":
    main()
