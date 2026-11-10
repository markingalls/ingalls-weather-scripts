"""
One-time builder for the extra basemap layers this map needs that aren't
in ../maps/ yet: smaller highways (US/state routes below trunk) and
Wallowa Lake. The shared OSM road files only carry motorway/trunk, and the
Natural Earth lakes in states_lakes_slim.json don't include lakes this
small, so both come from US Census TIGER/Line instead.

Writes (clipped to this map's extent, coordinates rounded to ~10 m):
  ../maps/wallowa_area_secondary_roads.geojson  -- TIGER PRISECROADS
      (MTFCC S1100/S1200) for OR, WA, ID
  ../maps/wallowa_lake.geojson                  -- TIGER AREAWATER,
      Wallowa County (FIPS 41063)

Only needs rerunning if the extent changes or for a newer TIGER vintage.
"""
import json

import geopandas as gpd
from shapely.geometry import box, mapping

TIGER = "https://www2.census.gov/geo/tiger/TIGER2024"
STATE_FIPS = ["41", "53", "16"]  # OR, WA, ID
# build_map.py's EXTENT, padded a little so lines run cleanly off the frame.
PAD = 0.3
CLIP = box(-118.6 - PAD, 44.65 - PAD, -116.0 + PAD, 46.3 + PAD)


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
    feats = []
    for st in STATE_FIPS:
        gdf = gpd.read_file(f"{TIGER}/PRISECROADS/tl_2024_{st}_prisecroads.zip")
        gdf = gdf[gdf.intersects(CLIP)]
        for _, row in gdf.iterrows():
            g = row.geometry.intersection(CLIP).simplify(0.0005)
            if g.is_empty:
                continue
            feats.append({"type": "Feature",
                          "properties": {"name": row.FULLNAME, "mtfcc": row.MTFCC},
                          "geometry": round_coords(mapping(g))})
    write(feats, "../maps/wallowa_area_secondary_roads.geojson")

    water = gpd.read_file(f"{TIGER}/AREAWATER/tl_2024_41063_areawater.zip")
    lake = water[water.FULLNAME == "Wallowa Lk"]
    write([{"type": "Feature", "properties": {"name": "Wallowa Lake"},
            "geometry": round_coords(mapping(g.simplify(0.0001)), 5)}
           for g in lake.geometry],
          "../maps/wallowa_lake.geojson")


if __name__ == "__main__":
    main()
