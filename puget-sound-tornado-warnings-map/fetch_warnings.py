"""Pull every polygon-era NWS Seattle (SEW) Tornado Warning from the
Iowa Environmental Mesonet's VTEC archive, plus each warning's polygon,
and write tornado_warnings.json for build_map.py.

IEM's VTEC archive is the de facto public record of NWS warnings (NWS
itself doesn't serve historical products through api.weather.gov), and
it carries storm-based polygons from 2007 on. A warning without a stored
polygon falls back to the union of its counties' geometries.
"""
import argparse
import json
from datetime import datetime, timezone

import requests

IEM = "https://mesonet.agron.iastate.edu"
WFO = "SEW"
# Storm-based (polygon) warnings became the NWS standard on 1 Oct 2007.
START_YEAR = 2007


def get_json(url, params):
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def event_geometry(year, etn):
    """Storm-based polygon for one warning, or the county geometry if IEM
    has no polygon stored for it (pre-2007 county-based warnings)."""
    base = {"wfo": WFO, "year": year, "phenomena": "TO",
            "significance": "W", "etn": etn}
    for sbw in (1, 0):
        gj = get_json(f"{IEM}/geojson/vtec_event.py", {**base, "sbw": sbw})
        feats = gj.get("features", [])
        if feats:
            geoms = [f["geometry"] for f in feats]
            kind = "polygon" if sbw else "county"
            if len(geoms) == 1:
                return geoms[0], kind
            return {"type": "GeometryCollection", "geometries": geoms}, kind
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=START_YEAR)
    args = ap.parse_args()

    this_year = datetime.now(timezone.utc).year
    warnings = []
    for year in range(args.start_year, this_year + 1):
        d = get_json(f"{IEM}/json/vtec_events.py",
                     {"wfo": WFO, "year": year, "phenomena": "TO",
                      "significance": "W"})
        for e in d.get("events", []):
            etn = int(e["eventid"])
            geom, kind = event_geometry(year, etn)
            if geom is None:
                print(f"WARNING: no geometry for {year} TO.W #{etn} -- skipping")
                continue
            warnings.append({
                "year": year,
                "etn": etn,
                "issue": e["issue"],
                "expire": e["expire"],
                "counties": e.get("locations", ""),
                "geometry_kind": kind,
                "geometry": geom,
            })
            print(f"{e['issue']}  TO.W #{etn:<3} {kind:<8} {e.get('locations', '')}")

    out = {
        "wfo": WFO,
        "start_year": args.start_year,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "warnings": warnings,
    }
    with open("tornado_warnings.json", "w") as f:
        json.dump(out, f)
    print(f"wrote tornado_warnings.json ({len(warnings)} warnings)")


if __name__ == "__main__":
    main()
