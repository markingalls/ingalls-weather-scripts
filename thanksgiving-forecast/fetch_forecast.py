"""
Fetches everything build_graphic.py needs for the Thanksgiving forecast
and writes it to a single forecast.json. Same sources as
crunchwrap-crawl-forecast/fetch_forecast.py (and
halloween-trick-or-treat-forecast/fetch_forecast.py before it):

- NWS hourly forecast (forecastHourly): per-hour temperature, condition icon
  (with NWS's own day/night flag, so frames after sunset get night
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
- NOAA RRFS (Rapid Refresh Forecast System, 3km CONUS) surface wind gust
  at each card's hour -- the gust source, in place of NWS's gridded
  windGust. Only the GUST:surface record is downloaded from each hourly
  GRIB2 file (byte range from its .idx), from NOMADS. If RRFS can't be
  reached, the graphic falls back to NWS's gusts.

No API key needed for anything but MetaMesh.
"""
import argparse
import json
import os
import time
from datetime import date as ddate, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import eccodes
import numpy as np
import requests

HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
METAMESH_URL = "https://api.windbornesystems.com/forecasts/v1/point_forecast"

KM_H_TO_MPH = 0.621371
ENSEMBLE_RETRIES = 5
ENSEMBLE_RETRY_WAIT_S = 15
MS_TO_MPH = 2.23694

RRFS_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod"
# Only the synoptic cycles run out to 84h; the hourly ones in between stop
# far short of that, so they're never enough to reach a day-ahead card.
RRFS_LONG_CYCLES = (0, 6, 12, 18)
RRFS_MAX_FHR = 84
RRFS_LOOKBACK_CYCLES = 8

# Default point: KPSC (Tri-Cities Airport, Pasco, WA) -- the same station
# MetaMesh bias-corrects against, so NWS/ECMWF and MetaMesh describe one spot.
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189
DEFAULT_LABEL = "Tri-Cities, WA"
DEFAULT_STATION = "kpsc"

