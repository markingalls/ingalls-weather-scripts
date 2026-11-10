"""
One-time builder for the geology layers this map draws, written into
../maps/ alongside the other shared basemap data:

  ../maps/wallowa_county_geology.geojson -- geologic map units, clipped to
      Wallowa County (FIPS 41063), with each unit's SGMC code, name, age,
      and the simplified legend group build_map.py colors it by
  ../maps/wallowa_county_faults.geojson  -- faults (normal + thrust),
      clipped to the county, with SGMC's certain/approximate/concealed
      description

Source: USGS State Geologic Map Compilation (SGMC; Horton and others,
2017, USGS Data Series 1052), Oregon file -- which for Oregon is Walker
and MacLeod's 1:500,000 Geologic Map of Oregon (1991). Downloaded from
https://mrdata.usgs.gov/geology/state/ (public, no key).

Only needs rerunning to pick up a newer SGMC release or change GROUPS.
"""
import io
import json
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import mapping

SGMC_OR = "https://mrdata.usgs.gov/geology/state/shp/OR.zip"
WALLOWA_FIPS = "41063"
MAPS_DIR = "../maps"

# SGMC unit code -> legend group. Groups are ordered youngest -> oldest in
# build_map.py's legend. Everything mapped in Wallowa County is listed;
# an unlisted code raises so a new SGMC release can't silently drop a unit.
GROUPS = {
    # Ice Age to today: glacial moraines (Wallowa Lake), river alluvium,
    # fans, landslides, and Pleistocene lake/stream sediment.
    "Qal": "surficial", "Qs": "surficial", "Qg": "surficial",
    "Qf": "surficial", "Qls": "surficial",
    # Columbia River Basalt Group above the Imnaha (Grande Ronde, Wanapum,
    # Saddle Mountains), plus undivided CRB flows, Miocene sediment
    # interbeds, and small younger vent deposits.
    "Tcg": "crb", "Tcw": "crb", "Tcs": "crb", "Tc": "crb",
    "Tlf": "crb", "Tvm": "crb", "QTvs": "crb",
    # The oldest Columbia River Basalt flows, fed by the Chief Joseph dikes.
    "Tci": "imnaha",
    # Wallowa batholith and related intrusions.
    "KJi": "granite", "JTRgd2": "granite",
    # Wallowa terrane, island-arc volcanic rocks (Clover Creek Greenstone
    # and similar).
    "TRv": "arc_volcanic", "TRsv": "arc_volcanic", "TRPsv": "arc_volcanic",
    "Psv": "arc_volcanic",
    # Wallowa terrane, marine sedimentary rocks (Martin Bridge Limestone,
    # Hurwal Formation, and similar).
    "TRs": "marine_sed", "JTRs": "marine_sed", "Js2": "marine_sed",
    "TRPZs2": "marine_sed",
    "water": "water",
}


def round_coords(geom_json, nd=4):
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
    print(f"downloading {SGMC_OR} ...")
    r = requests.get(SGMC_OR, timeout=300)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    zf.extractall("/tmp/sgmc_or")

    counties = gpd.read_file(f"{MAPS_DIR}/counties_wa_or_id.geojson")
    county = counties[counties["id"] == WALLOWA_FIPS].geometry.union_all()

    units = pd.read_csv("/tmp/sgmc_or/OR_units.csv")
    units["unit_link"] = units["unit_link"].str.strip()
    meta = units.set_index("unit_link")[["unit_name", "unit_age"]].to_dict("index")

    poly = gpd.read_file("/tmp/sgmc_or/OR_geol_poly.shp").to_crs(4326)
    poly = gpd.clip(poly, county)
    feats = []
    for _, row in poly.iterrows():
        code = row.UNIT_LINK.replace("OR", "", 1).split(";")[0]
        if code not in GROUPS:
            raise SystemExit(f"unmapped SGMC unit {code} -- add it to GROUPS")
        m = meta.get(row.UNIT_LINK, {})
        feats.append({"type": "Feature",
                      "properties": {"code": code, "group": GROUPS[code],
                                     "name": m.get("unit_name"),
                                     "age": m.get("unit_age")},
                      "geometry": round_coords(mapping(row.geometry))})
    write(feats, f"{MAPS_DIR}/wallowa_county_geology.geojson")

    lines = gpd.read_file("/tmp/sgmc_or/OR_structure.shp").to_crs(4326)
    lines = lines[lines.DESCRIPT.str.contains("fault", case=False, na=False)]
    lines = gpd.clip(lines, county)
    feats = [{"type": "Feature",
              "properties": {"descript": row.DESCRIPT, "misc": row.MISC},
              "geometry": round_coords(mapping(row.geometry))}
             for _, row in lines.iterrows() if not row.geometry.is_empty]
    write(feats, f"{MAPS_DIR}/wallowa_county_faults.geojson")


if __name__ == "__main__":
    main()
