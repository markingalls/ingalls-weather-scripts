"""
Largest Recorded Earthquake by County -- Washington, Oregon, Idaho
Ingalls Weather

Shades every WA/OR/ID county by the magnitude of the largest earthquake
whose epicenter falls inside it, from the USGS ANSS Comprehensive Catalog
(ComCat), and labels each county with that magnitude. A side box lists the
largest events on the map.

DATA SOURCE
-----------
USGS FDSN event web service (ComCat), unauthenticated GeoJSON:
    https://earthquake.usgs.gov/fdsnws/event/1/query
Queried with eventtype=earthquake (drops quarry blasts, explosions, etc.)
and orderby=magnitude, so the first event that lands in a county's polygon
is that county's maximum -- no per-county sort needed.

  Pass 1: every M2.5+ event in a box around the three states, all of
    ComCat's history (~12k events, comfortably under the service's 20,000
    per-request cap). Covers ~105 of 119 counties.
  Pass 2: for each county pass 1 left empty (quiet counties like Ada,
    Canyon, Coos, Twin Falls), query that county's own bounding box with no
    magnitude floor, largest first, and take the first event that's
    actually inside the polygon.

A county with nothing even after pass 2 is drawn in the no-data tone.

USAGE
-----
    python build_map.py                          # fetch live + render
    python build_map.py --file output/snapshot_2026-11-10.json   # re-render, no fetch

REQUIRES (shared, at repo root): maps/counties_wa_or_id.geojson,
land_slim.json, states_lakes_slim.json, admin1_boundary_lines.json,
admin0_boundary_lines.json. Logo: assets/ingalls_weather_logo.png.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import Patch
from matplotlib.transforms import offset_copy
import requests

import cartopy.crs as ccrs
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

COUNTIES_FILE = MAPS_DIR / "counties_wa_or_id.geojson"
LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# County GEOIDs are 5-digit FIPS -- first two digits are the state.
STATE_FIPS = {"53": "WA", "41": "OR", "16": "ID"}

# ---------------------------------------------------------------------------
# USGS ComCat query
# ---------------------------------------------------------------------------
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
# Box around WA/OR/ID, slightly padded so border counties' edges are in.
QUERY_BOX = dict(minlatitude=41.9, maxlatitude=49.1, minlongitude=-124.9, maxlongitude=-110.9)
PASS1_MIN_MAG = 2.5
PASS2_LIMIT = 500

# ---------------------------------------------------------------------------
# Map extent / projection (same NearsidePerspective look as
# ../columbia-basin-alerts-map/, zoomed out to the full three states)
# ---------------------------------------------------------------------------
# Padded west into the Pacific (room for the legend, clear of SW Oregon)
# and east into WY/MT (room for the logo, clear of SE Idaho).
EXTENT = [-128.6, -108.9, 41.35, 49.45]
CENTER_LON, CENTER_LAT = -118.75, 45.4

# ---------------------------------------------------------------------------
# Magnitude classes -- whole-magnitude bins (each step is ~32x the energy),
# with the top bin split at 6.5 so the handful of truly major events
# (Nisqually, Borah Peak, 1872 Chelan, ...) stand apart from the M6.0s.
# (lower bound inclusive, label, fill, label-text color)
# ---------------------------------------------------------------------------
MAG_CLASSES = [
    (6.5, "6.5+",      "#7a1a1a", "white"),
    (6.0, "6.0 – 6.4", "#b3311f", "white"),
    (5.0, "5.0 – 5.9", "#df6a2c", "white"),
    (4.0, "4.0 – 4.9", "#f0a453", "#2b2a26"),
    (3.0, "3.0 – 3.9", "#f6d38f", "#2b2a26"),
    (-9,  "Under 3.0", "#f8edcf", "#2b2a26"),
]
NO_DATA_COLOR = "#d9d6cc"
TOP_N_EVENTS = 8


def mag_class(mag):
    for lo, label, fill, text_color in MAG_CLASSES:
        if mag >= lo:
            return label, fill, text_color
    return MAG_CLASSES[-1][1:]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------
def usgs_query(params, retries=4):
    params = {"format": "geojson", "eventtype": "earthquake", "orderby": "magnitude",
              "starttime": "1700-01-01", **params}
    for attempt in range(retries):
        try:
            resp = requests.get(USGS_URL, params=params, timeout=120)
            resp.raise_for_status()
            return resp.json()["features"]
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  USGS request failed ({e}); retrying in {wait}s")
            time.sleep(wait)


def load_counties():
    data = json.loads(COUNTIES_FILE.read_text())
    counties = []
    for f in data["features"]:
        geoid = f["properties"]["id"]
        counties.append({"geoid": geoid, "name": f["properties"]["name"],
                         "state": STATE_FIPS.get(geoid[:2], "?"),
                         "geom": shape(f["geometry"])})
    return counties


def event_record(feat):
    p = feat["properties"]
    lon, lat = feat["geometry"]["coordinates"][:2]
    t = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=p["time"])
    return {"id": feat["id"], "mag": p["mag"], "mag_type": p.get("magType"),
            "time": t.isoformat(), "place": p.get("place"), "title": p.get("title"),
            "lon": lon, "lat": lat, "url": p.get("url")}


def fetch_county_maxima(counties):
    """Returns {geoid: event_record or None}."""
    geoms = [c["geom"] for c in counties]
    tree = STRtree(geoms)
    best = {}

    print(f"Pass 1: all M{PASS1_MIN_MAG}+ earthquakes in the WA/OR/ID box ...")
    feats = usgs_query({**QUERY_BOX, "minmagnitude": PASS1_MIN_MAG})
    print(f"  {len(feats)} events")
    for feat in feats:
        if feat["properties"]["mag"] is None:
            continue
        lon, lat = feat["geometry"]["coordinates"][:2]
        for i in tree.query(Point(lon, lat), predicate="intersects"):
            geoid = counties[i]["geoid"]
            if geoid not in best:  # orderby=magnitude -> first hit is the max
                best[geoid] = event_record(feat)

    missing = [c for c in counties if c["geoid"] not in best]
    print(f"  {len(best)} of {len(counties)} counties assigned; pass 2 for {len(missing)} more ...")
    for c in missing:
        minx, miny, maxx, maxy = c["geom"].bounds
        # The bbox can overlap busier neighbors, so page (largest first)
        # until an event lands inside this county's polygon or the box runs dry.
        hit, offset = None, 1
        while hit is None:
            feats = usgs_query({"minlatitude": miny, "maxlatitude": maxy,
                                "minlongitude": minx, "maxlongitude": maxx,
                                "limit": PASS2_LIMIT, "offset": offset})
            for feat in feats:
                if feat["properties"]["mag"] is None:
                    continue
                lon, lat = feat["geometry"]["coordinates"][:2]
                if c["geom"].intersects(Point(lon, lat)):
                    hit = event_record(feat)
                    break
            if len(feats) < PASS2_LIMIT:
                break
            offset += PASS2_LIMIT
        best[c["geoid"]] = hit
        desc = f"M{hit['mag']:.1f}" if hit else "nothing on record"
        print(f"    {c['name']} Co., {c['state']}: {desc}")
    return best


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_geoms(path, keep=lambda props: True):
    data = json.loads(Path(path).read_text())
    return [shape(f["geometry"]) for f in data["features"]
            if f.get("geometry") and keep(f["properties"])]


def event_label(ev):
    """Short name for the top-events box: USGS's own named-event title if
    it has one ("The 2001 Nisqually, Washington Earthquake" -> "Nisqually"),
    else just the year."""
    place = ev.get("place") or ""
    if place.startswith("The ") and place.endswith(" Earthquake"):
        core = place[4:-len(" Earthquake")]           # "2001 Nisqually, Washington"
        core = core.split(",")[0]                       # "2001 Nisqually"
        parts = core.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            return parts[1]
        return core
    return None


def build_map(maxima, counties, output_path, fetched_at):
    f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
    f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
    f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                    satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes([0.04, 0.045, 0.92, 0.82], projection=proj)
    ax.set_facecolor("white")
    ax.set_extent(EXTENT, crs=pc)

    # ---------- basemap ----------
    ax.add_geometries(load_geoms(LAND_FILE), crs=pc, facecolor="#e3e1da", edgecolor="none", zorder=1)

    lake_geoms = load_geoms(STATES_LAKES_FILE, lambda p: "Lake" in p.get("featurecla", "")
                            and p.get("admin") in ("United States of America", "Canada"))

    # ---------- county choropleth ----------
    present_classes = set()
    for c in counties:
        ev = maxima.get(c["geoid"])
        if ev is None:
            fill = NO_DATA_COLOR
        else:
            label, fill, _ = mag_class(ev["mag"])
            present_classes.add(label)
        ax.add_geometries([c["geom"]], crs=pc, facecolor=fill, edgecolor="#8f8b80",
                          linewidth=0.45, zorder=2)

    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#b9b6ac",
                      linewidth=0.5, zorder=2.5)
    ax.add_geometries(load_geoms(ADMIN1_LINES_FILE), crs=pc, facecolor="none",
                      edgecolor="#3f3c35", linewidth=1.2, zorder=3)
    ax.add_geometries(load_geoms(ADMIN0_LINES_FILE), crs=pc, facecolor="none",
                      edgecolor="#2b2a26", linewidth=1.4, zorder=3.1)

    # ---------- per-county magnitude labels ----------
    # Counties that get a top-event star have their label nudged up so the
    # star (often near the representative point) doesn't sit on the number.
    ranked = sorted(((ev, c) for c in counties if (ev := maxima.get(c["geoid"]))),
                    key=lambda ec: -ec[0]["mag"])[:TOP_N_EVENTS]
    starred = {c["geoid"] for _, c in ranked}
    for c in counties:
        ev = maxima.get(c["geoid"])
        if ev is None:
            continue
        _, _, text_color = mag_class(ev["mag"])
        pt = c["geom"].representative_point()
        halo = "#2b2a26" if text_color == "white" else "white"
        label_tf = offset_copy(pc._as_mpl_transform(ax), fig=fig, x=0,
                               y=9 if c["geoid"] in starred else 0, units="points")
        txt = ax.text(pt.x, pt.y, f"{ev['mag']:.1f}", transform=label_tf, ha="center", va="center",
                      fontproperties=f_med, fontsize=7.6, color=text_color, zorder=6)
        txt.set_path_effects([pe.withStroke(linewidth=1.4, foreground=halo, alpha=0.45)])

    # ---------- epicenters of the top events ----------
    for ev, _ in ranked:
        ax.plot(ev["lon"], ev["lat"], marker="*", markersize=11, color="#ffd23f",
                mec="#2b2a26", mew=0.8, transform=pc, zorder=7)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    fig.canvas.draw()
    map_pos = ax.get_position()
    left_x, right_x, top_y = map_pos.x0, map_pos.x1, map_pos.y1
    center_x = (map_pos.x0 + map_pos.x1) / 2

    # ---------- title / subtitle ----------
    years = [datetime.fromisoformat(ev["time"]).year for ev in maxima.values() if ev]
    subtitle_y = top_y + 0.018
    title_y = subtitle_y + 0.035
    fig.text(left_x, title_y, "Largest Recorded Earthquake by County",
             fontproperties=f_bold, fontsize=22, color="#2b2a26")
    fig.text(left_x, subtitle_y,
             f"Washington, Oregon & Idaho  •  Max magnitude at epicenter, {min(years)}–{fetched_at:%Y}",
             fontproperties=f_reg, fontsize=12, color="#5a584f")

    # ---------- magnitude legend (lower-left, over the Pacific) ----------
    handles = []
    for lo, label, fill, _ in MAG_CLASSES:
        if label in present_classes:
            handles.append(Patch(facecolor=fill, edgecolor="#8f8b80", label=f"M {label}"))
    if any(ev is None for ev in maxima.values()):
        handles.append(Patch(facecolor=NO_DATA_COLOR, edgecolor="#8f8b80", label="None on record"))
    leg = fig.legend(handles=handles, loc="lower left", title="Largest magnitude",
                     bbox_to_anchor=(left_x + 0.012, map_pos.y0 + 0.012),
                     bbox_transform=fig.transFigure, frameon=True, facecolor="white",
                     edgecolor="#d8d5cc", framealpha=1.0, prop=f_reg, fontsize=10,
                     title_fontproperties=f_med, borderpad=0.8)
    leg.get_title().set_fontsize(10.5)
    leg.get_frame().set_linewidth(0.8)

    # ---------- top-events box (upper-right, over Montana) ----------
    lines = []
    for ev, c in ranked:
        year = datetime.fromisoformat(ev["time"]).year
        name = event_label(ev)
        what = f"{name} ({year})" if name else f"{year}"
        lines.append(f"M{ev['mag']:.1f}   {c['name']} Co., {c['state']}  –  {what}")
    box_txt = fig.text(right_x - 0.012, top_y - 0.014,
                       "$\\bigstar$  Largest events on the map\n" + "\n".join(lines),
                       fontproperties=f_reg, fontsize=8.6, color="#2b2a26", ha="right", va="top", multialignment="left",
                       linespacing=1.55, zorder=20,
                       bbox=dict(boxstyle="round,pad=0.7", facecolor="white", edgecolor="#d8d5cc",
                                 linewidth=0.8))

    # ---------- logo (bottom-right, ~8% of map width, ~22px inset) ----------
    if LOGO_FILE.exists():
        logo_img = plt.imread(LOGO_FILE)
        img_h, img_w = logo_img.shape[:2]
        fig_w_in, fig_h_in = fig.get_size_inches()
        dpi = fig.get_dpi()
        inset_x = 22 / (fig_w_in * dpi)
        inset_y = 22 / (fig_h_in * dpi)
        logo_w = 0.08 * (map_pos.x1 - map_pos.x0)
        logo_h = logo_w * fig_w_in * (img_h / img_w) / fig_h_in
        logo_ax = fig.add_axes([map_pos.x1 - inset_x - logo_w, map_pos.y0 + inset_y, logo_w, logo_h],
                               zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_FILE} -- skipping logo placement.")

    # ---------- attribution ----------
    fig.text(center_x, map_pos.y0 - 0.035,
             f"USGS ANSS ComCat (retrieved {fetched_at:%d %b %Y}) / US Census (counties) — Ingalls Weather",
             fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"Saved {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather WA/OR/ID map of the largest earthquake per county.")
    parser.add_argument("--file", type=Path, default=None,
                        help="Render from a saved snapshot (.json) instead of querying USGS.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/county_max_earthquake_<date>.png).")
    args = parser.parse_args()

    counties = load_counties()
    if args.file:
        if not args.file.exists():
            sys.exit(f"--file {args.file} not found.")
        snap = json.loads(args.file.read_text())
        maxima, fetched_at = snap["maxima"], datetime.fromisoformat(snap["fetched_at"])
    else:
        fetched_at = datetime.now(LOCAL_TZ)
        maxima = fetch_county_maxima(counties)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snap_path = OUTPUT_DIR / f"snapshot_{fetched_at:%Y-%m-%d}.json"
        snap_path.write_text(json.dumps({"fetched_at": fetched_at.isoformat(), "maxima": maxima}, indent=1))
        print(f"Saved snapshot to {snap_path}")

    out_path = args.out or (OUTPUT_DIR / f"county_max_earthquake_{fetched_at:%Y-%m-%d}.png")
    build_map(maxima, counties, out_path, fetched_at)


if __name__ == "__main__":
    main()
