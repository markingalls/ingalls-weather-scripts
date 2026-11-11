"""
Fetches everything build_map.py needs for one Washington county and writes
it to data/<county>_*.geojson:

  <county>_geology.geojson -- Washington DNR 1:100,000 geologic map units,
      clipped to the county, each tagged with its class in the shared color
      table (../maps/geology_classes.json, via ../maps/geology_wadnr.py)
  <county>_faults.geojson  -- DNR 1:100,000 faults, clipped to the county
  <county>_folds.geojson   -- DNR 1:100,000 anticlines and synclines,
      clipped to the county
  <county>_roads.geojson   -- US Census TIGER primary/secondary roads
      (US/state highways) around the county, for the smaller-highway layer
  <county>_water.geojson   -- larger lakes, reservoirs and river reaches in
      and around the county (TIGER AREAWATER), for context
  <county>_places.geojson  -- incorporated cities/towns in and around the
      county (TIGER places), for labels; in_county marks the ones that get
      labeled by default

Sources (all public, no key):
  - WA DNR "100K Surface Geology WA GeMS" ArcGIS FeatureServer, patched
    from DNR's "250k Surface Geology" MapServer wherever 100k polygons are
    corrupted (detected automatically; see DEFECT_SEGMENT_M)
  - US Census TIGER/Line 2024 (PRISECROADS, PLACE)

Usage:  python3 fetch_geology.py --county Adams
"""
import argparse
import json
import os
import re
import sys

import geopandas as gpd
import numpy as np
import requests
from shapely.ops import unary_union
from shapely.geometry import Point, box, mapping, shape

MAPS_DIR = "../maps"
sys.path.insert(0, MAPS_DIR)
from geology_wadnr import classify  # noqa: E402

DNR = ("https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/"
       "100K_Surface_Geology_WA_GeMS/FeatureServer")
UNITS_LAYER, FOLDS_LAYER, FAULTS_LAYER, DMU_TABLE = 11, 6, 7, 13
# DNR's 1:250,000 map -- used only to patch areas where the 100k data is
# defective (see patch_defects).
DNR_250K = "https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/250k_Surface_Geology/MapServer"
UNITS_250K, DMU_250K = 8, 7
# Real 1:100k contacts never run straight for kilometers; DNR's published
# 100k layer has a few corrupted polygons (e.g. fan-shaped wedges around
# Clarkston/Asotin) whose rings jump 5-7 km in one segment.
DEFECT_SEGMENT_M = 5000
# Patch seams follow the corrupted polygons' straight edges; once the
# defects cover this much of a county, draw the whole county from 1:250k
# instead (consistent linework, no seams).
WHOLE_250K_SHARE = 0.4
TIGER = "https://www2.census.gov/geo/tiger/TIGER2024"
WA_FIPS = "53"
CONTEXT_PAD = 0.6  # degrees of roads/water/places fetched around the county
MIN_WATER_M2 = 1_500_000  # only lakes/reservoirs/river reaches >= 1.5 km^2


def slug(county):
    return re.sub(r"[^a-z0-9]+", "_", county.lower()).strip("_")


def county_shape(county):
    gdf = gpd.read_file(f"{MAPS_DIR}/counties_wa_or_id.geojson")
    hit = gdf[(gdf["id"].str.startswith(WA_FIPS)) & (gdf["name"].str.lower() == county.lower())]
    if hit.empty:
        raise SystemExit(f"no Washington county named {county!r}")
    return hit.geometry.union_all()


def dnr_query(layer, envelope, fields, service=DNR):
    """All features of a DNR layer intersecting an envelope. Pages by
    object id: the service caps each response, and GeoJSON offset paging
    stops early."""
    base = f"{service}/{layer}/query"
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


def longest_segment_m(geom):
    """Longest straight segment in any ring, in meters (local flat-earth
    scaling is plenty for a 5 km threshold)."""
    best = 0.0
    for poly in getattr(geom, "geoms", [geom]):
        for ring in [poly.exterior, *poly.interiors]:
            c = np.asarray(ring.coords)
            dx = np.diff(c[:, 0]) * 111_320 * np.cos(np.radians(c[:-1, 1]))
            dy = np.diff(c[:, 1]) * 110_540
            if len(dx):
                best = max(best, float(np.hypot(dx, dy).max()))
    return best


