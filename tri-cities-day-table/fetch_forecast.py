"""
Fetches the two hourly inputs build_table.py needs for a single-day
Tri-Cities table and writes them to forecast.json:

- NWS's hourly forecast (api.weather.gov `forecastHourly`) for the
  temperature row, plus the point's IANA timezone from the same `/points`
  lookup. No API key needed. (The 7-day graphic's MetaMesh highs/lows are a
  daily max/min reduction; this table wants the hourly curve itself, and
  NWS's hourly feed gives that directly without a WindBorne key.)
- NWS's gridded snow level (`forecastGridData` snowLevel, plus the grid
  cell's surface elevation) for the rain/snow-mix icon. No API key needed.
- WindBorne WM-6 ensemble precip-type probabilities (rain / freezing rain /
  ice pellets / snow), for the rain-vs-snow-vs-mix call. Optional: needs
  WB_API_KEY, skipped without one.
- Open-Meteo's 50-member ECMWF IFS ensemble (hourly precipitation +
  snowfall) for the chance-of-precip row -- same source and reasoning as
  tri-cities-7day-forecast/fetch_ecmwf_ensemble_forecast.py (raw members, so
  an exact measurable-precip threshold can be applied). No API key needed.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import requests

NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
HEADERS = {"User-Agent": "ingalls-weather-scripts", "Accept": "application/geo+json"}

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189


def fetch_nws_hourly(lat, lon):
    r = requests.get(NWS_POINTS_URL.format(lat=lat, lon=lon), headers=HEADERS, timeout=30)
    r.raise_for_status()
    point = r.json()["properties"]
    r = requests.get(point["forecastHourly"], headers=HEADERS, timeout=30)
    r.raise_for_status()
    periods = r.json()["properties"]["periods"]
    hourly = [{"start": p["startTime"], "temperature_f": p["temperature"]} for p in periods
              if p.get("temperatureUnit") == "F"]
    return point, hourly


def fetch_snow_level(point):
    """NWS gridded snowLevel series (start/duration intervals, meters MSL)
    and the grid cell's own surface elevation (m), both from the point's
    forecastGridData -- the raw grid, since the hourly/periods forecasts
    don't carry snow level at all."""
    r = requests.get(point["forecastGridData"], headers=HEADERS, timeout=30)
    r.raise_for_status()
    grid = r.json()["properties"]
    return {
        "surface_elevation_m": grid["elevation"]["value"],
        "values": [{"valid_time": v["validTime"], "snow_level_m": v["value"]}
                   for v in grid.get("snowLevel", {}).get("values", [])],
    }


WM6_INTERPOLATED_URL = "https://api.windbornesystems.com/forecasts/v1/wm-6/point_forecast/interpolated"


def fetch_wm6_variable(lat, lon, forecast_days, variable):
    """One WM-6 variable's ensemble distribution at a point, stored as the
    API's own response. Needs WB_API_KEY; returns None without one."""
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        return None
    now = datetime.now(timezone.utc)
    params = {
        "coordinates": f"{lat},{lon}",
        "variable": variable,
        "include_distribution": "true",
        "min_forecast_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_forecast_time": (now + timedelta(days=forecast_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    r = requests.get(WM6_INTERPOLATED_URL, params=params,
                      headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_wm6_ptype(lat, lon, forecast_days):
    """WindBorne WM-6 ensemble precipitation-type probabilities
    (p_rain/p_freezing_rain/p_ice_pellets/p_snow per 3-hourly step), stored
    as the API's own response. Needs WB_API_KEY; returns None without one
    (build_table.py then just skips the WM-6 rain/snow/mix rule)."""
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        print("NOTE: WB_API_KEY not set -- skipping WM-6 precip-type probabilities.")
        return None
    now = datetime.now(timezone.utc)
    params = {
        "coordinates": f"{lat},{lon}",
        "variable": "p_type",
        "include_distribution": "true",
        "min_forecast_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_forecast_time": (now + timedelta(days=forecast_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    r = requests.get(WM6_INTERPOLATED_URL, params=params,
                      headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_ensemble(lat, lon, forecast_days):
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,snowfall",
        "timezone": "auto",  # resolves to the point's own local timezone
        "forecast_days": forecast_days,
    }
    r = requests.get(ENSEMBLE_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--label", default="Tri-Cities")
    ap.add_argument("--forecast-days", type=int, default=8,
                     help="Enough to reach any day of the coming week")
    ap.add_argument("--output", default="forecast.json")
    args = ap.parse_args()

    point, hourly = fetch_nws_hourly(args.lat, args.lon)
    tz = point["timeZone"]
    snow_level = fetch_snow_level(point)
    try:
        ensemble = fetch_ensemble(args.lat, args.lon, args.forecast_days)
    except requests.RequestException as e:
        # Open-Meteo's free tier rate-limits shared IPs; still save the NWS
        # (and WM-6) data so build_table.py can fall back to WM-6 precip odds.
        print(f"WARNING: ECMWF ensemble fetch failed ({e}) -- saving without it.")
        ensemble = None
    wm6_ptype = fetch_wm6_ptype(args.lat, args.lon, args.forecast_days)
    # WM-6 3h precip distribution: fallback chance-of-precip source
    wm6_precip = fetch_wm6_variable(args.lat, args.lon, args.forecast_days, "total_precipitation_3h")

    with open(args.output, "w") as f:
        json.dump({"label": args.label, "timezone": tz, "nws_hourly": hourly,
                   "nws_snow_level": snow_level,
                   "wm6_ptype": wm6_ptype,
                   "wm6_precip": wm6_precip,
                   "ecmwf_ensemble": ensemble}, f)

    n_members = sum(1 for k in ensemble["hourly"] if k.startswith("precipitation_member")) if ensemble else 0
    print(f"Saved {args.output}: {len(hourly)} NWS hourly temps, {n_members} ECMWF members "
          f"at {args.lat},{args.lon} (timezone {tz})")
