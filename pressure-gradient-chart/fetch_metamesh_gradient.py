"""
Fetches the past day's observed PDX/HRI (or whichever pair) pressure
gradient from api.weather.gov, plus the next several days' forecast
gradient from WindBorne MetaMesh, and writes gradient_forecast.json: one
combined, time-ascending series with an `is_forecast` flag marking where
observed data ends and the forecast begins.

Observed segment: same source and station-pressure handling as
fetch_gradient.py (imported directly, not reimplemented) -- NWS ASOS/AWOS
`barometricPressure`, already near-sea-level, no further reduction.

Forecast segment: WindBorne MetaMesh's `pressure_msl` field (already mean
sea level pressure), queried by station id for both stations -- confirmed
live that MetaMesh accepts KHRI directly as a station id (not just
coordinates) and that both stations' forecasts share the exact same
hourly time grid, so no interpolation/pairing is needed on that side,
unlike the observed segment's two independently-timed NWS feeds. Verified
against the observed segment for continuity: MetaMesh's pressure_msl at
the top of a recent hour tracked barometricPressure at both stations to
within ~0.2 mb.

Requires WB_API_KEY in the environment (same WindBorne account/key every
other MetaMesh-consuming project in this repo uses). Get one at
https://app.windbornesystems.com/api_tokens.
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from fetch_gradient import MATCH_TOLERANCE, merge_gradient, normalize_station_id, pressure_series

METAMESH_URL = "https://api.windbornesystems.com/forecasts/v1/point_forecast"


def fetch_metamesh_pressure(station_id, min_time, max_time):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        raise SystemExit("Set WB_API_KEY in your environment before running this script.")
    params = {
        "stations": station_id,
        "min_forecast_time": min_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_forecast_time": max_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(METAMESH_URL, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    points = data["forecasts"][0]
    series = {p["time"]: p["pressure_msl"] for p in points if p.get("pressure_msl") is not None}
    return series, data["initialization_time"]


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station-a", default="KPDX")
    ap.add_argument("--station-b", default="KHRI")
    ap.add_argument("--label-a", default="PDX")
    ap.add_argument("--label-b", default="HRI")
    ap.add_argument("--timezone", default="America/Los_Angeles")
    ap.add_argument("--obs-days", type=int, default=1,
                     help="Trailing local calendar days of NWS-observed gradient (default: 1)")
    ap.add_argument("--forecast-days", type=int, default=5,
                     help="MetaMesh forecast days ahead of now (default: 5)")
    ap.add_argument("--output", default="gradient_forecast.json")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    station_a_id = normalize_station_id(args.station_a)
    station_b_id = normalize_station_id(args.station_b)
    tz = ZoneInfo(args.timezone)

    now = datetime.now(tz)
    today = now.date()
    obs_start_date = today - timedelta(days=args.obs_days - 1)
    window_start = datetime(obs_start_date.year, obs_start_date.month, obs_start_date.day, tzinfo=tz)
    start_utc = window_start.astimezone(timezone.utc)
    end_utc = now.astimezone(timezone.utc) + timedelta(minutes=1)

    # ---------- observed segment (NWS, past) ----------
    series_a = pressure_series(station_a_id, start_utc, end_utc)
    series_b = pressure_series(station_b_id, start_utc, end_utc)
    merged_obs = merge_gradient(series_a, series_b, MATCH_TOLERANCE)

    observations = [{
        "time": datetime.fromtimestamp(epoch, tz).isoformat(),
        "gradient_mb": round(pressure_a - pressure_b, 2),
        f"{args.label_a.lower()}_mb": round(pressure_a, 1),
        f"{args.label_b.lower()}_mb": round(pressure_b, 1),
        "is_forecast": False,
    } for epoch, pressure_a, pressure_b in merged_obs]

    # ---------- forecast segment (MetaMesh, future) ----------
    forecast_end_utc = now.astimezone(timezone.utc) + timedelta(days=args.forecast_days)
    forecast_a, init_time = fetch_metamesh_pressure(station_a_id, now.astimezone(timezone.utc), forecast_end_utc)
    forecast_b, _ = fetch_metamesh_pressure(station_b_id, now.astimezone(timezone.utc), forecast_end_utc)

    forecast = []
    for t in sorted(set(forecast_a) & set(forecast_b)):
        pressure_a, pressure_b = forecast_a[t], forecast_b[t]
        local_time = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(tz)
        forecast.append({
            "time": local_time.isoformat(),
            "gradient_mb": round(pressure_a - pressure_b, 2),
            f"{args.label_a.lower()}_mb": round(pressure_a, 1),
            f"{args.label_b.lower()}_mb": round(pressure_b, 1),
            "is_forecast": True,
        })
    forecast.sort(key=lambda o: o["time"])

    # Derived from the actual last forecast timestamp returned, not an
    # independently rounded "now + forecast_days" -- MetaMesh's hourly
    # grid doesn't necessarily land exactly on that boundary, and a
    # mismatch here left the window's true last point (often the
    # high/low-marked one) sitting just past build_forecast_chart.py's
    # x-axis limit, clipping its label off the right edge.
    window_end = (datetime.fromisoformat(forecast[-1]["time"]) + timedelta(hours=1)) if forecast else now

    out = {
        "source": "Observed: api.weather.gov per-station /observations feed (see "
                   "fetch_gradient.py) for the past segment. Forecast: WindBorne MetaMesh "
                   "point_forecast, pressure_msl, queried by station id for both stations, "
                   "for the future segment. Both differenced as "
                   f"{args.label_a} minus {args.label_b}.",
        "station_a": {"id": station_a_id, "label": args.label_a},
        "station_b": {"id": station_b_id, "label": args.label_b},
        "timezone": args.timezone,
        "window_start": window_start.isoformat(),
        "now": now.isoformat(),
        "window_end": window_end.isoformat(),
        "forecast_init_time": init_time,
        "gradient_label": f"{args.label_a} minus {args.label_b}",
        "observations": observations + forecast,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {args.output}: {len(observations)} observed obs (last {args.obs_days}d) + "
          f"{len(forecast)} forecast points (next {args.forecast_days}d) for "
          f"{args.label_a}-{args.label_b} (MetaMesh init {init_time})")
