"""
Fetches everything build_map.py needs for one Washington or Oregon county
and writes it to data/<county>_*.geojson:

  <county>_geology.geojson -- geologic map units, clipped to the county,
      each tagged with its class in the shared color table
      (../maps/geology_classes.json)
  <county>_faults.geojson  -- faults, clipped to the county
  <county>_folds.geojson   -- anticlines and synclines, clipped to the county
  <county>_county.geojson / <county>_counties.geojson -- full-resolution
      TIGER outline of the county, and of the counties around it
  <county>_roads.geojson   -- US Census TIGER primary/secondary roads
      (US/state highways) around the county, in every neighboring state
  <county>_water.geojson   -- larger lakes, reservoirs and river reaches in
      and around the county (TIGER AREAWATER), for context
  <county>_places.geojson  -- incorporated cities/towns in and around the
      county (TIGER places), for labels; in_county marks the ones that get
      labeled by default

Geology sources (all public, no key):
  - Washington: WA DNR "100K Surface Geology WA GeMS" ArcGIS FeatureServer,
    patched from DNR's "250k Surface Geology" MapServer wherever 100k
    polygons are corrupted (detected automatically; see DEFECT_SEGMENT_M).
    Crosswalk: ../maps/geology_wadnr.py
  - Oregon: DOGAMI Oregon Geologic Data Compilation, release 7 (OGDC-7)
    geodatabase, downloaded once (~100 MB) and cached in data/_cache/.
    Crosswalk: ../maps/geology_ogdc.py

Usage:  python3 fetch_geology.py --state WA --county Adams
        python3 fetch_geology.py --state OR --county Baker
"""
import argparse
import io
import json
import os
import re
import sys
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.ops import unary_union
from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping, shape

MAPS_DIR = "../maps"
sys.path.insert(0, MAPS_DIR)
import geology_ogdc  # noqa: E402
import geology_wadnr  # noqa: E402

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
BORDER_TOLERANCE_M = 1500  # straight edges within this of the state line are real
# Patch seams follow the corrupted polygons' straight edges; once the
# defects cover this much of a county, draw the whole county from 1:250k
# instead (consistent linework, no seams).
WHOLE_250K_SHARE = 0.4
TIGER = "https://www2.census.gov/geo/tiger/TIGER2024"
# --state -> (FIPS, name). Neighboring states' counties, roads, water and
# places are pulled in too, from NEIGHBOR_STATES.
STATE_INFO = {"WA": ("53", "Washington"), "OR": ("41", "Oregon")}
NEIGHBOR_STATES = ["53", "41", "16", "06", "32"]  # WA, OR, ID, CA, NV

OGDC_BUNDLE = "https://pubs.oregon.gov/dogami/dds/ogdc/ogdc-7/OGDC-7_publication-bundle.zip"
OGDC_GDB = "data/_cache/OGDC7.gdb"
OGDC_CRS = "EPSG:2994"  # Oregon Lambert (ft), the geodatabase's native CRS
OGDC_NOT_FAULTS = re.compile(r"^contact|dike|key bed", re.I)
CONTEXT_PAD = 0.6  # degrees of roads/water/places fetched around the county
MIN_WATER_M2 = 1_500_000  # only lakes/reservoirs/river reaches >= 1.5 km^2


def slug(county):
    return re.sub(r"[^a-z0-9]+", "_", county.lower()).strip("_")


def data_name(state, county):
    """File prefix: state + county (e.g. or_baker), so counties that share a
    name across states (Columbia, Douglas, Grant, Lincoln...) never
    overwrite each other."""
    return f"{state.lower()}_{slug(county)}"


def cached(url):
    """Download `url` once into data/_cache/ and return the local path.
    Statewide TIGER files are shared by every county in a batch run."""
    path = os.path.join("data/_cache", os.path.basename(url))
    if not os.path.exists(path):
        os.makedirs("data/_cache", exist_ok=True)
        r = requests.get(url, timeout=900)
        r.raise_for_status()
        with open(path + ".part", "wb") as fh:
            fh.write(r.content)
        os.replace(path + ".part", path)
    return path


