"""Static explainer graphic: the difference between NWS High Surf and
Coastal Flood alerts. No data fetch -- all content is defined below.

Styling (canvas size, palette, fonts, card look, logo/title placement)
mirrors tri-cities-7day-forecast/build_graphic.py; alert chip colors are
the official NWS hazard colors, same as columbia-basin-alerts-map/build_map.py.
"""
import argparse
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle

# ---------- fonts ----------
# Same Poppins-with-Montserrat-fallback loader as tri-cities-7day-forecast/.
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
FALLBACK_FONT_DIR = "/usr/share/fonts/truetype/montserrat/"


def _load_font(poppins_name, fallback_name):
    poppins_path = FONT_DIR + poppins_name
    if os.path.exists(poppins_path):
        return fm.FontProperties(fname=poppins_path)
    return fm.FontProperties(fname=FALLBACK_FONT_DIR + fallback_name)


f_bold = _load_font("Poppins-Bold.ttf", "Montserrat-Bold.ttf")
f_reg = _load_font("Poppins-Regular.ttf", "Montserrat-Regular.ttf")
f_med = _load_font("Poppins-Medium.ttf", "Montserrat-Medium.ttf")

# ---------- palette (shared with the other Ingalls Weather graphics) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
CARD_FILL = "#ffffff"
CARD_EDGE = "#d8d5cc"
RULE = "#e6e3da"
HIGHLIGHT_EDGE = "#164f29"  # forest green, in the spirit of the logo's pine tree

COLOR_SURF = "#2f6fb0"     # same blue as the 7-day forecast's rain
COLOR_FLOOD = "#3f8f8f"    # same teal as the 7-day forecast's wind
COLOR_SAND = "#e3e1da"     # alerts-map land tone
COLOR_HOUSE = "#8a887c"

# ---------- official NWS hazard colors (see columbia-basin-alerts-map/) ----------
NWS_COLORS = {
    "High Surf Advisory": "#BA55D3",
    "High Surf Warning": "#228B22",
    "Coastal Flood Advisory": "#7CFC00",
    "Coastal Flood Watch": "#66CDAA",
    "Coastal Flood Warning": "#228B22",
}

# ---------- content ----------
# Each column: header, tagline, accent color, icon fn name, rows of
# (label, body), and the alert products that exist for that hazard.
COLUMNS = [
    {
        "title": "HIGH SURF",
        "tagline": "It's about the waves",
        "accent": COLOR_SURF,
        "icon": "surf",
        "rows": [
            ("CAUSE", "Large, powerful breaking waves, usually swell "
                      "from distant storms."),
            ("THREAT", "People swept off beaches, rocks, and jetties. "
                       "Sneaker waves, rolling logs, erosion."),
            ("WHO", "Beachgoers, anglers, and storm-watchers at the "
                    "water's edge."),
            ("ACTION", "Stay back from the surf and off jetties. "
                       "Never turn your back on the ocean."),
        ],
        "alerts": ["High Surf Advisory", "High Surf Warning"],
        "alerts_note": "No watch product\nexists for high surf.",
    },
    {
        "title": "COASTAL FLOOD",
        "tagline": "It's about the water level",
        "accent": COLOR_FLOOD,
        "icon": "flood",
        "rows": [
            ("CAUSE", "High tides plus storm surge push the sea "
                      "above its normal level."),
            ("THREAT", "Seawater floods normally dry land: roads, "
                       "parking lots, homes, businesses."),
            ("WHO", "Low-lying shoreline areas, mostly around "
                    "high tide."),
            ("ACTION", "Don't drive through flooded roads. Move cars "
                       "to higher ground before high tide."),
        ],
        "alerts": ["Coastal Flood Advisory", "Coastal Flood Watch", "Coastal Flood Warning"],
        "alerts_note": None,
    },
]

FOOTER_TEXT = ("They can happen together: a king tide plus a big winter swell can bring "
               "dangerous surf and coastal flooding at the same time. Exact criteria vary "
               "by NWS office.")


def text_color_for(hexcolor):
    """Dark ink on light chips, white on dark ones (relative luminance)."""
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return INK if lum > 0.5 else "white"


# ---------- icons (drawn in data coords on the full-figure axes) ----------
def draw_surf_icon(ax, cx, cy, size, color):
    """Three stacked wave lines, growing taller toward the top."""
    aspect = ax.figure.get_size_inches()[0] / ax.figure.get_size_inches()[1]
    sx, sy = size, size * aspect  # keep the icon visually square

    xs = np.linspace(cx - sx, cx + sx, 120)
    phase = (xs - (cx - sx)) / (2 * sx) * 2 * np.pi * 2  # two full waves across
    for i, (offset, amp) in enumerate(((-0.62, 0.10), (-0.12, 0.15), (0.42, 0.21))):
        ys = cy + offset * sy + np.sin(phase) * amp * sy
        ax.plot(xs, ys, color=color, linewidth=5.0, solid_capstyle="round",
                alpha=0.55 + 0.225 * i, zorder=4)


