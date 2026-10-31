"""
Fetches everything build_graphic.py needs for one location's trick-or-treat
forecast and writes it to a single forecast_<location>.json:

- NWS hourly forecast (forecastHourly): per-hour temperature, condition icon
  (with NWS's own day/night flag, so the after-sunset frames get night
  icons), wind speed/direction, and the point's IANA timezone.
- NWS raw gridpoints (forecastGridData): apparentTemperature ("feels like")
  and windGust -- the hourly periods carry neither. Only those two
  properties are kept; values are converted to °F/mph here so
  build_graphic.py never has to think about units.
- Open-Meteo's 50-member ECMWF IFS ensemble (hourly precipitation +
  snowfall) -- the chance-of-precip source, same as
  tri-cities-7day-forecast/.
- WindBorne MetaMesh temperature_2m for the location's METAR station, only
  if WB_API_KEY is set (same source as the 7-day forecast's high/low).
  Without a key -- or if MetaMesh doesn't cover the station -- the graphic
  falls back to NWS's own hourly temperature instead of failing.

No API key needed for anything but MetaMesh.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import requests

HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
METAMESH_URL = "https://api.windbornesystems.com/forecasts/v1/point_forecast"

KM_H_TO_MPH = 0.621371

# Each point is the location's airport ASOS -- the same station MetaMesh
# bias-corrects against, so NWS/ECMWF and MetaMesh all describe one spot.
LOCATIONS = {
    "tri-cities": {"lat": 46.2647, "lon": -119.1189, "label": "Tri-Cities, WA", "station": "kpsc"},
    "yakima": {"lat": 46.5682, "lon": -120.5440, "label": "Yakima, WA", "station": "kykm"},
    "hermiston": {"lat": 45.8283, "lon": -119.2593, "label": "Hermiston, OR", "station": "khri"},
}


def _grid_values(grid_props, name, convert):
    return [{"validTime": v["validTime"],
              "value": convert(v["value"]) if v["value"] is not None else None}
             for v in grid_props[name]["values"]]


def fetch_nws(lat, lon):
    points = requests.get(f"https://api.weather.gov/points/{lat},{lon}", headers=HEADERS, timeout=30)
    points.raise_for_status()
    point_props = points.json()["properties"]

    hourly = requests.get(point_props["forecastHourly"], headers=HEADERS, timeout=30)
    hourly.raise_for_status()

    grid = requests.get(point_props["forecastGridData"], headers=HEADERS, timeout=30)
    grid.raise_for_status()
    grid_props = grid.json()["properties"]

    return {
        "timezone": point_props["timeZone"],
        "hourly": hourly.json()["properties"]["periods"],
        "apparent_temperature_f": _grid_values(grid_props, "apparentTemperature", lambda c: c * 9 / 5 + 32),
        "wind_gust_mph": _grid_values(grid_props, "windGust", lambda kmh: kmh * KM_H_TO_MPH),
    }


def fetch_ensemble(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": "ecmwf_ifs025",
        "hourly": "precipitation,snowfall",
        "timezone": "auto",  # resolves to the point's own local timezone
        "forecast_days": 4,
    }
    r = requests.get(ENSEMBLE_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_metamesh(station):
    api_key = os.environ.get("WB_API_KEY")
    if not api_key:
        print("NOTE: WB_API_KEY not set -- skipping MetaMesh, NWS hourly temps will be used instead.")
        return None
    now = datetime.now(timezone.utc)
    params = {
        "stations": station,
        "min_forecast_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_forecast_time": (now + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    r = requests.get(METAMESH_URL, headers={"Authorization": f"Bearer {api_key}"}, params=params, timeout=60)
    if not r.ok:
        # e.g. a station outside MetaMesh's 349 supported METARs -- not
        # worth failing the whole graphic over when NWS has temps too.
        print(f"NOTE: MetaMesh request for {station} failed ({r.status_code}) -- "
              f"NWS hourly temps will be used instead.")
        return None
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--location", choices=sorted(LOCATIONS), default="tri-cities")
    ap.add_argument("--output", help="defaults to forecast_<location>.json")
    args = ap.parse_args()

    loc = LOCATIONS[args.location]
    data = fetch_nws(loc["lat"], loc["lon"])
    data["ensemble"] = fetch_ensemble(loc["lat"], loc["lon"])
    data["metamesh"] = fetch_metamesh(loc["station"])
    data.update(location=args.location, **loc)

    output = args.output or f"forecast_{args.location}.json"
    with open(output, "w") as f:
        json.dump(data, f)

    print(f"Saved {output}: {len(data['hourly'])} NWS hourly periods for {loc['label']} "
          f"(timezone {data['timezone']}, MetaMesh {'yes' if data['metamesh'] else 'no'})")
