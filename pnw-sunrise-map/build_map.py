"""
Pacific Northwest Sunrise Time Map -- one-off builder
Ingalls Weather

Styled map of local clock sunrise time across WA, OR, ID, western MT,
southern BC (north to about 100 Mile House) and southwestern Alberta for a
single date -- by default Sunday, November 1, 2026, the first fall-back
where British Columbia and Alberta *don't* turn their clocks back:

  - BC (most of it) stays on UTC-7 year-round ("Pacific Time"), so its
    sunrise jumps an hour later than Washington's -- Vancouver ~08:00 vs.
    Seattle ~07:00.
  - Alberta, and BC's East Kootenay (Cranbrook, Fernie, Invermere) and
    Golden, stay on UTC-6 year-round -- sunrise near 08:30.
  - Creston stays on UTC-7 as always.
  - US states fall back at 2 AM Nov 1 as usual (PST / MST).

Shading is the clock time of sunrise (upper limb on the horizon, standard
-0.833 deg refraction allowance, sea-level horizon -- terrain isn't
considered), computed per grid point with the NOAA solar position
equations, then converted to local clock time using the time zone polygon
the point falls in. Thin contours every 15 minutes are drawn separately
within each offset region, so they stop cleanly at time zone lines instead
of piling up where the clock jumps.

USAGE
-----
    python build_map.py                    # Nov 1, 2026
    python build_map.py --date 2026-12-21

REQUIRES (checked into /maps at repo root):
    tz_boundaries_north_america.json (see
    ../north-america-time-zones/prepare_basemap.py), land_slim.json,
    states_lakes_slim.json, admin0_boundary_lines.json

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.transforms import offset_copy
import numpy as np
import shapely
from PIL import Image
from shapely.geometry import box, shape
from shapely.ops import unary_union

import cartopy.crs as ccrs

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

TZ_FILE = MAPS_DIR / "tz_boundaries_north_america.json"
LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

DEFAULT_DATE = date_cls(2026, 11, 1)

# ---------------------------------------------------------------------------
# Canada's 2026 changes, pinned so the map is right even with a tz database
# older than 2026e (same table as ../north-america-time-zones/build_map.py,
# trimmed to the zones in this domain). Offset in hours, valid from Nov 1,
# 2026 on. America/Edmonton's polygon includes East Kootenay and Golden.
# Everything else (US zones) comes from the system tz database at the
# local-morning instant of the target date.
# ---------------------------------------------------------------------------
CANADA_2026 = {
    "America/Vancouver": -7.0,
    "America/Edmonton": -6.0,
    "America/Creston": -7.0,
    "America/Dawson_Creek": -7.0,
    "America/Fort_Nelson": -7.0,
    "America/Regina": -6.0,
    "America/Swift_Current": -6.0,
}

# ---------------------------------------------------------------------------
# Domain / figure (Lambert Conformal, framed as a projected rectangle
# around FRAME_POINTS -- see ../north-america-time-zones/build_map.py).
# North edge sits just above 100 Mile House; south edge just below the
# OR/CA line; west takes in Vancouver Island, east takes in Calgary and
# all of Idaho.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -129.0, -109.8
LAT_MIN, LAT_MAX = 41.5, 53.0
PROJ = ccrs.LambertConformal(central_longitude=-119.4, central_latitude=47.0,
                             standard_parallels=(43.0, 51.0))
FRAME_POINTS = [(-127.9, 52.75), (-110.6, 52.75), (-126.0, 41.7), (-111.6, 41.7),
                (-119.4, 53.0), (-119.4, 41.6)]
FIG_DPI = 200
FIG_WIDTH_IN = 9.0
AXES_LEFT, AXES_BOTTOM, AXES_WIDTH = 0.03, 0.135, 0.94
TOP_MARGIN_FRAC = 0.125
MAP_FRAME_INSET_PX = 22

GRID_STEP_DEG = 0.01
GRID_PAD_DEG = 1.5

CONTOUR_INTERVAL_MIN = 15
CITY_LABEL_FONTSIZE = 10.5
TZ_LINE_SNAP_DEG = 0.1

CITIES = [
    # (name, lon, lat, label side: right/left/above/below)
    ("100 Mile House", -121.2930, 51.6418, "right"),
    ("Bella Coola", -126.7659, 52.3728, "right"),
    ("Tofino", -125.9066, 49.1530, "left"),
    ("Kamloops", -120.3273, 50.6745, "right"),
    ("Whistler", -122.9574, 50.1163, "right"),
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Victoria", -123.3656, 48.4284, "left"),
    ("Kelowna", -119.4960, 49.8880, "right"),
    ("Golden", -116.9631, 51.2985, "right"),
    ("Cranbrook", -115.7697, 49.5097, "right"),
    ("Creston", -116.5135, 49.0955, "below"),
    ("Calgary", -114.0719, 51.0447, "right"),
    ("Lethbridge", -112.8418, 49.6935, "right"),
    ("Seattle", -122.3321, 47.6062, "left"),
    ("Wenatchee", -120.3103, 47.4235, "right"),
    ("Spokane", -117.4260, 47.6588, "right"),
    ("Yakima", -120.5059, 46.6021, "left"),
    ("Tri-Cities", -119.2781, 46.2565, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Bend", -121.3153, 44.0582, "right"),
    ("Eugene", -123.0868, 44.0521, "left"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Boise", -116.2023, 43.6150, "right"),
    ("Missoula", -113.9940, 46.8721, "right"),
    ("Idaho Falls", -112.0362, 43.4917, "left"),
]

# Sunrise color table -- early = warm sunrise gold, late = deep pre-dawn
# indigo, as fixed clock-time control points (decimal hours) so a shade
# always means the same time across runs.
SUNRISE_COLOR_TABLE = [
    (6.25, [250, 214, 120]),
    (6.75, [245, 170, 95]),
    (7.25, [228, 120, 98]),
    (7.75, [180, 88, 120]),
    (8.25, [110, 72, 132]),
    (8.75, [44, 50, 104]),
]
SR_MIN = SUNRISE_COLOR_TABLE[0][0]
SR_MAX = SUNRISE_COLOR_TABLE[-1][0]


def build_sunrise_colormap():
    span = SR_MAX - SR_MIN
    stops = [((h - SR_MIN) / span, [c / 255 for c in rgb]) for h, rgb in SUNRISE_COLOR_TABLE]
    return LinearSegmentedColormap.from_list("ingalls_sunrise", stops, N=256)


# ---------------------------------------------------------------------------
# Sunrise (NOAA solar calculator equations, vectorized)
# ---------------------------------------------------------------------------
def sunrise_utc_hours(target_date, lon, lat):
    """UTC sunrise time (decimal hours, may be <0 or >24) for each lon/lat.
    Evaluated with the solar declination / equation of time at ~local
    morning, which is accurate to well under a minute at these latitudes."""
    jd = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc).timestamp() / 86400 + 2440587.5
    jd = jd + 15 / 24  # ~sunrise in the PNW, in UTC
    t = (jd - 2451545.0) / 36525
    l0 = np.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    m = np.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (np.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t)) + np.sin(2 * m) * (0.019993 - 0.000101 * t)
         + np.sin(3 * m) * 0.000289)
    true_long = np.degrees(l0) + c
    omega = np.radians(125.04 - 1934.136 * t)
    app_long = np.radians(true_long - 0.00569 - 0.00478 * np.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = np.radians(eps0 + 0.00256 * np.cos(omega))
    decl = np.arcsin(np.sin(eps) * np.sin(app_long))
    y = np.tan(eps / 2) ** 2
    eq_time_min = 4 * np.degrees(y * np.sin(2 * l0) - 2 * e * np.sin(m) + 4 * e * y * np.sin(m) * np.cos(2 * l0)
                                 - 0.5 * y * y * np.sin(4 * l0) - 1.25 * e * e * np.sin(2 * m))
    lat_r = np.radians(lat)
    cos_ha = (np.cos(np.radians(90.833)) / (np.cos(lat_r) * np.cos(decl)) - np.tan(lat_r) * np.tan(decl))
    ha = np.degrees(np.arccos(np.clip(cos_ha, -1, 1)))
    sunrise_min = 720 - 4 * (lon + ha) - eq_time_min
    return sunrise_min / 60


def fmt_clock(h):
    """24-hour clock time, e.g. 07:59."""
    total = int(round(h * 60))
    hh, mm = divmod(total, 60)
    return f"{hh % 24:02d}:{mm:02d}"


# ---------------------------------------------------------------------------
# Time zones
# ---------------------------------------------------------------------------
def load_tz_regions(target_date):
    """{offset_hours: shapely geometry} for zones touching the domain,
    using clock offsets in effect on the morning of target_date."""
    morning = datetime(target_date.year, target_date.month, target_date.day, 16, tzinfo=timezone.utc)
    dom = box(LON_MIN - GRID_PAD_DEG, LAT_MIN - GRID_PAD_DEG, LON_MAX + GRID_PAD_DEG, LAT_MAX + GRID_PAD_DEG)
    with open(TZ_FILE) as f:
        data = json.load(f)
    groups = {}
    for feat in data["features"]:
        geom = shape(feat["geometry"])
        if not geom.intersects(dom):
            continue
        tzid = feat["properties"]["tzid"]
        off = morning.astimezone(ZoneInfo(tzid)).utcoffset().total_seconds() / 3600
        if tzid in CANADA_2026 and target_date >= DEFAULT_DATE:
            if off != CANADA_2026[tzid]:
                print(f"NOTE: local tz database gives {tzid} {off:+.1f} on {target_date}; "
                      f"using the pinned 2026 value {CANADA_2026[tzid]:+.1f}.")
            off = CANADA_2026[tzid]
        groups.setdefault(off, []).append(geom.intersection(dom))
    # The small buffer-out/buffer-in closes hairline gaps between adjacent
    # same-offset zones (e.g. America/Boise vs America/Denver along the
    # ID/MT line), which would otherwise draw as stray time zone dashes.
    return {off: unary_union(g).buffer(0.01).buffer(-0.01) for off, g in groups.items()}


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states():
    """State/province polygons, lakes dropped (see dew-point-storm-map)."""
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    out = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            continue
        if props.get("admin") in TARGET_COUNTRIES:
            out.append(shape(feat["geometry"]))
    return out


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def densify(geoms, max_seg_deg=0.05):
    """Long straight lon/lat segments (the 49th parallel is a handful of
    vertices in some of these datasets) need extra vertices to follow
    LambertConformal's curved parallels -- otherwise two datasets' versions
    of the same border project as visibly separate lines."""
    return [shapely.segmentize(g, max_seg_deg) for g in geoms]


def frame_extent():
    xs, ys = zip(*[PROJ.transform_point(lon, lat, ccrs.PlateCarree()) for lon, lat in FRAME_POINTS])
    return min(xs), max(xs), min(ys), max(ys)


def build_map(target_date, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)
    pc = ccrs.PlateCarree()

    print("Loading time zones and basemap...")
    tz_regions = load_tz_regions(target_date)
    land_geoms = load_land()
    land = unary_union(land_geoms)
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    print("Computing sunrise grid...")
    lons = np.arange(LON_MIN - GRID_PAD_DEG, LON_MAX + GRID_PAD_DEG, GRID_STEP_DEG)
    lats = np.arange(LAT_MIN - GRID_PAD_DEG, LAT_MAX + GRID_PAD_DEG, GRID_STEP_DEG)
    lon2d, lat2d = np.meshgrid(lons, lats)
    sr_utc = sunrise_utc_hours(target_date, lon2d, lat2d)

    offset_grid = np.full(lon2d.shape, np.nan)
    for off, geom in tz_regions.items():
        shapely.prepare(geom)
        offset_grid[shapely.contains_xy(geom, lon2d, lat2d)] = off
    shapely.prepare(land)
    on_land = shapely.contains_xy(land, lon2d, lat2d)
    sr_local = sr_utc + offset_grid
    sr_local = np.ma.masked_where(~on_land | np.isnan(offset_grid), sr_local)

    x0, x1, y0, y1 = frame_extent()
    axes_h_in = FIG_WIDTH_IN * AXES_WIDTH * (y1 - y0) / (x1 - x0)
    fig_h_in = axes_h_in / (1 - AXES_BOTTOM - TOP_MARGIN_FRAC)
    axes_rect = [AXES_LEFT, AXES_BOTTOM, AXES_WIDTH, axes_h_in / fig_h_in]

    fig = plt.figure(figsize=(FIG_WIDTH_IN, fig_h_in), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes(axes_rect, projection=PROJ)
    ax.set_extent([x0, x1, y0, y1], crs=PROJ)
    ax.patch.set_facecolor("#e6edf0")

    cmap = build_sunrise_colormap()
    norm = Normalize(vmin=SR_MIN, vmax=SR_MAX)
    ax.pcolormesh(lons, lats, sr_local, transform=pc, cmap=cmap, norm=norm, shading="nearest",
                  rasterized=True, zorder=1)

    # 15-minute isochrones, per offset region so they end at the tz line.
    levels = np.arange(SR_MIN, SR_MAX + 1e-6, CONTOUR_INTERVAL_MIN / 60)
    for off in tz_regions:
        field = np.ma.masked_where(offset_grid != off, sr_utc + off)
        if field.count() < 50:
            continue
        cs = ax.contour(lons, lats, field, levels=levels, colors=[(1, 1, 1, 0.6)], linewidths=0.6,
                        transform=pc, zorder=1.2)
        labels = ax.clabel(cs, levels=levels[::2], fmt=lambda h: fmt_clock(h), fontsize=7,
                           inline=True, inline_spacing=2)
        for lbl in labels:
            lbl.set_fontproperties(poppins_reg)
            lbl.set_fontsize(7)
            lbl.set_color((1, 1, 1, 0.9))

    # Time zone lines -- edges of each offset region, clipped to land,
    # white halo under a dark dashed line so they read on light and dark
    # shading alike. They come from the same polygons as the shading, so
    # they sit exactly on the color jump; national/state border segments
    # running within TZ_LINE_SNAP_DEG of one are dropped, since Natural
    # Earth's version of the same border (49th parallel, Snake River) runs
    # slightly off the tz data's and would draw as a second line beside it.
    tz_edges = densify([g.intersection(land).boundary.difference(land.boundary.buffer(0.02))
                        for g in tz_regions.values()])
    tz_snap = unary_union(tz_edges).buffer(TZ_LINE_SNAP_DEG)
    state_lines = densify([g.boundary.difference(tz_snap) for g in state_geoms])
    admin0_lines = densify([g.difference(tz_snap) for g in admin0_lines])
    land_geoms = densify(land_geoms)
    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.7, zorder=1.5)
    ax.add_geometries(state_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.7, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.0, zorder=2.5)
    tz_dashes = (0, (4, 2.5))
    ax.add_geometries(tz_edges, crs=pc, facecolor="none", edgecolor="white", linewidth=2.6,
                      linestyle=tz_dashes, zorder=3)
    ax.add_geometries(tz_edges, crs=pc, facecolor="none", edgecolor="#1d1b18", linewidth=1.2,
                      linestyle=tz_dashes, zorder=3.1)

    # Cities with sunrise clock time
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.9, foreground=(0, 0, 0, 0.8))]
    for name, lon_c, lat_c, side in CITIES:
        j = int(round((lon_c - lons[0]) / GRID_STEP_DEG))
        i = int(round((lat_c - lats[0]) / GRID_STEP_DEG))
        off = offset_grid[i, j]
        if np.isnan(off):
            print(f"NOTE: no tz for {name}, skipping.")
            continue
        sr = float(sunrise_utc_hours(target_date, lon_c, lat_c)) + off
        ax.plot(lon_c, lat_c, marker="o", markersize=4.4, color="white", zorder=100,
                mec="black", mew=0.7, transform=pc)
        dx_pt, dy_pt, ha, va = {"right": (5, 0, "left", "center"), "left": (-5, 0, "right", "center"),
                                "above": (0, 5, "center", "bottom"),
                                "below": (0, -5, "center", "top")}[side]
        t = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=dy_pt, units="points")
        # Two lines: city name, sunrise time underneath.
        txt = ax.text(lon_c, lat_c, f"{name}\n{fmt_clock(sr)}", color="white", ha=ha, va=va,
                      multialignment=ha, linespacing=1.05, zorder=101, transform=t)
        txt.set_fontproperties(poppins_semibold)
        txt.set_fontsize(CITY_LABEL_FONTSIZE)
        txt.set_path_effects(stroke)
        print(f"  {name:15s} {fmt_clock(sr)} (UTC{off:+.0f})")

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # Colorbar
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    fw = FIG_WIDTH_IN * FIG_DPI
    frame_left, frame_right = frame_px.x0 / fw, frame_px.x1 / fw
    cbar_width, cbar_height = (frame_right - frame_left) * 0.6, 0.016
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cax = fig.add_axes([cbar_left, 0.062, cbar_width, cbar_height])
    gradient = np.linspace(SR_MIN, SR_MAX, 256).reshape(1, -1)
    cax.imshow(gradient, aspect="auto", cmap=cmap, norm=norm, extent=[SR_MIN, SR_MAX, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    ticks = np.arange(6.5, SR_MAX + 1e-6, 0.5)
    cax.set_xticks(ticks)
    cax.set_xticklabels([fmt_clock(h) for h in ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    fig.text(0.5, 0.062 + cbar_height + 0.012, "Sunrise, local clock time", fontsize=9,
             fontproperties=poppins_reg, color="#2b2a26", ha="center", va="bottom")

    # Time zone line legend, right of the colorbar label
    leg_y = 0.062 + cbar_height + 0.019
    fig.lines.extend([
        plt.Line2D([0.73, 0.77], [leg_y, leg_y], transform=fig.transFigure, color="white", linewidth=2.6,
                   linestyle=tz_dashes),
        plt.Line2D([0.73, 0.77], [leg_y, leg_y], transform=fig.transFigure, color="#1d1b18", linewidth=1.2,
                   linestyle=tz_dashes),
    ])
    fig.text(0.778, leg_y, "Time zone line", fontsize=8.6, fontproperties=poppins_reg, color="#2b2a26",
             ha="left", va="center")

    # Title block
    s = 11.0 / fig_h_in
    top = 1 - 0.022 * s
    fig.text(0.03, top, f"Sunrise Times • {target_date.strftime('%A, %B')} {target_date.day}, {target_date.year}",
             fontsize=19, fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, top - 0.040 * s, "B.C. & Alberta don't fall back — sunrise comes an hour later",
             fontsize=12.5, fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, top - 0.068 * s,
             "U.S. on PST/MST  •  B.C. on year-round UTC−7  •  Alberta, East Kootenay & Golden on year-round UTC−6",
             fontsize=9.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")
    fig.text(0.5, 0.008, "NOAA solar equations • IANA tz 2026e / timezone-boundary-builder — Ingalls Weather",
             fontsize=8.5, fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        frame_left_px = int(axes_rect[0] * bw)
        frame_bottom_px = int((1 - axes_rect[1]) * bh)
        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        target_h = int(logo.height * target_w / logo.width)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)
        pos = (frame_left_px + MAP_FRAME_INSET_PX, frame_bottom_px - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an Ingalls Weather Pacific Northwest sunrise time map.")
    parser.add_argument("--date", type=str, default=None,
                        help=f"Target date, YYYY-MM-DD (default: {DEFAULT_DATE.isoformat()}).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/pnw_sunrise_<date>.png).")
    args = parser.parse_args()
    d = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else DEFAULT_DATE
    build_map(d, args.out or (OUTPUT_DIR / f"pnw_sunrise_{d.isoformat()}.png"))