def draw_flood_icon(ax, cx, cy, size, color):
    """A house with seawater rising up its walls."""
    aspect = ax.figure.get_size_inches()[0] / ax.figure.get_size_inches()[1]
    sx, sy = size, size * aspect

    wall_w, wall_h = sx * 1.1, sy * 0.85
    wall_x0, wall_y0 = cx - wall_w / 2, cy - sy * 0.75
    ax.add_patch(Rectangle((wall_x0, wall_y0), wall_w, wall_h,
                            facecolor=COLOR_HOUSE, edgecolor="none", zorder=3))
    ax.add_patch(Polygon([(wall_x0 - sx * 0.15, wall_y0 + wall_h),
                           (cx, wall_y0 + wall_h + sy * 0.62),
                           (wall_x0 + wall_w + sx * 0.15, wall_y0 + wall_h)],
                          closed=True, facecolor=COLOR_HOUSE, edgecolor="none", zorder=3))
    ax.add_patch(Rectangle((cx - sx * 0.14, wall_y0), sx * 0.28, wall_h * 0.55,
                            facecolor="white", edgecolor="none", zorder=3.1))

    # Water: wavy-topped band across the bottom half of the house.
    water_top = wall_y0 + wall_h * 0.42
    xs = np.linspace(cx - sx, cx + sx, 80)
    ys = water_top + np.sin((xs - cx) / sx * 3 * np.pi) * sy * 0.05
    poly = np.column_stack([np.concatenate([xs, [cx + sx, cx - sx]]),
                            np.concatenate([ys, [cy - sy * 0.95, cy - sy * 0.95]])])
    ax.add_patch(Polygon(poly, closed=True, facecolor=color, edgecolor="none",
                          alpha=0.92, zorder=4))
    # "Normal level" dashed line well below the water surface
    ax.plot([cx - sx, cx + sx], [cy - sy * 0.82] * 2, color="white",
            linewidth=1.4, linestyle=(0, (3, 2)), zorder=5)


ICONS = {"surf": draw_surf_icon, "flood": draw_flood_icon}


def text_width_fig(fig, renderer, s, fontprops, fontsize):
    t = fig.text(0, 0, s, fontproperties=fontprops, fontsize=fontsize)
    w = t.get_window_extent(renderer=renderer).width / fig.bbox.width
    t.remove()
    return w


def parse_args():
    ap = argparse.ArgumentParser(description="Render the High Surf vs. Coastal Flood explainer graphic.")
    ap.add_argument("--output", default="high_surf_vs_coastal_flood.png")
    return ap.parse_args()


