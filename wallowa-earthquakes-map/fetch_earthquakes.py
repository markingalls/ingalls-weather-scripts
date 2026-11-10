"""
Pulls every M3.0+ earthquake on record in and around Wallowa County, OR
from the USGS ComCat catalog and writes earthquakes.json. Run this before
build_map.py any time you want the map to reflect the latest catalog
(e.g. the morning after a felt quake, once USGS has posted it).

Source: USGS FDSN Event Web Service
(https://earthquake.usgs.gov/fdsnws/event/1/) -- public, no API key.
ComCat's record for this region starts in the early 20th century, but
coverage below ~M4 is spotty before the regional seismic networks came
online in the 1970s, so the older part of the record is sparse.

The highlighted ("latest") quake defaults to the most recent event in the
catalog; pass --event-id to highlight a specific USGS event instead.
"""
import argparse
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

PACIFIC = ZoneInfo("America/Los_Angeles")

FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
MIN_MAG = 3.0
START = "1900-01-01"  # earlier than ComCat's first event here -- full record

# Same domain as build_map.py's EXTENT: Wallowa County plus a ring of
# neighboring counties (Union/Baker/Umatilla OR, Walla Walla/Columbia/
# Garfield/Asotin WA, Idaho/Adams ID). Kept equal to the map extent so every
# event in earthquakes.json actually lands on the map.
LON_MIN, LON_MAX = -118.6, -116.0
LAT_MIN, LAT_MAX = 44.65, 46.3


def fetch():
    params = {
        "format": "geojson",
        "starttime": START,
        "minmagnitude": MIN_MAG,
        "minlatitude": LAT_MIN,
        "maxlatitude": LAT_MAX,
        "minlongitude": LON_MIN,
        "maxlongitude": LON_MAX,
        "orderby": "time-asc",
    }
    r = requests.get(FDSN_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.json()["features"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event-id", help="USGS event id to highlight "
                    "(e.g. uw714136981); defaults to the most recent event")
    args = ap.parse_args()

    features = fetch()
    if not features:
        raise SystemExit("USGS returned no events for this domain")

    quakes = []
    for f in features:
        p = f["properties"]
        lon, lat, depth = f["geometry"]["coordinates"]
        quakes.append({
            "id": f["id"],
            "time": datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat(),
            "mag": round(p["mag"], 2),
            "mag_type": p.get("magType"),
            "place": p.get("place"),
            "lon": lon,
            "lat": lat,
            "depth_km": depth,
            "url": p.get("url"),
        })

    if args.event_id:
        matches = [q for q in quakes if q["id"] == args.event_id]
        if not matches:
            raise SystemExit(f"event {args.event_id} not in the M{MIN_MAG}+ "
                             "catalog for this domain")
        highlight = matches[0]
    else:
        highlight = quakes[-1]  # orderby=time-asc -> last is most recent

    out = {
        "fetched": datetime.now(timezone.utc).isoformat(),
        "min_mag": MIN_MAG,
        "bbox": [LON_MIN, LON_MAX, LAT_MIN, LAT_MAX],
        "highlight_id": highlight["id"],
        "quakes": quakes,
    }
    with open("earthquakes.json", "w") as fh:
        json.dump(out, fh, indent=1)

    t_pt = datetime.fromisoformat(highlight["time"]).astimezone(PACIFIC)
    print(f"{len(quakes)} M{MIN_MAG}+ events, {quakes[0]['time'][:10]} to "
          f"{quakes[-1]['time'][:10]}")
    print(f"highlight: M{highlight['mag']} {highlight['place']} "
          f"{t_pt:%Y-%m-%d %I:%M %p %Z} ({highlight['id']})")


if __name__ == "__main__":
    main()
