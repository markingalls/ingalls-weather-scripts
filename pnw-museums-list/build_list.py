"""
Pacific Northwest Museums -- bucket-list graphic
Ingalls Weather

Renders a Pacific Northwest museum bucket list as a to-do-style graphic
(two columns of open-circle "City - Museum" lines), modestly wide for
Instagram, in the same visual style as the repo's map products: Poppins
type, the #f7f6f2 page tone throughout, a black outline frame, a muted
credit line along the bottom, and the Ingalls Weather logo.

USAGE
-----
    python build_list.py                    # output/pnw_museums.png
    python build_list.py --out some.png

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Figure geometry -- modestly wide (2000x1680 px at 200 dpi, ~1.19:1), so
# two columns of full "City - Museum" lines fit without wrapping.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.0, 8.4
FIG_DPI = 200
PANEL_RECT = [0.03, 0.06, 0.94, 0.765]   # left, bottom, width, height (figure fraction)

PAGE_COLOR = "#f7f6f2"
CITY_COLOR = "#4a6b7a"
TEXT_COLOR = "#2b2a26"
SUBTITLE_COLOR = "#3a3835"
CREDIT_COLOR = "#8a887e"
BULLET_COLOR = "#4a6b7a"
MAX_FONT_SIZE = 12.5

# ---------------------------------------------------------------------------
# The list -- (city, museum), sorted by city then museum.
# ---------------------------------------------------------------------------
MUSEUMS = [
    ("Astoria", "Columbia River Maritime Museum"),
    ("Astoria", "Fort Clatsop National Memorial"),
    ("Baker City", "Oregon Trail Interpretive Center"),
    ("Bellingham", "SPARK Museum of Electrical Invention"),
    ("Bend", "High Desert Museum"),
    ("Burnaby", "Burnaby Village Museum"),
    ("Eugene", "Museum of Natural and Cultural History"),
    ("Fort Rock", "Fort Rock Homestead Village Museum"),
    ("John Day", "Kam Wah Chung & Co. Museum"),
    ("Keyport", "US Naval Undersea Museum"),
    ("Neah Bay", "Makah Museum"),
    ("Oregon City", "Museum of the Oregon Territory"),
    ("Pendleton", "Heritage Station Museum"),
    ("Pendleton", "Pendleton Underground"),
    ("Portland", "Oregon Historical Society Museum"),
    ("Portland", "Oregon Maritime Museum"),
    ("Portland", "Wells Fargo History Museum"),
    ("Portland", "World Forestry Museum"),
    ("Reardan", "Inland Northwest Rail Museum"),
    ("Republic", "Stonerose Interpretive Center"),
    ("Seattle", "Connections Museum"),
    ("Seattle", "Living Computers Museum + Labs"),
    ("Seattle", "Museum of History and Industry"),
    ("Seattle", "Seattle Underground"),
    ("Tacoma", "Washington State History Museum"),
    ("The Dalles", "Columbia Gorge Discovery Center and Museum"),
    ("The Dalles", "Fort Dalles Museum"),
    ("Vancouver (BC)", "UBC Museum of Anthropology"),
    ("Vancouver (WA)", "Fort Vancouver"),
    ("Yakima", "Yakima Electric Railway Museum"),
]


def build_list(output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor(PAGE_COLOR)
    renderer = fig.canvas.get_renderer()
    fig_w_px = FIG_WIDTH_IN * FIG_DPI

    # Outline-only frame, same 1.6 weight as the map products' frame --
    # no fill, so the page tone runs straight through it.
    px, py, pw, ph = PANEL_RECT
    fig.patches.append(mpatches.Rectangle((px, py), pw, ph, transform=fig.transFigure,
                                          facecolor="none", edgecolor="black",
                                          linewidth=1.6, zorder=0))

    # Two columns, filled top-to-bottom in list order (left column first).
    n_rows = (len(MUSEUMS) + 1) // 2
    columns = [MUSEUMS[:n_rows], MUSEUMS[n_rows:]]
    col_w = pw / 2
    pad_x = 0.03
    bullet_gap = 0.018          # bullet center -> text start
    text_room = col_w - pad_x - bullet_gap - 0.012

    def width_frac(txt, prop, size):
        t = fig.text(0, 0, txt, fontproperties=prop, fontsize=size)
        w = t.get_window_extent(renderer).width / fig_w_px
        t.remove()
        return w

    # Largest font size (<= MAX_FONT_SIZE) at which the longest line fits.
    size = MAX_FONT_SIZE
    while size > 7 and max(width_frac(c, poppins_med, size) + width_frac(f" - {m}", poppins_reg, size)
                           for c, m in MUSEUMS) > text_room:
        size -= 0.25

    row_h = (ph - 0.09) / n_rows
    top = py + ph - 0.045 - row_h / 2

    for ci, col in enumerate(columns):
        x0 = px + ci * col_w + pad_x
        for ri, (city, museum) in enumerate(col):
            y = top - ri * row_h
            fig.add_artist(Line2D([x0], [y - 0.0035], transform=fig.transFigure, marker="o", markersize=size * 0.8,
                                  markerfacecolor="none", markeredgecolor=BULLET_COLOR, markeredgewidth=1.3,
                                  linestyle="none"))
            tx = x0 + bullet_gap
            fig.text(tx, y, city, fontsize=size, fontproperties=poppins_med, color=CITY_COLOR,
                     ha="left", va="center_baseline")
            fig.text(tx + width_frac(city, poppins_med, size), y, f" - {museum}", fontsize=size,
                     fontproperties=poppins_reg, color=TEXT_COLOR, ha="left", va="center_baseline")

    # Title & subtitle above the frame
    n_cities = len({c for c, _ in MUSEUMS})
    fig.text(0.03, 0.965, "Pacific Northwest Museums", fontsize=24,
             fontproperties=poppins_reg, color=TEXT_COLOR, ha="left", va="top")
    fig.text(0.03, 0.895, f"{len(MUSEUMS)} museums • {n_cities} cities • Washington, Oregon & British Columbia",
             fontsize=12, fontproperties=poppins_med, color=SUBTITLE_COLOR, ha="left", va="top")

    fig.text(0.5, 0.018, "Ingalls Weather", fontsize=9.5, fontproperties=poppins_reg,
             color=CREDIT_COLOR, ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved list to {output_path} (list font {size}pt)")

    # ---- Composite logo, top-right, in the title band ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        panel_right = int((px + pw) * bw)
        panel_top = int((1 - (py + ph)) * bh)
        target = int(panel_top * 0.78)
        logo = Image.open(LOGO_FILE).convert("RGB").resize((target, target), Image.LANCZOS)
        pos = (panel_right - target, (panel_top - target) // 2)
        base.paste(logo, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Pacific Northwest museums list graphic.")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR / "pnw_museums.png",
                        help="Output PNG path (default: output/pnw_museums.png).")
    args = parser.parse_args()
    build_list(args.out)
