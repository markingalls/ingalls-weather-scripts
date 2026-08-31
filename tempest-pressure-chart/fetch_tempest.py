"""
Fetches a full local calendar day's observations (1-minute Tempest samples)
for a WeatherFlow Tempest station and writes tempest_pressure_obs.json --
sea-level-reduced barometric pressure, the same station/day-boundary
handling as ../tempest-temp-chart/fetch_tempest.py's temperature fetch,
just reading a different obs_st field (and, unlike that script, also
needing the station's own elevation to do the sea-level reduction).

Requires a Tempest API key (get one at https://tempestwx.com/settings/tokens),
passed via --api-key or the TEMPEST_API_KEY environment variable.

Station discovery: calls /swd/rest/stations to list the account's stations
and picks the first one with a Tempest ("ST") device, unless --station-id
pins a specific one (useful if the account has more than one station).
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://swd.weatherflow.com/swd/rest"

# obs_st field indices (WeatherFlow Tempest API, /observations/device):
# 0 epoch, 1 wind lull, 2 wind avg, 3 wind gust, 4 wind dir, 5 wind sample
# interval, 6 station pressure (mb), 7 air temperature (C), 8 relative
# humidity, 9 illuminance, 10 UV, 11 solar radiation, 12 rain accumulated, ...
STATION_PRESSURE_MB_INDEX = 6
AIR_TEMP_C_INDEX = 7

MB_TO_INHG = 0.0295300

# Standard barometric formula for reducing station pressure to sea level
# (the same reduction NWS-style METAR/altimeter-style readings use,
# ignoring humidity/virtual-temperature effects -- a station-elevation-only
# approximation, not a full QFF calculation, but the standard one
# consumer weather stations including Tempest's own app use): -6.5 K/km
# is the ICAO standard atmosphere's tropospheric lapse rate, and 5.257 =
# g*M / (R*L) for that same standard atmosphere.
BAROMETRIC_LAPSE_RATE_K_PER_M = 0.0065
BAROMETRIC_EXPONENT = 5.257


def sea_level_pressure_mb(station_pressure_mb, elevation_m, temp_c):
    lapse_term = BAROMETRIC_LAPSE_RATE_K_PER_M * elevation_m
    denom = temp_c + lapse_term + 273.15
    return station_pressure_mb * (1 - lapse_term / denom) ** (-BAROMETRIC_EXPONENT)


def mb_to_inhg(mb):
    return mb * MB_TO_INHG


# Known-station display-name overrides -- the API's own "public_name" is
# sometimes just the property name, without the nearby town that makes it
# recognizable to an Instagram audience. Falls back to the raw API name for
# any station not listed here.
STATION_LABEL_OVERRIDES = {
    "Highland Hills": "Highland Hills (Hermiston)",
}


def fetch_stations(api_key):
    r = requests.get(f"{BASE_URL}/stations", params={"api_key": api_key}, timeout=30)
    r.raise_for_status()
    return r.json()


def find_tempest_device(stations, station_id=None):
    for station in stations.get("stations", []):
        if station_id is not None and station["station_id"] != station_id:
            continue
        for device in station.get("devices", []):
            if device.get("device_type") == "ST":
                return station, device
    return None, None


def fetch_observations(api_key, device_id, time_start, time_end):
    # Deliberately time_start/time_end (station-local midnight to midnight
    # converted to UTC unix seconds) rather than the endpoint's day_offset
    # param -- day_offset buckets by UTC calendar day, not the station's
    # local one, which silently shifts "today" for any station west of UTC.
    r = requests.get(f"{BASE_URL}/observations/device/{device_id}",
                      params={"api_key": api_key, "time_start": time_start, "time_end": time_end},
                      timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-key", default=os.environ.get("TEMPEST_API_KEY"),
                     help="Tempest API key (or set TEMPEST_API_KEY)")
    ap.add_argument("--station-id", type=int, default=None,
                     help="Pin a specific station id (default: first station with a Tempest device)")
    ap.add_argument("--date", default=None,
                     help="YYYY-MM-DD, station-local calendar day (default: today, station-local)")
    ap.add_argument("--label", default=None,
                     help="Display label override, e.g. 'Highland Hills (Hermiston)' "
                          "(default: STATION_LABEL_OVERRIDES entry for the API's name, else the API name itself)")
    ap.add_argument("--output", default="tempest_pressure_obs.json")
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("Tempest API key required: pass --api-key or set TEMPEST_API_KEY")

    stations = fetch_stations(args.api_key)
    station, device = find_tempest_device(stations, args.station_id)
    if device is None:
        raise SystemExit("No Tempest ('ST') device found for this API key/station-id")

    elevation_m = station["station_meta"]["elevation"]

    tz = ZoneInfo(station["timezone"])
    target_date = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    obs_resp = fetch_observations(args.api_key, device["device_id"],
                                   int(day_start.timestamp()), int(day_end.timestamp()))

    observations = []
    for row in obs_resp.get("obs") or []:
        epoch = row[0]
        station_pressure_mb, air_temp_c = row[STATION_PRESSURE_MB_INDEX], row[AIR_TEMP_C_INDEX]
        if epoch is None or station_pressure_mb is None or air_temp_c is None:
            continue
        local_time = datetime.fromtimestamp(epoch, tz)
        slp_mb = sea_level_pressure_mb(station_pressure_mb, elevation_m, air_temp_c)
        observations.append({
            "time": local_time.isoformat(),
            "sea_level_pressure_inhg": round(mb_to_inhg(slp_mb), 2),
        })

    station_name = station.get("public_name") or station.get("name")
    label = args.label or STATION_LABEL_OVERRIDES.get(station_name, station_name)

    out = {
        "source": "WeatherFlow Tempest API, /observations/device (obs_st), station pressure "
                   "reduced to sea level via the standard barometric formula using the "
                   "station's own elevation (/stations station_meta.elevation)",
        "station_id": station["station_id"],
        "station_name": station_name,
        "label": label,
        "device_id": device["device_id"],
        "timezone": station["timezone"],
        "elevation_m": elevation_m,
        "date": target_date.isoformat(),
        "observations": observations,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    if observations:
        print(f"Saved {args.output}: {len(observations)} obs for {label} on "
              f"{target_date} ({observations[0]['time']} .. {observations[-1]['time']})")
    else:
        print(f"Saved {args.output}: 0 observations returned for {label} on {target_date}")
