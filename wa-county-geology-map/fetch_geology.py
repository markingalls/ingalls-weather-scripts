"""
Fetches everything build_map.py needs for one Washington county and writes
it to data/<county>_*.geojson:

  <county>_geology.geojson -- Washington DNR 1:100,000 geologic map units,
      clipped to the county, each tagged with its class in the shared color
      table (../maps/geology_classes.json, via ../maps/geology_wadnr.py)
  <county>_faults.geojson  -- DNR 1:100,000 faults, clipped to the county
  <county>_roads.geojson   -- US Census TIGER primary/secondary roads
      (US/state highways) around the county, for the smaller-highway layer
  <county>_places.geojson  -- incorporated cities/towns in the county
      (TIGER places), for labels

Sources (all public, no key):
  - WA DNR "100K Surface Geology WA GeMS" ArcGIS FeatureServer
  - US Census TIGER/Line 2024 (PRISECROADS, PLACE)

Usage:  python3 fetch_geology.py --county Adams
"""
import argparse
import json
import os
import re
import sys

import geopandas as gpd
import requests
from shapely.geometry import box, mapping, shape

MAPS_DIR = "../maps"
sys.path.insert(0, MAPS_DIR)
from geology_wadnr import classify  # noqa: E402

DNR = ("https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/"
       "100K_Surface_Geology_WA_GeMS/FeatureServer")
UNITS_LAYER, FAULTS_LAYER, DMU_TABLE = 11, 7, 13
TIGER = "https://www2.census.gov/geo/tiger/TIGER2024"
WA_FIPS = "53"
CONTEXT_PAD = 0.6  # degrees of roads fetched around the county


def slug(county):
    return re.sub(r"[^a-z0-9]+", "_", county.lower()).strip("_")


def county_shape(county):
    gdf = gpd.read_file(f"{MAPS_DIR}/counties_wa_or_id.geojson")
    hit = gdf[(gdf["id"].str.startswith(WA_FIPS)) & (gdf["name"].str.lower() == county.lower())]
    if hit.empty:
        raise SystemExit(f"no Washington county named {county!r}")
    return hit.geometry.union_all()


def dnr_query(layer, envelope, fields):
    """All features of a DNR layer intersecting an envelope. Pages by
    object id: the service caps each response, and GeoJSON offset paging
    stops early."""
    base = f"{DNR}/{layer}/query"
    geom = {"geometry": json.dumps(envelope), "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"}
    r = requests.get(base, params={**geom, "where": "1=1", "returnIdsOnly": "true",
                                   "f": "json"}, timeout=120)
    r.raise_for_status()
    ids = r.json().get("objectIds") or []
    feats = []
    for i in range(0, len(ids), 200):
        r = requests.post(base, data={"objectIds": ",".join(map(str, ids[i:i + 200])),
                                      "outFields": fields, "outSR": 4326,
                                      "f": "geojson"}, timeout=180)
        r.raise_for_status()
        feats += r.json()["features"]
    if len(feats) != len(ids):
        raise SystemExit(f"layer {layer}: got {len(feats)} of {len(ids)} features")
    return feats


def dnr_dmu():
    """Description of Map Units: symbol -> (name, age, description)."""
    out, offset = {}, 0
    while True:
        r = requests.get(f"{DNR}/{DMU_TABLE}/query", params={
            "where": "1=1", "f": "json", "resultOffset": offset, "resultRecordCount": 2000,
            "outFields": "DMU_100K_MAP_UNIT,DMU_100K_FULL_NAME,DMU_100K_AGE,DMU_100K_DESCRIPTION"},
            timeout=120)
        r.raise_for_status()
        rows = [f["attributes"] for f in r.json()["features"]]
        for a in rows:
            out.setdefault(a["DMU_100K_MAP_UNIT"], (a["DMU_100K_FULL_NAME"] or "",
                                                    a["DMU_100K_AGE"] or "",
                                                    a["DMU_100K_DESCRIPTION"] or ""))
        offset += len(rows)
        if len(rows) < 2000:
            return out


def round_coords(geom_json, nd=5):
    def r(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    geom_json["coordinates"] = r(geom_json["coordinates"])
    return geom_json


def write(features, path):
    with open(path, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh,
                  separators=(",", ":"))
    print(f"wrote {path} ({len(features)} features)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--county", required=True, help='Washington county name, e.g. "Adams"')
    args = ap.parse_args()
    name = slug(args.county)
    os.makedirs("data", exist_ok=True)

    county = county_shape(args.county)
    x0, y0, x1, y1 = county.bounds
    env = {"xmin": x0 - 0.02, "ymin": y0 - 0.02, "xmax": x1 + 0.02, "ymax": y1 + 0.02,
           "spatialReference": {"wkid": 4326}}

    # ---- geology units ----
    print("fetching DNR map units ...")
    dmu = dnr_dmu()
    unit_feats = dnr_query(UNITS_LAYER, env, "MAP_UNIT_100K")
    out = []
    for f in unit_feats:
        g = shape(f["geometry"]).buffer(0).intersection(county)
        if g.is_empty:
            continue
        sym = f["properties"]["MAP_UNIT_100K"]
        uname, age, desc = dmu.get(sym, ("", "", ""))
        out.append({"type": "Feature",
                    "properties": {"code": sym, "class": classify(sym, uname, age, desc),
                                   "name": uname, "age": age},
                    "geometry": round_coords(mapping(g))})
    write(out, f"data/{name}_geology.geojson")

    # ---- faults ----
    fault_feats = dnr_query(FAULTS_LAYER, env, "FAULTS_100K_DESC,FAULTS_100K_IS_CONCEALED")
    out = []
    for f in fault_feats:
        g = shape(f["geometry"]).intersection(county)
        if g.is_empty:
            continue
        p = f["properties"]
        out.append({"type": "Feature",
                     "properties": {"descript": p["FAULTS_100K_DESC"],
                                    "concealed": p["FAULTS_100K_IS_CONCEALED"] == "Y"},
                     "geometry": round_coords(mapping(g))})
    write(out, f"data/{name}_faults.geojson")

    # ---- smaller highways (TIGER) ----
    clip = box(x0 - CONTEXT_PAD, y0 - CONTEXT_PAD, x1 + CONTEXT_PAD, y1 + CONTEXT_PAD)
    roads = gpd.read_file(f"{TIGER}/PRISECROADS/tl_2024_{WA_FIPS}_prisecroads.zip")
    roads = roads[roads.intersects(clip)]
    write([{"type": "Feature", "properties": {"name": r.FULLNAME, "mtfcc": r.MTFCC},
            "geometry": round_coords(mapping(r.geometry.intersection(clip).simplify(0.0005)), 4)}
           for r in roads.itertuples() if not r.geometry.intersection(clip).is_empty],
          f"data/{name}_roads.geojson")

    # ---- incorporated places (labels) ----
    places = gpd.read_file(f"{TIGER}/PLACE/tl_2024_{WA_FIPS}_place.zip")
    places = places[places.CLASSFP.str.startswith("C")]  # incorporated cities/towns
    out = []
    for p in places.itertuples():
        pt = p.geometry.representative_point()
        if county.contains(pt):
            out.append({"type": "Feature", "properties": {"name": p.NAME},
                        "geometry": mapping(pt)})
    write(out, f"data/{name}_places.geojson")


if __name__ == "__main__":
    main()