def dnr_250k_units(envelope, region):
    """DNR 1:250k units inside `region`, classified like the 100k ones.
    250k symbols carry a sheet suffix (Ql_SE); the DMU table is keyed by
    the suffixed symbol, the crosswalk by the bare one."""
    feats = dnr_query(UNITS_250K, envelope, "MapUnit", service=DNR_250K)
    units = sorted({f["properties"]["MapUnit"] for f in feats})
    dmu = {}
    for i in range(0, len(units), 50):
        where = "MapUnit IN (%s)" % ",".join("'%s'" % u.replace("'", "''") for u in units[i:i + 50])
        r = requests.post(f"{DNR_250K}/{DMU_250K}/query", data={
            "where": where, "outFields": "MapUnit,Name,Age,Description", "f": "json"}, timeout=120)
        r.raise_for_status()
        for f in r.json()["features"]:
            a = f["attributes"]
            dmu[a["MapUnit"]] = (a["Name"] or "", a["Age"] or "", a["Description"] or "")
    out = []
    for f in feats:
        g = shape(f["geometry"]).buffer(0).intersection(region)
        if g.is_empty:
            continue
        unit = f["properties"]["MapUnit"]
        sym = re.sub(r"_[NS][EW]$", "", unit)
        uname, age, desc = dmu.get(unit, ("", "", ""))
        out.append((g, sym, uname, age, desc))
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
    good, defective = [], []
    for f in unit_feats:
        raw = shape(f["geometry"]).buffer(0)
        (defective if longest_segment_m(raw) > DEFECT_SEGMENT_M else good).append((raw, f))
    patch = unary_union([raw for raw, _ in defective]).intersection(county) if defective else None
    if patch is not None and patch.area / county.area < 1e-5:
        patch = None  # defects only touch the county's edge -- nothing to patch
    if patch is not None and patch.area / county.area > WHOLE_250K_SHARE:
        print(f"  defective 100k polygons cover {patch.area / county.area:.0%} of the county "
              "-- using DNR 1:250k for the whole county")
        patch = county
    elif patch is not None:
        print(f"  {len(defective)} defective 100k polygons (straight edges > "
              f"{DEFECT_SEGMENT_M / 1000:g} km); patching {patch.area / county.area:.2%} "
              "of the county from 1:250k")

    out = []
    for raw, f in good:
        g = raw.intersection(county)
        if patch is not None:
            g = g.difference(patch)
        if g.is_empty:
            continue
        sym = f["properties"]["MAP_UNIT_100K"]
        uname, age, desc = dmu.get(sym, ("", "", ""))
        out.append({"type": "Feature",
                    "properties": {"code": sym, "class": classify(sym, uname, age, desc),
                                   "name": uname, "age": age, "source": "100k"},
                    "geometry": round_coords(mapping(g))})
    if patch is not None and not patch.is_empty:
        for g, sym, uname, age, desc in dnr_250k_units(env, patch):
            out.append({"type": "Feature",
                        "properties": {"code": sym, "class": classify(sym, uname, age, desc),
                                       "name": uname, "age": age, "source": "250k"},
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

    # ---- folds (anticlines + synclines; monoclines left out) ----
    fold_feats = dnr_query(FOLDS_LAYER, env, "FOLDS_100K_TYPE,FOLDS_100K_IS_CONCEALED")
    out = []
    for f in fold_feats:
        p = f["properties"]
        if p["FOLDS_100K_TYPE"] not in ("Anticline", "Syncline"):
            continue
        g = shape(f["geometry"]).intersection(county)
        if g.is_empty:
            continue
        out.append({"type": "Feature",
                    "properties": {"type": p["FOLDS_100K_TYPE"].lower(),
                                   "concealed": p["FOLDS_100K_IS_CONCEALED"] == "Y"},
                    "geometry": round_coords(mapping(g))})
    write(out, f"data/{name}_folds.geojson")

    # ---- smaller highways (TIGER) ----
    clip = box(x0 - CONTEXT_PAD, y0 - CONTEXT_PAD, x1 + CONTEXT_PAD, y1 + CONTEXT_PAD)
    roads = gpd.read_file(f"{TIGER}/PRISECROADS/tl_2024_{WA_FIPS}_prisecroads.zip")
    roads = roads[roads.intersects(clip)]
    write([{"type": "Feature", "properties": {"name": r.FULLNAME, "mtfcc": r.MTFCC},
            "geometry": round_coords(mapping(r.geometry.intersection(clip).simplify(0.0005)), 4)}
           for r in roads.itertuples() if not r.geometry.intersection(clip).is_empty],
          f"data/{name}_roads.geojson")

    # ---- big water bodies around the county (context; TIGER AREAWATER) ----
    counties_all = gpd.read_file(f"{MAPS_DIR}/counties_wa_or_id.geojson")
    near = counties_all[counties_all["id"].str.startswith(WA_FIPS) & counties_all.intersects(clip)]
    out = []
    for fips in sorted(near["id"]):
        water = gpd.read_file(f"{TIGER}/AREAWATER/tl_2024_{fips}_areawater.zip")
        water = water[(water.AWATER > MIN_WATER_M2) & water.intersects(clip)]
        for w in water.itertuples():
            g = w.geometry.intersection(clip).simplify(0.0003)
            if not g.is_empty:
                out.append({"type": "Feature", "properties": {"name": w.FULLNAME},
                            "geometry": round_coords(mapping(g), 4)})
    write(out, f"data/{name}_water.geojson")

    # ---- incorporated places (labels) ----
    places = gpd.read_file(f"{TIGER}/PLACE/tl_2024_{WA_FIPS}_place.zip")
    places = places[places.CLASSFP.str.startswith("C")]  # incorporated cities/towns
    out = []
    for p in places.itertuples():
        # Census's own internal point (INTPTLAT/LON) sits at the town
        # center; a computed point-in-polygon can land anywhere inside a
        # sprawling city limit (Moses Lake's fell south of I-90).
        pt = Point(float(p.INTPTLON), float(p.INTPTLAT))
        if clip.contains(pt):
            out.append({"type": "Feature",
                        "properties": {"name": p.NAME, "in_county": county.contains(pt)},
                        "geometry": mapping(pt)})
    write(out, f"data/{name}_places.geojson")


if __name__ == "__main__":
    main()
