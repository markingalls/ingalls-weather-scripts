"""
WM-6 Ensemble Mean Total Precipitable Water Map -- one-off builder
Ingalls Weather

Styled map spanning Hawaii (SW corner) to the northwest corner of
Saskatchewan (NE corner) -- the North Pacific, US West Coast, Great Basin,
and Western Canada in one frame:
  - Shading: WindBorne WeatherMesh-6 (global, 0.25 deg) ensemble-mean total
    column water vapour (total precipitable water), for a single valid time.

USAGE
-----
    python build_map.py                        # tomorrow, 12:00 PM Pacific
    python build_map.py --date 2026-07-30 --hour 12
    python build_map.py --file snapshot.npz     # render from a saved fetch

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

WM-6's gridded endpoint only serves per-variable/per-distribution subsets
for forecast hours still in "hot" storage; every run this was tested
against had already moved to archived storage by the time it was
requested, at which point the API only serves the complete per-hour
archive (all variables/levels/products, ~2 GB compressed) via a presigned
URL (`as_url=true`) -- see fetch_tcwv_mean()'s docstring for how this
script avoids downloading the whole thing.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    states_lakes_slim.json, admin0_boundary_lines.json, countries_slim.json
  countries_slim.json (full country polygons, not just the coastline-only
  land_slim.json, which is clipped to the Pacific Northwest and doesn't
  reach Hawaii) draws both the coastline and doubles as the land layer.
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.transforms import offset_copy
import numpy as np
import requests
import zarr
from remotezip import RemoteZip

import cartopy.crs as ccrs
import shapely
from shapely.geometry import shape, box
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

COUNTRIES_FILE = MAPS_DIR / "countries_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
VARIABLE = "total_column_water_vapour"

# ---------------------------------------------------------------------------
# Figure geometry. Under NearsidePerspective (see build_map()'s note on
# projection choice) the visible curved area doesn't fill the rectangular
# axes box the way it would under PlateCarree -- cartopy still fits the
# projection's true aspect ratio within AXES_RECT, so a mismatched
# FIG_WIDTH_IN/FIG_HEIGHT_IN just means more/less unfilled margin around
# the curved frame rather than a hard visual bug. This ratio was tuned by
# eye against the actual domain below.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.66, 9.5
FIG_DPI = 200
AXES_RECT = [0.03, 0.17, 0.94, 0.70]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- Hawaii (SW) to the northwest corner of Saskatchewan (NE,
# ~60N/110W), each padded so it's clearly visible rather than sitting right
# at the frame edge.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -164.0, -104.0
LAT_MIN, LAT_MAX = 14.0, 63.0
CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2

# Basemap geometries (country/state/border-line datasets) are sourced from
# files that extend well past this map's domain -- fine for PlateCarree,
# but reprojecting a line with far-off vertices into NearsidePerspective
# can bow it into a visibly wrong shape or, worse, cut across the frame
# entirely. Clipping every geometry to this padded box before handing it
# to add_geometries keeps every vertex within (or just outside) the
# visible area -- see clip_to_map().
MAP_CLIP_BOX = box(LON_MIN - 5, LAT_MIN - 5, LON_MAX + 5, LAT_MAX + 5)

# WM-6 is a plain regular 0.25 deg lat/lon grid (unlike wm6-3km/HRRR's
# curvilinear native grids), so cropping to the map bbox is a direct index
# slice -- no griddata resampling needed. The pad keeps the raster
# extending past the visible frame so cartopy's NearsidePerspective warp
# (a screen-pixel -> source-raster inverse lookup) has real data to sample
# right up to the curved frame's edge.
FETCH_PAD_DEG = 1.5

# ---------------------------------------------------------------------------
# Cities -- spread across the domain for geographic reference. (name, lon,
# lat, label position: "left" | "right")
# ---------------------------------------------------------------------------
CITIES = [
    ("Honolulu", -157.8583, 21.3069, "right"),
    ("Hilo", -155.0868, 19.7241, "right"),
    ("Seattle", -122.3321, 47.6062, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("San Francisco", -122.4194, 37.7749, "left"),
    ("Los Angeles", -118.2437, 34.0522, "right"),
    ("Las Vegas", -115.1398, 36.1699, "right"),
    ("Salt Lake City", -111.8910, 40.7608, "right"),
    ("Boise", -116.2023, 43.6150, "left"),
    ("Spokane", -117.4260, 47.6588, "right"),
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Prince George", -122.7497, 53.9171, "left"),
    ("Calgary", -114.0719, 51.0447, "right"),
    ("Edmonton", -113.4938, 53.5461, "left"),
    ("Saskatoon", -106.6700, 52.1332, "right"),
]

# ---------------------------------------------------------------------------
# Total precipitable water color table -- fixed inch-to-RGB control points
# (not rescaled per map), taken from Ingalls Weather's standard TPW palette
# (cream/dry through green-teal through blue to dark navy/very moist).
# Bottom of the scale is 0.5" (below that reads as dry/uninteresting for
# TPW purposes and is left off the bottom of the ramp), stepping up in the
# 0.5" increments typical of operational PWAT color tables. WM-6's field
# itself comes back in kg/m^2 (numerically == mm), so the control points
# are converted to mm once here for comparison against the fetched data.
# ---------------------------------------------------------------------------
TPW_COLOR_TABLE_IN = [
    (0.5, [255, 255, 221]),
    (1.0, [239, 248, 185]),
    (1.5, [206, 232, 184]),
    (2.0, [145, 203, 188]),
    (2.5, [101, 180, 195]),
    (3.0, [69, 143, 188]),
    (3.5, [50, 92, 164]),
    (4.0, [41, 52, 142]),
    (4.5, [13, 30, 86]),
]
TPW_COLOR_TABLE_MM = [(inch * 25.4, rgb) for inch, rgb in TPW_COLOR_TABLE_IN]
TPW_IN_MIN = TPW_COLOR_TABLE_IN[0][0]
TPW_IN_MAX = TPW_COLOR_TABLE_IN[-1][0]
TPW_MM_MIN = TPW_COLOR_TABLE_MM[0][0]
TPW_MM_MAX = TPW_COLOR_TABLE_MM[-1][0]


def build_tpw_colormap():
    span = TPW_MM_MAX - TPW_MM_MIN
    stops = [((mm - TPW_MM_MIN) / span, [c / 255 for c in rgb]) for mm, rgb in TPW_COLOR_TABLE_MM]
    return LinearSegmentedColormap.from_list("ingalls_tpw", stops, N=256)


def mm_to_in(mm):
    return mm / 25.4


def in_to_mm(inch):
    return inch * 25.4


# ---------------------------------------------------------------------------
# WindBorne WM-6 fetch
# ---------------------------------------------------------------------------
def wb_get(path, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{WB_BASE}/{path}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_zarr_array(remote_zip, names, tmp_dir, array_path):
    """Copy just one array's metadata + chunk file(s) out of the remote
    zip into a local directory tree, then open it with zarr -- lets zarr's
    codec pipeline (WM-6's TCWV field uses zstd/blosc + zarr v3 sharding)
    handle decoding, without pulling in the rest of the archive."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def fetch_tcwv_mean(valid_time_utc, api_key):
    """Fetch the WM-6 ensemble-mean total column water vapour grid valid
    nearest to valid_time_utc, cropped to the map bbox.

    WM-6's gridded endpoint archives each run shortly after it finishes,
    and once archived, `variable=`/`include_distribution=` filtering is no
    longer honored server-side -- a request naming a specific variable is
    rejected outright ("Variable filtering is not available for archived
    forecasts. Use variable=all..."), even with `as_url=true`. The
    complete per-forecast-hour file (every variable, level, and product:
    deterministic, ensemble mean/std, members, percentiles) is still
    servable via a presigned URL by passing `variable=all` explicitly
    (docs: "points to the full archived Zarr file -- variable and level
    filtering are not applied"). That file runs ~2 GB compressed. Rather
    than downloading the whole thing, this uses `remotezip` to make HTTP
    range requests against the presigned URL for just the handful of
    entries this map needs -- the latitude/longitude coordinate arrays and
    the TCWV ensemble-mean field -- a few MB total.

    Returns (lat_1d, lon_1d, tcwv_mm_2d, meta dict with
    initialization_time/valid_time/forecast_hour)."""
    url_info = wb_get("gridded", api_key, variable="all",
                       time=valid_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), as_url="true")
    print(f"Opening archived WM-6 run via presigned URL (range-request fetch, not a full download)...")

    with RemoteZip(url_info["url"]) as rz:
        names = rz.namelist()
        root_meta = json.loads(rz.read("zarr.json"))["attributes"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            lat = fetch_zarr_array(rz, names, tmp_dir, "latitude")
            lon = fetch_zarr_array(rz, names, tmp_dir, "longitude")
            tcwv = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{VARIABLE}")

    lat_idx = np.where((lat >= LAT_MIN - FETCH_PAD_DEG) & (lat <= LAT_MAX + FETCH_PAD_DEG))[0]
    lon_idx = np.where((lon >= LON_MIN - FETCH_PAD_DEG) & (lon <= LON_MAX + FETCH_PAD_DEG))[0]
    lat_crop = lat[lat_idx]
    lon_crop = lon[lon_idx]
    tcwv_crop = tcwv[np.ix_(lat_idx, lon_idx)]

    # WM-6's latitude axis runs north-to-south (90 down to -89.75); flip to
    # ascending so downstream imshow(..., origin="lower") behaves like
    # every other map builder in this repo.
    if lat_crop[0] > lat_crop[-1]:
        lat_crop = lat_crop[::-1]
        tcwv_crop = tcwv_crop[::-1, :]

    meta = {
        "initialization_time": root_meta["initialization_time"],
        "valid_time": root_meta["valid_time"],
        "forecast_hour": root_meta["forecast_hour"],
    }
    return lat_crop, lon_crop, tcwv_crop, meta


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def clip_to_map(geom):
    # segmentize first: a real, mostly-straight-in-lon/lat run (the
    # US/Canada border tracks the 49th parallel dead straight for ~2000
    # km) can be represented with very few vertices, which is fine under
    # PlateCarree but draws as a visibly wrong straight chord once
    # reprojected into NearsidePerspective's curved view -- adding
    # intermediate vertices every ~0.5 deg gives the reprojection enough
    # points to bend it into its true curved shape.
    clipped = shapely.segmentize(geom, max_segment_length=0.5).intersection(MAP_CLIP_BOX)
    return None if clipped.is_empty else clipped


def clip_outline_to_map(geom):
    """Like clip_to_map, but for a polygon that's only ever drawn as an
    outline (facecolor="none"): clips its boundary LineString rather than
    the polygon itself, so truncating a polygon that extends past
    MAP_CLIP_BOX doesn't add the clip box's own straight edge as a fake
    coastline/border segment across the box's cut line."""
    return clip_to_map(geom.boundary)


def load_countries():
    """Full country polygons (not just a coastline-only dataset) -- the
    only basemap layer in /maps that reaches Hawaii, since it's drawn per
    country rather than clipped to a Pacific Northwest bounding box.
    Doubles as the coastline: drawn outline-only so TPW shading over water
    stays visible."""
    with open(COUNTRIES_FILE) as f:
        data = json.load(f)
    geoms = [shape(feat["geometry"]) for feat in data["features"]
             if feat["properties"].get("NAME") in TARGET_COUNTRIES]
    return [g for g in (clip_outline_to_map(g) for g in geoms) if g is not None]


def load_states():
    """State/province polygons -- lake features dropped so they don't draw
    as if they were a state/province border."""
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            continue
        if props.get("admin") in TARGET_COUNTRIES:
            clipped = clip_outline_to_map(shape(feat["geometry"]))
            if clipped is not None:
                state_geoms.append(clipped)
    return state_geoms


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    geoms = [shape(feat["geometry"]) for feat in data["features"]]
    return [g for g in (clip_to_map(g) for g in geoms) if g is not None]


def build_map(date, hour, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    local_dt = datetime(date.year, date.month, date.day, hour, tzinfo=LOCAL_TZ)
    valid_time_utc = local_dt.astimezone(ZoneInfo("UTC"))

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path, allow_pickle=True)
        lat, lon, tcwv_mm = npz["lat"], npz["lon"], npz["tcwv_mm"]
        meta = npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, tcwv_mm, meta = fetch_tcwv_mean(valid_time_utc, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(OUTPUT_DIR / f"snapshot_{date.isoformat()}_{hour:02d}.npz",
                  lat=lat, lon=lon, tcwv_mm=tcwv_mm, meta=meta)

    print(f"TPW range in fetched crop: {tcwv_mm.min():.0f} - {tcwv_mm.max():.0f} mm")

    print("Loading basemap layers...")
    country_geoms = load_countries()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # NearsidePerspective (satellite view), not PlateCarree -- shows the
    # earth's actual curvature (converging meridians, bowed parallels)
    # rather than a flat lon/lat rectangle. At this domain's size (60 deg
    # lon x 49 deg lat, Hawaii to Saskatchewan), the projected shape is a
    # curved trapezoid that doesn't fill a rectangular frame -- unlike
    # ../dew-point-storm-map/build_map.py's much smaller domain, there's no
    # satellite_height that avoids that. Rather than fighting it, the axes
    # patch is left transparent so the unfilled corners show the figure's
    # own background instead of a jarring white/blank rectangle -- the
    # curved geo spine (below) reads as the map's actual border, the same
    # way published trapezoid-framed Lambert Conformal maps look.
    pc = ccrs.PlateCarree()
    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=35_786_000)

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("none")

    # TPW field -- a fixed mm-to-color enhancement curve (not rescaled to
    # this map's data range), so color reads consistently across every map
    # this script renders. WM-6 is already a plain regular lat/lon grid
    # (unlike wm6-3km/HRRR's curvilinear native grids), so no griddata
    # resampling step is needed before handing it to imshow -- cartopy
    # still has to warp that regular grid into the curved NearsidePerspective
    # view internally (a source-raster -> screen-pixel inverse lookup,
    # which is why cartopy's img_transform needs scipy -- see
    # requirements.txt).
    tpw_cmap = build_tpw_colormap()
    tpw_norm = Normalize(vmin=TPW_MM_MIN, vmax=TPW_MM_MAX)
    ax.imshow(tcwv_mm, transform=pc, cmap=tpw_cmap, norm=tpw_norm, origin="lower",
              extent=[lon.min(), lon.max(), lat.min(), lat.max()], zorder=1)

    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # City labels -- dot plus name, no value overlay (this is a continental-
    # scale overview map, not a point-forecast one).
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.75))]
    for name, lon_c, lat_c, pos in CITIES:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.6, color="white", zorder=100,
                mec="black", mew=0.7, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=9.25, fontproperties=poppins_semibold,
                       color="white", ha=ha, va="center", zorder=101, transform=name_transform)
        txt.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame.
    # Primary (bottom) axis is inches, ticked at each 0.5" color-table stop
    # (the unit the color table -- and PWAT/TPW products generally -- are
    # defined in); a secondary (top) axis mirrors it in mm.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.016
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.085

    gradient_mm = np.linspace(TPW_MM_MIN, TPW_MM_MAX, 256).reshape(1, -1)
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient_mm, aspect="auto", cmap=tpw_cmap, norm=tpw_norm,
               extent=[TPW_IN_MIN, TPW_IN_MAX, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    in_ticks = [inch for inch, _ in TPW_COLOR_TABLE_IN]
    cax.set_xticks(in_ticks)
    cax.set_xticklabels([f'{inch:g}"' for inch in in_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    cax.set_xlabel("Total Precipitable Water (in)", fontsize=8.5, fontproperties=poppins_reg, color="#5a584f")

    cax_mm = cax.secondary_xaxis("top", functions=(in_to_mm, mm_to_in))
    cax_mm.xaxis.set_major_formatter(lambda mm, _: f"{mm:.0f}")
    cax_mm.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax_mm.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    valid_dt_utc = datetime.fromisoformat(meta["valid_time"].replace("Z", "+00:00"))
    valid_dt_local = valid_dt_utc.astimezone(LOCAL_TZ)

    h12 = local_dt.hour % 12 or 12
    ampm = "AM" if local_dt.hour < 12 else "PM"
    fig.text(0.03, 0.978, f"{local_dt.strftime('%A')} {h12}:00 {ampm} PT Precipitable Water", fontsize=19,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, "WindBorne WM-6 Ensemble Mean", fontsize=12.5,
              fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    valid_note = ""
    if abs((valid_dt_local - local_dt).total_seconds()) > 60:
        valid_note = f" (nearest available step to {h12}:00 {ampm} PT: {valid_dt_local.strftime('%I:%M %p %Z').lstrip('0')})"
    fig.text(0.03, 0.914, f"Init {init_dt.strftime('%Y-%m-%d %H')}z{valid_note}",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "WindBorne WM-6 — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if arr[y, x][0] < 40 and arr[y, x][1] < 40 and arr[y, x][2] < 40]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if arr[yy, x][0] < 40 and arr[yy, x][1] < 40 and arr[yy, x][2] < 40]
        frame_left = min(black_cols) if black_cols else 20
        frame_bottom = max(black_rows) if black_rows else bh - 20

        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        scale = target_w / logo.width
        target_h = int(logo.height * scale)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

        pos = (frame_left + MAP_FRAME_INSET_PX, frame_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather WM-6 ensemble mean total precipitable water map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD, local (Pacific) time (default: tomorrow).")
    parser.add_argument("--hour", type=int, default=12,
                         help="Target local hour, 0-23 (default: 12, i.e. noon PT).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/tpw_wm6_ensemble_<date>_<hour>.png).")
    args = parser.parse_args()

    if not (0 <= args.hour <= 23):
        parser.error("--hour must be between 0 and 23.")

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = datetime.now(LOCAL_TZ).date() + timedelta(days=1)

    out_path = args.out or (OUTPUT_DIR / f"tpw_wm6_ensemble_{target_date.isoformat()}_{args.hour:02d}.png")
    build_map(target_date, args.hour, out_path, override_path=args.file)
