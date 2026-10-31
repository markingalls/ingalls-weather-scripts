"""
One-time basemap prep for north-america-time-zones/ and pnw-sunrise-map/
Ingalls Weather

Writes three files into ../maps/ (checked in, so the build scripts never
need network access):

  tz_boundaries_north_america.json
      IANA time zone polygons (one feature per tzid, property "tzid") for
      every zone in North America, Central America, the Caribbean,
      Greenland and Hawaii, simplified to ~0.01 deg. Sourced from the
      `timezonefinder` PyPI package, which bundles the polygons from
      evansiroky/timezone-boundary-builder (OpenStreetMap-derived). The
      polygons are only *geography* -- which tzid a place belongs to. The
      clock offsets each tzid uses after Nov 1, 2026 are assigned in the
      build scripts (see their CANADA_2026 tables), not read from here.

  na_land_50m.json, na_lakes_50m.json, na_admin1_lines_50m.json
      Natural Earth 50m land, large lakes, and state/province lines,
      cropped to North America. The existing *_slim.json files in ../maps/
      are clipped to US/Canada/Mexico (land_slim.json only reaches -85
      deg lon), which isn't enough for a continent-wide map. Sourced from
      raw.githubusercontent.com/martynafford/natural-earth-geojson.

USAGE
-----
    pip install timezonefinder
    python prepare_basemap.py
"""

import json
import urllib.request
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.validation import make_valid
from timezonefinder import TimezoneFinder

REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"

NA_BOX = box(-180.0, 5.0, -10.0, 84.0)
SIMPLIFY_DEG = 0.01
NE_BASE = "https://raw.githubusercontent.com/martynafford/natural-earth-geojson/master/50m"

EXTRA_ZONES = {"Pacific/Honolulu", "Atlantic/Bermuda"}


def tz_polygons():
    tf = TimezoneFinder()
    features = []
    for tzid in sorted(tf.timezone_names):
        if not (tzid.startswith("America/") or tzid in EXTRA_ZONES):
            continue
        polys = []
        for poly in tf.get_geometry(tz_name=tzid, coords_as_pairs=True):
            shell, *holes = poly
            polys.append(Polygon(shell, holes))
        geom = make_valid(MultiPolygon(polys)).intersection(NA_BOX)
        if geom.is_empty:
            continue
        geom = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
        features.append({"type": "Feature", "properties": {"tzid": tzid}, "geometry": mapping(geom)})
        print(f"  {tzid}")
    return features


def ne_layer(name, keep=lambda props: True):
    with urllib.request.urlopen(f"{NE_BASE}/{name}") as resp:
        data = json.load(resp)
    out = []
    for feat in data["features"]:
        if not feat.get("geometry") or not keep(feat["properties"]):
            continue
        geom = shape(feat["geometry"]).intersection(NA_BOX)
        if geom.is_empty:
            continue
        out.append({"type": "Feature", "properties": {}, "geometry": mapping(geom)})
    return out


def write(name, features):
    path = MAPS_DIR / name
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
    print(f"Wrote {path} ({path.stat().st_size / 1e6:.1f} MB, {len(features)} features)")


if __name__ == "__main__":
    print("Extracting time zone polygons...")
    write("tz_boundaries_north_america.json", tz_polygons())
    print("Fetching Natural Earth 50m layers...")
    write("na_land_50m.json", ne_layer("physical/ne_50m_land.json"))
    # Only the big lakes (Great Lakes, Winnipeg, Great Bear/Slave, etc.) --
    # smaller ones are just clutter at continent scale.
    write("na_lakes_50m.json", ne_layer("physical/ne_50m_lakes.json",
                                         keep=lambda p: (p.get("scalerank") or 9) <= 1))
    write("na_admin1_lines_50m.json", ne_layer("cultural/ne_50m_admin_1_states_provinces_lines.json"))
