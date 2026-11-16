"""
Fetches the two hourly inputs build_table.py needs for a single-day
Tri-Cities table and writes them to forecast.json:

- NWS's hourly forecast (api.weather.gov `forecastHourly`) for the
  temperature row, plus the point's IANA timezone from the same `/points`
  lookup. No API key needed. (The 7-day graphic's MetaMesh highs/lows are a
  daily max/min reduction; this table wants the hourly curve itself, and
  NWS's hourly feed gives that directly without a WindBorne key.)
- Open-Meteo's 50-member ECMWF IFS ensemble (hourly precipitation +
  snowfall) for the chance-of-precip row -- same source and reasoning as
  tri-cities-7day-forecast/fetch_ecmwf_ensemble_forecast.py (raw members, so
  an exact measurable-precip threshold can be applied). No API key needed.
"""
import argparse
import json

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
    return point["timeZone"], hourly


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

    tz, hourly = fetch_nws_hourly(args.lat, args.lon)
    ensemble = fetch_ensemble(args.lat, args.lon, args.forecast_days)

    with open(args.output, "w") as f:
        json.dump({"label": args.label, "timezone": tz, "nws_hourly": hourly,
                   "ecmwf_ensemble": ensemble}, f)

    n_members = sum(1 for k in ensemble["hourly"] if k.startswith("precipitation_member"))
    print(f"Saved {args.output}: {len(hourly)} NWS hourly temps, {n_members} ECMWF members "
          f"at {args.lat},{args.lon} (timezone {tz})")
