"""
Refreshes alerts_with_zones.json with whatever NWS alerts are currently
active for OR/WA. Run this before build_map.py any time you want the map
to reflect right-now conditions instead of a stale snapshot.
"""
import json
import time
import requests

HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}
AREA = "OR,WA"  # add more states here if you widen the map domain later


def fetch_active_alerts():
    url = f"https://api.weather.gov/alerts/active?area={AREA}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_zone_geometries(alerts_geojson):
    zone_cache = {}
    records = []
    for f in alerts_geojson["features"]:
        p = f["properties"]
        zones = p.get("affectedZones", [])
        geoms = []
        for z in zones:
            if z not in zone_cache:
                r = requests.get(z, headers=HEADERS, timeout=20)
                r.raise_for_status()
                zone_cache[z] = r.json()
                time.sleep(0.2)  # be polite to the API
            zj = zone_cache[z]
            geoms.append({
                "zone_id": zj["properties"].get("id"),
                "name": zj["properties"].get("name"),
                "geometry": zj["geometry"],
            })
        records.append({
            "event": p["event"],
            "severity": p.get("severity"),
            "onset": p.get("onset"),
            "ends": p.get("ends"),
            "headline": p.get("headline"),
            "zones": geoms,
        })
    return records


if __name__ == "__main__":
    raw = fetch_active_alerts()
    print(f"Active alerts fetched: {len(raw['features'])}")
    records = fetch_zone_geometries(raw)
    json.dump(records, open("alerts_with_zones.json", "w"))
    for r in records:
        print(" -", r["event"], [z["name"] for z in r["zones"]])
    print("Saved alerts_with_zones.json")