def tiger_counties():
    """Full-resolution TIGER/Line county polygons for WA, OR and ID. The
    national file is ~84 MB, so it's cached in data/_cache/ after the first
    download. (The repo's shared ../maps/counties_wa_or_id.geojson is
    simplified -- fine for regional maps, but it cuts corners along rivers
    at county scale.)"""
    gdf = gpd.read_file(cached(f"{TIGER}/COUNTY/tl_2024_us_county.zip"))
    return gdf[gdf.STATEFP.isin(NEIGHBOR_STATES)].to_crs(4326)


def county_shape(county, state, counties=None):
    counties = tiger_counties() if counties is None else counties
    fips, state_name = STATE_INFO[state]
    hit = counties[(counties.STATEFP == fips) & (counties.NAME.str.lower() == county.lower())]
    if hit.empty:
        raise SystemExit(f"no {state_name} county named {county!r}")
    return hit.geometry.iloc[0]


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
    """Description of Map Units: symbol -> (name, age, description).
    Statewide (~1,900 rows), so cached in data/_cache/ for batch runs."""
    path = "data/_cache/dnr_100k_dmu.json"
    if os.path.exists(path):
        return {k: tuple(v) for k, v in json.load(open(path)).items()}
    out = _dnr_dmu_fetch()
    os.makedirs("data/_cache", exist_ok=True)
    json.dump(out, open(path, "w"))
    return out


def _dnr_dmu_fetch():
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


def has_defect_segment(geom, border):
    """True if any ring has a straight segment longer than DEFECT_SEGMENT_M
    that doesn't run along `border` (the state/national boundary). DNR's
    map is clipped to the state line, which really is straight for 100+ km
    (46 N east of Wallula, 49 N, the Idaho line); everywhere else, a
    kilometers-long straight contact is a data defect."""
    for poly in getattr(geom, "geoms", [geom]):
        for ring in [poly.exterior, *poly.interiors]:
            c = np.asarray(ring.coords)
            if len(c) < 2:
                continue
            dx = np.diff(c[:, 0]) * 111_320 * np.cos(np.radians(c[:-1, 1]))
            dy = np.diff(c[:, 1]) * 110_540
            for i in np.where(np.hypot(dx, dy) > DEFECT_SEGMENT_M)[0]:
                mid = Point((c[i] + c[i + 1]) / 2)
                if mid.distance(border) * 111_000 > BORDER_TOLERANCE_M:
                    return True
    return False


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
        if g.is_empty or g.area == 0:
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


def clean_polygon(g, min_area=1e-9):
    """Make a polygon safe for cartopy. Rounding can make rings
    self-intersect, and DNR data has zero-area sliver parts; cartopy fills
    either as the *whole map* (King and Okanogan counties came out solid
    blue). Fix validity, then drop parts and holes under ~10 m^2."""
    g = g.buffer(0)
    parts = []
    for p in getattr(g, "geoms", [g]):
        if p.geom_type != "Polygon" or p.area <= min_area:
            continue
        parts.append(Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area > min_area]))
    if not parts:
        return Polygon()
    return MultiPolygon(parts) if len(parts) > 1 else parts[0]


def write(features, path):
    for f in features:
        if f["geometry"]["type"] in ("Polygon", "MultiPolygon", "GeometryCollection"):
            f["geometry"] = mapping(clean_polygon(shape(f["geometry"])))
    features = [f for f in features if not shape(f["geometry"]).is_empty]
    with open(path, "w") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh,
                  separators=(",", ":"))
    print(f"wrote {path} ({len(features)} features)")


