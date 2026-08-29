"""
Refreshes alerts_with_zones.json with whatever NWS alerts are currently
active for AREA below. Run this before build_map.py any time you want the
map to reflect right-now conditions instead of a stale snapshot.
"""
import json
import os
import time
import requests

HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}
# Every state any region's extent reaches into, even by a sliver, needs to
# be listed here -- a region's frame doesn't limit what NWS data gets
# fetched, only AREA does, so a state left out here always renders
# alert-free in that region regardless of what's actually active there
# (this bit columbia_basin's Idaho panhandle sliver earlier; pnw_wide's
# much wider extent now reaches CA/NV/MT/UT the same way). Marine zones
# (Small Craft Advisory, Gale Warning, Special Marine Warning, etc.) are a
# separate case: NWS doesn't file them under a coastal state's own area
# code at all, only under its own marine area code -- "PZ" covers coastal
# and offshore Pacific waters from Point Arena, CA to the Canadian border,
# which is the whole OR/WA coast plus the Strait of Juan de Fuca that
# Portland's and pnw_wide's extents reach. Without PZ here, marine alerts
# always render as "none active" regardless of what's actually posted.
AREA = "OR,WA,ID,CA,NV,MT,UT,PZ"

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
ZONE_CACHE_FILE = os.path.join(STATE_DIR, "zone_geometry_cache.json")


def fetch_active_alerts():
    url = f"https://api.weather.gov/alerts/active?area={AREA}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def load_zone_cache():
    try:
        with open(ZONE_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_zone_cache(zone_cache):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp_path = ZONE_CACHE_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(zone_cache, f)
    os.replace(tmp_path, ZONE_CACHE_FILE)


def fetch_zone_geometries(alerts_geojson, zone_cache):
    # Zone boundaries are essentially static (NWS very rarely redraws a
    # forecast zone), so persisting this to disk across runs avoids
    # re-fetching every zone's geometry on every single cron tick -- AREA
    # covering seven states now means a lot more zones to look up than
    # when this was just OR/WA/ID.
    records = []
    for f in alerts_geojson["features"]:
        p = f["properties"]
        zones = p.get("affectedZones", [])
        geoms = []
        for z in zones:
            if z not in zone_cache:
                r = requests.get(z, headers=HEADERS, timeout=20)
                r.raise_for_status()
                zj = r.json()
                zone_cache[z] = {
                    "zone_id": zj["properties"].get("id"),
                    "name": zj["properties"].get("name"),
                    "geometry": zj["geometry"],
                }
                time.sleep(0.2)  # be polite to the API
            geoms.append(zone_cache[z])
        records.append({
            "id": p.get("id") or f.get("id"),
            "event": p["event"],
            "severity": p.get("severity"),
            "onset": p.get("onset"),
            "ends": p.get("ends"),
            "headline": p.get("headline"),
            # Polygon-type products (see POLYGON_WARNING_EVENTS in
            # build_map.py) carry their own precise warned-area geometry
            # here; NWS leaves this null for zone-based products, which
            # fall back to `zones` below.
            "geometry": f.get("geometry"),
            "zones": geoms,
        })
    return records


if __name__ == "__main__":
    raw = fetch_active_alerts()
    print(f"Active alerts fetched: {len(raw['features'])}")
    zone_cache = load_zone_cache()
    cache_size_before = len(zone_cache)
    records = fetch_zone_geometries(raw, zone_cache)
    save_zone_cache(zone_cache)
    json.dump(records, open("alerts_with_zones.json", "w"))
    for r in records:
        print(" -", r["event"], [z["name"] for z in r["zones"]])
    print(f"Zone cache: {cache_size_before} cached, {len(zone_cache) - cache_size_before} newly fetched.")
    print("Saved alerts_with_zones.json")
