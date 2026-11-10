"""
Pulls the earthquake to mark on the geology map from USGS ComCat and
writes earthquake.json. Defaults to the most recent M3.0+ event in and
around Wallowa County (same rule as ../wallowa-earthquakes-map); pass
--event-id to mark a specific USGS event instead.

Source: USGS FDSN Event Web Service -- public, no API key.
"""
import argparse
import json
from datetime import datetime, timezone

import requests

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MIN_MAG = 3.0
# Same as ../wallowa-earthquakes-map/fetch_earthquakes.py.
LON_MIN, LON_MAX = -118.6, -116.0
LAT_MIN, LAT_MAX = 44.65, 46.3


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event-id", help="USGS event id (e.g. uw714136981)")
    args = ap.parse_args()

    if args.event_id:
        params = {"format": "geojson", "eventid": args.event_id}
        r = requests.get(FDSN_URL, params=params, timeout=60)
        r.raise_for_status()
        f = r.json()
    else:
        params = {"format": "geojson", "starttime": "1900-01-01",
                  "minmagnitude": MIN_MAG, "minlatitude": LAT_MIN,
                  "maxlatitude": LAT_MAX, "minlongitude": LON_MIN,
                  "maxlongitude": LON_MAX, "orderby": "time", "limit": 1}
        r = requests.get(FDSN_URL, params=params, timeout=60)
        r.raise_for_status()
        f = r.json()["features"][0]

    p = f["properties"]
    lon, lat, depth = f["geometry"]["coordinates"]
    quake = {
        "id": f["id"],
        "time": datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat(),
        "mag": round(p["mag"], 2),
        "mag_type": p.get("magType"),
        "place": p.get("place"),
        "lon": lon, "lat": lat, "depth_km": depth,
        "url": p.get("url"),
    }
    with open("earthquake.json", "w") as fh:
        json.dump(quake, fh, indent=1)
    print(f"M{quake['mag']} {quake['place']} {quake['time']} ({quake['id']})")


if __name__ == "__main__":
    main()
