"""
Pacific Northwest Museums -- bucket-list graphic
Ingalls Weather

Renders a styled, Instagram-ready (4:5) list of Pacific Northwest museums,
grouped by city, in the same visual style as the repo's map products:
Poppins type, the #f7f6f2 page tone, a black-framed panel, a muted
credit line along the bottom, and the Ingalls Weather logo.

USAGE
-----
    python build_list.py                    # output/pnw_museums.png
    python build_list.py --out some.png

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
from itertools import groupby
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
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
# Figure geometry -- 4:5 portrait for Instagram (1680x2100 px at 200 dpi).
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.4, 10.5
FIG_DPI = 200
PANEL_RECT = [0.03, 0.045, 0.94, 0.835]   # left, bottom, width, height (figure fraction)

PAGE_COLOR = "#f7f6f2"
PANEL_COLOR = "#ffffff"
CITY_COLOR = "#4a6b7a"
TEXT_COLOR = "#2b2a26"
SUBTITLE_COLOR = "#3a3835"
CREDIT_COLOR = "#8a887e"
RULE_COLOR = "#d7dcd0"

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


def city_groups():
    return [(city, [m for _, m in items]) for city, items in groupby(MUSEUMS, key=lambda t: t[0])]


def split_columns(groups):
    """Split city groups (kept intact, in order) into two columns whose
    line counts (one heading line + one per museum, plus a gap) are as
    close to even as possible."""
    weights = [1 + len(ms) + 0.45 for _, ms in groups]
    total = sum(weights)
    best_i, best_diff, running = 0, float("inf"), 0
    for i, w in enumerate(weights):
        running += w
        diff = abs(total - 2 * running)
        if diff < best_diff:
            best_i, best_diff = i + 1, diff
    return groups[:best_i], groups[best_i:]


def build_list(output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor(PAGE_COLOR)

    # Black-framed white panel, same 1.6 frame weight as the map products.
    px, py, pw, ph = PANEL_RECT
    fig.patches.append(mpatches.Rectangle((px, py), pw, ph, transform=fig.transFigure,
                                          facecolor=PANEL_COLOR, edgecolor="black",
                                          linewidth=1.6, zorder=0))

    groups = city_groups()
    columns = split_columns(groups)

    line_h = 0.0228
    gap_h = 0.45 * line_h
    # Vertically center the taller column inside the panel.
    col_heights = [sum((1 + len(ms)) * line_h for _, ms in col) + (len(col) - 1) * gap_h
                   for col in columns]
    top = py + ph / 2 + max(col_heights) / 2 + 0.004
    col_x = [px + 0.04, px + pw / 2 + 0.022]
    indent = 0.018

    for x, col in zip(col_x, columns):
        y = top
        for city, museums in col:
            fig.text(x, y, city.upper(), fontsize=10, fontproperties=poppins_med,
                     color=CITY_COLOR, ha="left", va="top")
            y -= line_h
            for m in museums:
                fig.text(x + indent, y, m, fontsize=10.5, fontproperties=poppins_reg,
                         color=TEXT_COLOR, ha="left", va="top")
                y -= line_h
            y -= gap_h

    # Thin center rule between the two columns.
    fig.add_artist(plt.Line2D([px + pw / 2, px + pw / 2], [py + 0.03, py + ph - 0.03],
                              transform=fig.transFigure, color=RULE_COLOR, linewidth=1.0))

    # Title & subtitle above the panel
    n_cities = len(groups)
    fig.text(0.03, 0.977, "Pacific Northwest Museums", fontsize=22,
             fontproperties=poppins_reg, color=TEXT_COLOR, ha="left", va="top")
    fig.text(0.03, 0.935, f"{len(MUSEUMS)} museums • {n_cities} cities • Washington, Oregon & British Columbia",
             fontsize=11.5, fontproperties=poppins_med, color=SUBTITLE_COLOR, ha="left", va="top")
    fig.text(0.03, 0.909, "A bucket list", fontsize=10.5, fontproperties=poppins_reg,
             color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.014, "Ingalls Weather", fontsize=9, fontproperties=poppins_reg,
             color=CREDIT_COLOR, ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved list to {output_path}")

    # ---- Composite logo, top-right, in the title band ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        panel_right = int((px + pw) * bw)
        panel_top = int((1 - (py + ph)) * bh)
        target = int(bw * 0.095)
        logo = Image.open(LOGO_FILE).convert("RGB").resize((target, target), Image.LANCZOS)
        margin = int((panel_top - target) / 2)
        pos = (panel_right - target, margin)
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