def geology_wa(county, env, border):
    """Units, faults, folds for a Washington county from WA DNR. `border`
    is Washington's outline (for telling the straight state line apart
    from defective straight contacts)."""
    # ---- geology units ----
    print("fetching DNR map units ...")
    dmu = dnr_dmu()
    unit_feats = dnr_query(UNITS_LAYER, env, "MAP_UNIT_100K")
    good, defective = [], []
    for f in unit_feats:
        raw = shape(f["geometry"]).buffer(0)
        (defective if has_defect_segment(raw, border) else good).append((raw, f))
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
        if g.is_empty or g.area == 0:  # clipping can leave zero-area slivers
            continue
        sym = f["properties"]["MAP_UNIT_100K"]
        uname, age, desc = dmu.get(sym, ("", "", ""))
        out.append({"type": "Feature",
                    "properties": {"code": sym, "class": geology_wadnr.classify(sym, uname, age, desc),
                                   "name": uname, "age": age, "source": "100k"},
                    "geometry": round_coords(mapping(g))})
    if patch is not None and not patch.is_empty:
        for g, sym, uname, age, desc in dnr_250k_units(env, patch):
            out.append({"type": "Feature",
                        "properties": {"code": sym, "class": geology_wadnr.classify(sym, uname, age, desc),
                                       "name": uname, "age": age, "source": "250k"},
                        "geometry": round_coords(mapping(g))})
    units = out

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
    faults = out

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
    folds = out

    return units, faults, folds