# Reach most of a week out so it can be run well ahead of the holiday (NWS hourly
# stops around 6.5 days anyway).
FORECAST_DAYS = 7


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
        "forecast_days": FORECAST_DAYS,
    }
    # Open-Meteo's free tier rate-limits per egress IP, and shared cloud IPs
    # can trip that intermittently -- a few spaced retries usually clear it.
    for attempt in range(ENSEMBLE_RETRIES):
        r = requests.get(ENSEMBLE_URL, params=params, timeout=30)
        if r.status_code != 429:
            break
        time.sleep(ENSEMBLE_RETRY_WAIT_S)
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
        "max_forecast_time": (now + timedelta(days=FORECAST_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    r = requests.get(METAMESH_URL, headers={"Authorization": f"Bearer {api_key}"}, params=params, timeout=60)
    if not r.ok:
        # e.g. a station outside MetaMesh's 349 supported METARs -- not
        # worth failing the whole graphic over when NWS has temps too.
        print(f"NOTE: MetaMesh request for {station} failed ({r.status_code}) -- "
              f"NWS hourly temps will be used instead.")
        return None
    return r.json()


def thanksgiving(year):
    """US Thanksgiving: the fourth Thursday of November (same as build_graphic.py)."""
    first = ddate(year, 11, 1)
    return first + timedelta(days=(3 - first.weekday()) % 7, weeks=3)


def default_date(today):
    day = thanksgiving(today.year)
    return day if day >= today else thanksgiving(today.year + 1)


def _rrfs_file(cycle, fhr):
    return (f"{RRFS_URL}/rrfs.{cycle:%Y%m%d}/{cycle:%H}/"
            f"rrfs.t{cycle:%H}z.2dfld.3km.f{fhr:03d}.conus.grib2")


def pick_rrfs_cycle(valid_times):
    """The newest 84h RRFS cycle that's already published far enough out to
    cover every valid time -- checked by asking for the latest needed
    hour's .idx, since NOMADS fills a cycle in over a couple of hours."""
    now = datetime.now(timezone.utc)
    cycle = now.replace(hour=max(h for h in RRFS_LONG_CYCLES if h <= now.hour), minute=0, second=0, microsecond=0)
    for _ in range(RRFS_LOOKBACK_CYCLES):
        last_fhr = int((max(valid_times) - cycle).total_seconds() // 3600)
        if 0 <= min(int((t - cycle).total_seconds() // 3600) for t in valid_times) and last_fhr <= RRFS_MAX_FHR:
            if requests.get(_rrfs_file(cycle, last_fhr) + ".idx", timeout=30).ok:
                return cycle
        cycle -= timedelta(hours=6)
    return None


def rrfs_gust_at(cycle, fhr, lat, lon):
    """RRFS GUST:surface (mph) at the grid point nearest (lat, lon)."""
    url = _rrfs_file(cycle, fhr)
    idx = requests.get(url + ".idx", timeout=30)
    idx.raise_for_status()
    lines = idx.text.splitlines()
    i = next(k for k, line in enumerate(lines) if ":GUST:surface:" in line)
    start, end = int(lines[i].split(":")[1]), int(lines[i + 1].split(":")[1]) - 1
    r = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=60)
    r.raise_for_status()
    gid = eccodes.codes_new_from_message(r.content)
    try:
        values = eccodes.codes_get_values(gid)
        lats = eccodes.codes_get_array(gid, "latitudes")
        lons = eccodes.codes_get_array(gid, "longitudes")
    finally:
        eccodes.codes_release(gid)
    lons = np.where(lons > 180, lons - 360, lons)
    dist = (lats - lat) ** 2 + ((lons - lon) * np.cos(np.radians(lat))) ** 2
    return float(values[dist.argmin()]) * MS_TO_MPH


def fetch_rrfs_gusts(lat, lon, day, hours, tz_name):
    local_tz = ZoneInfo(tz_name)
    valid_times = [datetime.combine(day, dtime(h), tzinfo=local_tz).astimezone(timezone.utc) for h in hours]
    try:
        cycle = pick_rrfs_cycle(valid_times)
        if cycle is None:
            print("NOTE: no RRFS cycle covers those hours yet -- NWS gusts will be used instead.")
            return None
        gusts = {t.isoformat(): rrfs_gust_at(cycle, int((t - cycle).total_seconds() // 3600), lat, lon)
                 for t in valid_times}
    except (requests.RequestException, StopIteration, eccodes.CodesInternalError) as exc:
        print(f"NOTE: RRFS gust fetch failed ({exc}) -- NWS gusts will be used instead.")
        return None
    return {"cycle": cycle.isoformat(), "gust_mph": gusts}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--label", default=DEFAULT_LABEL,
                     help="Human-readable location shown in the graphic subtitle")
    ap.add_argument("--station", default=DEFAULT_STATION,
                     help="MetaMesh METAR station for the temperature")
    ap.add_argument("--date", help="Local date for the RRFS gusts, YYYY-MM-DD (default: this year's Thanksgiving)")
    ap.add_argument("--hours", type=int, nargs="+", default=[7, 11, 15, 19],
                     help="Local hours to fetch RRFS gusts for -- match build_graphic.py's --hours")
    ap.add_argument("--output", default="forecast.json")
    args = ap.parse_args()

    data = fetch_nws(args.lat, args.lon)
    data["ensemble"] = fetch_ensemble(args.lat, args.lon)
    data["metamesh"] = fetch_metamesh(args.station)
    day = ddate.fromisoformat(args.date) if args.date else default_date(datetime.now(ZoneInfo(data["timezone"])).date())
    data["rrfs"] = fetch_rrfs_gusts(args.lat, args.lon, day, args.hours, data["timezone"])
    data.update(lat=args.lat, lon=args.lon, label=args.label, station=args.station)

    with open(args.output, "w") as f:
        json.dump(data, f)

    print(f"Saved {args.output}: {len(data['hourly'])} NWS hourly periods for {args.label} "
          f"(timezone {data['timezone']}, MetaMesh {'yes' if data['metamesh'] else 'no'}, "
          f"RRFS {data['rrfs']['cycle'] if data['rrfs'] else 'no'})")
