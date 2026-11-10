"""
One-time builder for the geology layers this map draws, written into
../maps/ alongside the other shared basemap data:

  ../maps/wallowa_county_geology.geojson -- geologic map units, clipped to
      Wallowa County (FIPS 41063), with each unit's SGMC code, name, age,
      and its class in the shared color table (../maps/geology_classes.json,
      assigned by ../maps/geology_sgmc.py -- the same crosswalk any other
      state's map uses, so colors match across states)
  ../maps/wallowa_county_faults.geojson  -- faults (normal + thrust),
      clipped to the county, with SGMC's certain/approximate/concealed
      description

Source: USGS State Geologic Map Compilation (SGMC; Horton and others,
2017, USGS Data Series 1052), Oregon file -- which for Oregon is Walker
and MacLeod's 1:500,000 Geologic Map of Oregon (1991). Downloaded from
https://mrdata.usgs.gov/geology/state/ (public, no key).

Only needs rerunning for a newer SGMC release or a crosswalk change.
"""
import io
import json
import sys
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import mapping

SGMC_OR = "https://mrdata.usgs.gov/geology/state/shp/OR.zip"
WALLOWA_FIPS = "41063"
MAPS_DIR = "../maps"

sys.path.insert(0, MAPS_DIR)
from geology_sgmc import classify_state  # noqa: E402  shared, state-agnostic crosswalk

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

    classes = classify_state("/tmp/sgmc_or", "OR")
    units = pd.read_csv("/tmp/sgmc_or/OR_units.csv")
    units["unit_link"] = units["unit_link"].str.strip()
    meta = units.set_index("unit_link")[["unit_name", "unit_age"]].to_dict("index")

    poly = gpd.read_file("/tmp/sgmc_or/OR_geol_poly.shp").to_crs(4326)
    poly = gpd.clip(poly, county)
    feats = []
    for _, row in poly.iterrows():
        code = row.UNIT_LINK.replace("OR", "", 1).split(";")[0]
        m = meta.get(row.UNIT_LINK, {})
        feats.append({"type": "Feature",
                      "properties": {"code": code, "class": classes[row.UNIT_LINK],
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