def geology_or(county):
    """Units, faults, folds for an Oregon county from DOGAMI OGDC-7."""
    if not os.path.exists(OGDC_GDB):
        os.makedirs("data/_cache", exist_ok=True)
        print("downloading DOGAMI OGDC-7 (one time, ~100 MB) ...")
        r = requests.get(OGDC_BUNDLE, timeout=900)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            for member in zf.namelist():
                if member.startswith("Geodatabase/OGDC7.gdb/") and not member.endswith("/"):
                    dest = os.path.join(OGDC_GDB, os.path.basename(member))
                    os.makedirs(OGDC_GDB, exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as fh:
                        fh.write(src.read())
    county_native = gpd.GeoSeries([county], crs=4326).to_crs(OGDC_CRS)
    bbox = tuple(county_native.total_bounds)

    def read(layer):
        gdf = gpd.read_file(OGDC_GDB, layer=layer, bbox=bbox)
        return gdf[gdf.intersects(county_native.iloc[0])].to_crs(4326)

    print("reading OGDC-7 map units ...")
    units = []
    for r in read("MapUnitPolys").itertuples():
        g = r.geometry.buffer(0).intersection(county)
        if g.is_empty or g.area == 0:
            continue
        cls = geology_ogdc.classify(r.ThematicRockType, r.ThematicAge, r.ThematicTerraneGroup,
                                    r.ThematicFormation, r.MapUnitName)
        units.append({"type": "Feature",
                      "properties": {"code": r.MapUnit, "class": cls, "name": r.MapUnitName,
                                     "age": r.ThematicAge, "source": "ogdc7"},
                      "geometry": round_coords(mapping(g))})

    faults = []
    for r in read("ContactsAndFaults").itertuples():
        if not r.Type or OGDC_NOT_FAULTS.search(r.Type):
            continue
        g = r.geometry.intersection(county)
        if g.is_empty:
            continue
        concealed = r.IsConcealed == "Y" or "conceal" in str(r.LTYPE).lower()
        faults.append({"type": "Feature",
                       "properties": {"descript": r.Type, "concealed": concealed},
                       "geometry": round_coords(mapping(g))})

    folds = []
    for r in read("GeologicLines").itertuples():
        t = str(r.Type).lower()
        kind = "anticline" if ("anticline" in t or "antiform" in t) else \
               "syncline" if ("syncline" in t or "synform" in t) else None
        if kind is None or "minor" in t:
            continue
        g = r.geometry.intersection(county)
        if g.is_empty:
            continue
        concealed = r.IsConcealed == "Y" or "conceal" in str(r.LTYPE).lower()
        folds.append({"type": "Feature", "properties": {"type": kind, "concealed": concealed},
                      "geometry": round_coords(mapping(g))})
    return units, faults, folds


OSM_FILES = ["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"]
OSM_SNAP_DEG = 0.0008  # ~70 m: how close a TIGER road must be to "be" an OSM road
COUNTY_WATER_M2 = 250_000  # lakes/rivers/bays >= 0.25 km^2 are cut out of the county's land


def osm_roads(clip):
    """The repo's OSM freeway (motorway) and expressway (trunk) lines in
    `clip`. These extracts only cover parts of WA/OR/ID (roughly the
    Columbia Basin and I-5 corridor), so they refine TIGER rather than
    replace it -- see classify_roads."""
    motorway, trunk = [], []
    for fn in OSM_FILES:
        for f in json.load(open(f"{MAPS_DIR}/{fn}"))["features"]:
            hwy = f["properties"].get("highway")
            if hwy not in ("motorway", "trunk"):
                continue
            g = shape(f["geometry"])
            if g.intersects(clip):
                (motorway if hwy == "motorway" else trunk).append(g.intersection(clip))
    return unary_union(motorway), unary_union(trunk)


def classify_roads(roads, clip):
    """Split TIGER primary/secondary roads into freeway / major / state.

    TIGER covers every state, and its MTFCC S1100 ("primary road":
    divided, limited access, with interchanges) catches non-Interstate
    freeways -- SR 520, SR 167, the Bend Parkway, OR 22 at Salem. Where the
    repo's OSM extract has data it's the authority: an S1100 stretch that
    OSM maps as a trunk (expressway with at-grade crossings) is demoted to
    major highway, and an OSM motorway TIGER missed is added as freeway.
    Major highway = US routes (TIGER RTTYP U); everything else is state."""
    motorway, trunk = osm_roads(clip)
    mw_buf = motorway.buffer(OSM_SNAP_DEG) if not motorway.is_empty else None
    tr_buf = trunk.buffer(OSM_SNAP_DEG) if not trunk.is_empty else None
    out = {"freeway": [], "major": [], "state": []}
    for r in roads.itertuples():
        g = r.geometry.intersection(clip)
        if g.is_empty:
            continue
        if r.MTFCC == "S1100":
            demote = g.intersection(tr_buf) if tr_buf is not None else None
            if demote is not None and mw_buf is not None:
                demote = demote.difference(mw_buf)
            if demote is not None and not demote.is_empty and demote.length > 0:
                out["major"].append(demote)
                g = g.difference(tr_buf if mw_buf is None else tr_buf.difference(mw_buf))
            if not g.is_empty:
                out["freeway"].append(g)
        elif r.RTTYP == "U":
            out["major"].append(g)
        else:
            out["state"].append(g)
    if not motorway.is_empty:
        out["freeway"].append(motorway)
    feats = []
    for cls, geoms in out.items():
        for g in geoms:
            g = g.simplify(0.0003)
            if not g.is_empty:
                feats.append({"type": "Feature", "properties": {"class": cls},
                              "geometry": round_coords(mapping(g), 4)})
    return feats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", required=True, type=str.upper, choices=sorted(STATE_INFO))
    ap.add_argument("--county", required=True, help='county name, e.g. "Adams" or "Baker"')
    args = ap.parse_args()
    name = data_name(args.state, args.county)
    os.makedirs("data", exist_ok=True)

    counties = tiger_counties()
    county = county_shape(args.county, args.state, counties)
    fips = STATE_INFO[args.state][0]
    geoid = counties[(counties.STATEFP == fips) &
                     (counties.NAME.str.lower() == args.county.lower())].GEOID.iloc[0]
    x0, y0, x1, y1 = county.bounds
    env = {"xmin": x0 - 0.02, "ymin": y0 - 0.02, "xmax": x1 + 0.02, "ymax": y1 + 0.02,
           "spatialReference": {"wkid": 4326}}
    clip = box(x0 - CONTEXT_PAD, y0 - CONTEXT_PAD, x1 + CONTEXT_PAD, y1 + CONTEXT_PAD)
    near = counties[counties.intersects(clip)]
    states_on_map = sorted(near.STATEFP.unique())

    # ---- water: the county's own (cut out of its land) + big water around ----
    water_out, county_water = [], []
    for g_id in sorted(near.GEOID):
        water = gpd.read_file(cached(f"{TIGER}/AREAWATER/tl_2024_{g_id}_areawater.zip"))
        own = g_id == geoid
        water = water[(water.AWATER > (COUNTY_WATER_M2 if own else MIN_WATER_M2))
                      & water.intersects(clip)]
        for w in water.itertuples():
            if own:
                county_water.append(w.geometry)
            g = w.geometry.intersection(clip).simplify(0.0003)
            # simplify + rounding can leave self-intersecting rings, which
            # cartopy fills as the whole map; re-validate after rounding.
            g = shape(round_coords(mapping(g), 4)).buffer(0) if not g.is_empty else g
            if not g.is_empty:
                water_out.append({"type": "Feature", "properties": {"name": w.FULLNAME},
                                  "geometry": mapping(g)})
    write(water_out, f"data/{name}_water.geojson")

    # County land: the TIGER county reaches 3 nmi offshore and to mid-river,
    # so geology is clipped to (and the outline drawn around) its land.
    land = county.difference(unary_union(county_water).buffer(0)) if county_water else county
    land = land.buffer(0)
    # The black county outline only gives up *edge* water -- the Sound, the
    # ocean, a border river -- i.e. water running along the legal boundary.
    # Rivers and lakes inside the county (or merely crossing its
    # line) stay inside the outline instead of slicing it into pieces.
    # "Along the line" = > 1 km of shared edge AND >= 20% of the water
    # body's perimeter: the Columbia's pieces on Multnomah's line score
    # 30-45%, the Willamette (whose mouth touches it) only 4%.
    edge_water = [w for w in county_water
                  if (lambda shared: shared * 111_000 > 1000 and shared >= 0.2 * w.length)(
                      w.intersection(county.boundary).length)]
    outline = county.difference(unary_union(edge_water).buffer(0)).buffer(0) if edge_water else county
    write([{"type": "Feature", "properties": {"name": args.county, "role": "land"},
            "geometry": round_coords(mapping(land))},
           {"type": "Feature", "properties": {"name": args.county, "role": "outline"},
            "geometry": round_coords(mapping(outline))}], f"data/{name}_county.geojson")
    write([{"type": "Feature", "properties": {"geoid": c.GEOID, "state": c.STATEFP, "name": c.NAME},
            "geometry": round_coords(mapping(c.geometry.simplify(0.0002)))}
           for c in near.itertuples()], f"data/{name}_counties.geojson")

    # ---- geology ----
    if args.state == "WA":
        wa_outline = unary_union(counties[counties.STATEFP == STATE_INFO["WA"][0]].geometry).boundary
        units, faults, folds = geology_wa(land, env, wa_outline)
    else:
        units, faults, folds = geology_or(land)
    write(units, f"data/{name}_geology.geojson")
    write(faults, f"data/{name}_faults.geojson")
    write(folds, f"data/{name}_folds.geojson")

    # ---- highways (TIGER in every state on the map, refined by repo OSM) ----
    roads = pd.concat([gpd.read_file(cached(f"{TIGER}/PRISECROADS/tl_2024_{st}_prisecroads.zip"))
                       for st in states_on_map])
    write(classify_roads(roads[roads.intersects(clip)], clip), f"data/{name}_roads.geojson")

    # ---- incorporated places (labels), every state on the map ----
    out = []
    for st in states_on_map:
        places = gpd.read_file(cached(f"{TIGER}/PLACE/tl_2024_{st}_place.zip"))
        places = places[places.CLASSFP.str.startswith("C")]  # incorporated cities/towns
        for p in places.itertuples():
            # Census's own internal point (INTPTLAT/LON) sits at the town
            # center; a computed point-in-polygon can land anywhere inside a
            # sprawling city limit (Moses Lake's fell south of I-90).
            pt = Point(float(p.INTPTLON), float(p.INTPTLAT))
            if clip.contains(pt):
                out.append({"type": "Feature",
                            "properties": {"name": p.NAME, "in_county": county.contains(pt),
                                           "aland_km2": round(p.ALAND / 1e6, 2)},
                            "geometry": mapping(pt)})
    write(out, f"data/{name}_places.geojson")


if __name__ == "__main__":
    main()