def main():
    args = parse_args()

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    LEFT, RIGHT = 0.055, 0.965
    CARD_TOP, CARD_BOTTOM = 0.835, 0.185
    GUTTER = 0.024
    card_w = (RIGHT - LEFT - GUTTER) / 2

    HEADER_Y = CARD_TOP - 0.05
    TAGLINE_Y = CARD_TOP - 0.098
    ICON_CX_OFFSET = 0.062  # from the card's right edge
    ROWS_TOP = CARD_TOP - 0.17
    ROW_GAP = 0.026
    LABEL_COL_W = 0.085
    BODY_WRAP = 44
    ALERTS_Y = CARD_BOTTOM + 0.065

    for idx, col in enumerate(COLUMNS):
        x0 = LEFT + idx * (card_w + GUTTER)
        pad = 0.024
        ax.add_patch(FancyBboxPatch(
            (x0, CARD_BOTTOM), card_w, CARD_TOP - CARD_BOTTOM,
            boxstyle="round,pad=0,rounding_size=0.012",
            facecolor=CARD_FILL, edgecolor=CARD_EDGE, linewidth=1.0, zorder=2))
        # Accent bar along the card's top edge
        ax.add_patch(FancyBboxPatch(
            (x0 + 0.012, CARD_TOP - 0.008), card_w - 0.024, 0.008,
            boxstyle="round,pad=0,rounding_size=0.004",
            facecolor=col["accent"], edgecolor="none", zorder=2.5))

        ax.text(x0 + pad, HEADER_Y, col["title"], ha="left", va="center",
                fontproperties=f_bold, fontsize=24, color=col["accent"], zorder=3)
        ax.text(x0 + pad, TAGLINE_Y, col["tagline"], ha="left", va="center",
                fontproperties=f_med, fontsize=14, color=INK, zorder=3)

        ICONS[col["icon"]](ax, x0 + card_w - ICON_CX_OFFSET, CARD_TOP - 0.078,
                           0.036, col["accent"])

        ax.plot([x0 + pad, x0 + card_w - pad], [CARD_TOP - 0.135] * 2,
                color=RULE, linewidth=1.0, zorder=3)

        y = ROWS_TOP
        for label, body in col["rows"]:
            lines = textwrap.wrap(body, BODY_WRAP)
            ax.text(x0 + pad, y, label, ha="left", va="top",
                    fontproperties=f_bold, fontsize=10.5, color=col["accent"], zorder=3)
            body_t = ax.text(x0 + pad + LABEL_COL_W, y + 0.003, "\n".join(lines), ha="left", va="top",
                             fontproperties=f_reg, fontsize=12, color=INK, linespacing=1.05, zorder=3)
            body_h = body_t.get_window_extent(renderer=renderer).height / fig.bbox.height
            y -= body_h + ROW_GAP

        # Alert chips in official NWS colors
        ax.plot([x0 + pad, x0 + card_w - pad], [ALERTS_Y + 0.062] * 2,
                color=RULE, linewidth=1.0, zorder=3)
        ax.text(x0 + pad, ALERTS_Y + 0.038, "NWS ALERTS", ha="left", va="center",
                fontproperties=f_bold, fontsize=10.5, color=col["accent"], zorder=3)

        chip_x = x0 + pad
        chip_h = 0.042
        chip_pad_x = 0.011
        chip_gap = 0.008
        for alert in col["alerts"]:
            # Chips show just the tier word; the hazard is the card's header.
            tier = alert.split()[-1]
            label = tier.upper()
            w = text_width_fig(fig, renderer, label, f_bold, 11) + 2 * chip_pad_x
            fill = NWS_COLORS[alert]
            ax.add_patch(FancyBboxPatch(
                (chip_x, ALERTS_Y - chip_h / 2 - 0.004), w, chip_h,
                boxstyle="round,pad=0,rounding_size=0.01",
                facecolor=fill, edgecolor="none", zorder=3))
            ax.text(chip_x + w / 2, ALERTS_Y - 0.004, label, ha="center", va="center",
                    fontproperties=f_bold, fontsize=11, color=text_color_for(fill), zorder=4)
            chip_x += w + chip_gap
        if col["alerts_note"]:
            ax.text(chip_x + 0.006, ALERTS_Y - 0.004, col["alerts_note"], ha="left",
                    va="center", fontproperties=f_reg, fontsize=10, color=INK_SECONDARY,
                    style="italic", zorder=3)

    # ---------- footer callout ----------
    FOOT_TOP, FOOT_BOTTOM = CARD_BOTTOM - 0.022, 0.085
    ax.add_patch(FancyBboxPatch(
        (LEFT, FOOT_BOTTOM), RIGHT - LEFT, FOOT_TOP - FOOT_BOTTOM,
        boxstyle="round,pad=0,rounding_size=0.012",
        facecolor=CARD_FILL, edgecolor=HIGHLIGHT_EDGE, linewidth=1.6, zorder=2))
    ax.text(LEFT + 0.024, (FOOT_TOP + FOOT_BOTTOM) / 2, "\n".join(textwrap.wrap(FOOTER_TEXT, 112)),
            ha="left", va="center", fontproperties=f_reg, fontsize=11.5, color=INK,
            linespacing=1.1, zorder=3)

    # ---------- logo (top-left, sized to the title block) + title / subtitle ----------
    TITLE_BLOCK_TOP, TITLE_BLOCK_BOTTOM = 0.965, 0.878
    title_x = LEFT

    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()

        logo_height_fig = TITLE_BLOCK_TOP - TITLE_BLOCK_BOTTOM
        logo_height_in = logo_height_fig * fig_h_in
        logo_width_in = logo_height_in * (img_w / img_h)
        logo_width_fig = logo_width_in / fig_w_in

        logo_y0 = TITLE_BLOCK_BOTTOM + 0.012
        logo_ax = fig.add_axes([LEFT, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")

        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    fig.text(title_x, 0.935, "High Surf vs. Coastal Flood Alerts",
             fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, "Two different coastal hazards, two different NWS alerts",
             fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text((LEFT + RIGHT) / 2, 0.038, "Source: National Weather Service • Ingalls Weather",
             fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
