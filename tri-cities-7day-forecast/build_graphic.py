import argparse
import json
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import FancyBboxPatch

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

ICON_FONT = fm.FontProperties(fname="fonts/easy_weather_icons_font.ttf")

# ---------- palette ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
CARD_FILL = "#ffffff"
CARD_EDGE = "#d8d5cc"
TODAY_EDGE = "#164f29"  # forest green, in the spirit of the logo's pine tree

# icon color by condition category
COLOR_SUN = "#e8a33d"
COLOR_CLOUD = "#8a887c"
COLOR_RAIN = "#2f6fb0"
COLOR_SNOW = "#5aa9d6"
COLOR_STORM = "#5b4b8a"
COLOR_MUTED = "#9a9483"  # fog/haze/smoke/dust
COLOR_WIND = "#3f8f8f"
COLOR_SEVERE = "#c0392b"

# ---------- easy-weather-icons-font glyph names -> codepoints ----------
# Subset of https://github.com/boxbot6/easy-weather-icons-font relevant to
# NWS forecast icon codes, "day" variants only (see easy_weather_icons_font.json
# for the full IcoMoon glyph set -- MIT licensed, see fonts/LICENSE-easy-weather-icons-font.txt).
GLYPHS = {
    "UNKNOWNday": 0xe901,
    "CLEARday": 0xe96d,
    "FAIRday": 0xe970,
    "PARTLY_CLOUDYday": 0xe967,
    "MOSTLY_CLOUDYday": 0xe961,
    "CLOUDYday": 0xe95e,
    "WINDYday": 0xe95b,
    "WINDY_CLOUDYday": 0xe9b5,
    "SNOWday": 0xe940,
    "MIXED_RAIN_SNOWday": 0xe916,
    "MIXED_RAIN_SLEETday": 0xe919,
    "MIXED_SNOW_SLEETday": 0xe91c,
    "FREEZING_RAINday": 0xe925,
    "SLEETday": 0xe946,
    "RAINday": 0xe92e,
    "SHOWERSday": 0xe928,
    "SCATTERED_SHOWERSday": 0xe979,
    "THUNDERSTORMSday": 0xe910,
    "THUNDERSHOWERSday": 0xe982,
    "ISOLATED_THUNDERSTORMSday": 0xe976,
    "TORNADOday": 0xe904,
    "HURRICANEday": 0xe90a,
    "TROPICAL_STORMday": 0xe907,
    "DUSTday": 0xe949,
    "SMOKYday": 0xe955,
    "HAZEday": 0xe952,
    "FOGGYday": 0xe94c,
    "BLOWING_SNOWday": 0xe93d,
}

# NWS forecast icon code (from the last path segment of the "icon" URL,
# e.g. https://api.weather.gov/icons/land/day/tsra,40 -> "tsra") -> (glyph, color)
NWS_ICON_MAP = {
    "skc": ("CLEARday", COLOR_SUN),
    "few": ("FAIRday", COLOR_SUN),
    "sct": ("PARTLY_CLOUDYday", COLOR_CLOUD),
    "bkn": ("MOSTLY_CLOUDYday", COLOR_CLOUD),
    "ovc": ("CLOUDYday", COLOR_CLOUD),
    "wind_skc": ("WINDYday", COLOR_WIND),
    "wind_few": ("WINDYday", COLOR_WIND),
    "wind_sct": ("WINDY_CLOUDYday", COLOR_WIND),
    "wind_bkn": ("WINDY_CLOUDYday", COLOR_WIND),
    "wind_ovc": ("WINDY_CLOUDYday", COLOR_WIND),
    "snow": ("SNOWday", COLOR_SNOW),
    "rain_snow": ("MIXED_RAIN_SNOWday", COLOR_SNOW),
    "rain_sleet": ("MIXED_RAIN_SLEETday", COLOR_SNOW),
    "snow_sleet": ("MIXED_SNOW_SLEETday", COLOR_SNOW),
    "fzra": ("FREEZING_RAINday", COLOR_SNOW),
    "rain_fzra": ("FREEZING_RAINday", COLOR_SNOW),
    "snow_fzra": ("FREEZING_RAINday", COLOR_SNOW),
    "sleet": ("SLEETday", COLOR_SNOW),
    "rain": ("RAINday", COLOR_RAIN),
    "rain_showers": ("SHOWERSday", COLOR_RAIN),
    "rain_showers_hi": ("SCATTERED_SHOWERSday", COLOR_RAIN),
    "tsra": ("THUNDERSTORMSday", COLOR_STORM),
    "tsra_sct": ("THUNDERSHOWERSday", COLOR_STORM),
    "tsra_hi": ("ISOLATED_THUNDERSTORMSday", COLOR_STORM),
    "tornado": ("TORNADOday", COLOR_SEVERE),
    "hurricane": ("HURRICANEday", COLOR_SEVERE),
    "tropical_storm": ("TROPICAL_STORMday", COLOR_SEVERE),
    "dust": ("DUSTday", COLOR_MUTED),
    "smoke": ("SMOKYday", COLOR_MUTED),
    "haze": ("HAZEday", COLOR_MUTED),
    "hot": ("CLEARday", COLOR_SUN),
    "cold": ("CLEARday", COLOR_WIND),
    "blizzard": ("BLOWING_SNOWday", COLOR_SNOW),
    "fog": ("FOGGYday", COLOR_MUTED),
}


def icon_code_from_url(url):
    """https://api.weather.gov/icons/land/day/tsra,40?size=medium -> 'tsra'
    (drops the query string, the percent-chance suffix, and any second
    slash-separated condition -- we only show the dominant/first one)."""
    path = url.split("?")[0]
    after_day_night = path.split("land/")[-1].split("/", 1)[-1]
    first_condition = after_day_night.split("/")[0]
    return first_condition.split(",")[0]


def glyph_for(icon_url):
    code = icon_code_from_url(icon_url)
    name, color = NWS_ICON_MAP.get(code, ("UNKNOWNday", INK_SECONDARY))
    return chr(GLYPHS[name]), color


def daily_columns(periods):
    """Pairs sequential (daytime, following-night) periods into up to 7 day
    columns: label/date/icon from the daytime period, high from its temp,
    low from the paired night's temp. If the feed starts overnight (fetched
    after sunset, before a Today period exists), that leading night period
    is dropped -- it has no daytime pair to lead a column."""
    if periods and not periods[0]["isDaytime"]:
        periods = periods[1:]

    columns = []
    i = 0
    while i < len(periods) and len(columns) < 7:
        day = periods[i]
        low = periods[i + 1]["temperature"] if i + 1 < len(periods) and not periods[i + 1]["isDaytime"] else None
        columns.append({
            "label": day["name"],
            "date": datetime.fromisoformat(day["startTime"]),
            "high": day["temperature"],
            "low": low,
            "icon": day["icon"],
        })
        i += 2
    return columns


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Tri-Cities TV-style 7-day forecast graphic.")
    ap.add_argument("--forecast", default="forecast.json")
    ap.add_argument("--output", default="tri_cities_7day_forecast.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.forecast))
    props = data["properties"]
    columns = daily_columns(props["periods"])

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    LEFT, RIGHT = 0.055, 0.965
    CARD_TOP, CARD_BOTTOM = 0.775, 0.135
    GUTTER = 0.012
    n = len(columns)
    card_w = (RIGHT - LEFT - (n - 1) * GUTTER) / n

    for idx, col in enumerate(columns):
        x0 = LEFT + idx * (card_w + GUTTER)
        x1 = x0 + card_w
        cx = (x0 + x1) / 2
        is_today = col["label"] == "Today"

        card = FancyBboxPatch(
            (x0, CARD_BOTTOM), card_w, CARD_TOP - CARD_BOTTOM,
            boxstyle="round,pad=0,rounding_size=0.012",
            facecolor=CARD_FILL, edgecolor=TODAY_EDGE if is_today else CARD_EDGE,
            linewidth=1.8 if is_today else 1.0, zorder=2)
        ax.add_patch(card)

        day_label = col["label"].upper() if is_today else col["date"].strftime("%A").upper()
        ax.text(cx, CARD_TOP - 0.045, day_label, ha="center", va="top",
                 fontproperties=f_bold, fontsize=13.5,
                 color=TODAY_EDGE if is_today else INK, zorder=3)
        ax.text(cx, CARD_TOP - 0.085, col["date"].strftime("%b %-d"), ha="center", va="top",
                 fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY, zorder=3)

        glyph, color = glyph_for(col["icon"])
        ax.text(cx, (CARD_TOP + CARD_BOTTOM) / 2 + 0.045, glyph, ha="center", va="center",
                 fontproperties=ICON_FONT, fontsize=40, color=color, zorder=3)

        ax.text(cx, CARD_BOTTOM + 0.085, f"{col['high']}°", ha="center", va="bottom",
                 fontproperties=f_bold, fontsize=20, color=INK, zorder=3)
        low_text = f"{col['low']}°" if col["low"] is not None else "—"
        ax.text(cx, CARD_BOTTOM + 0.03, low_text, ha="center", va="bottom",
                 fontproperties=f_med, fontsize=15, color=INK_SECONDARY, zorder=3)

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

        # nudged up from TITLE_BLOCK_BOTTOM -- the title+subtitle text doesn't
        # fill the full reserved block (there's dead space below the
        # subtitle's descender), so top-aligning the logo to the block reads
        # as sitting low; this centers it on the text's actual visual span.
        logo_y0 = TITLE_BLOCK_BOTTOM + 0.025
        logo_ax = fig.add_axes([LEFT, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")

        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    generated = datetime.fromisoformat(props["generatedAt"])
    fig.text(title_x, 0.935, f"{data.get('label', 'Tri-Cities')} 7-Day Forecast",
              fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, f"Updated {generated.strftime('%A, %B %-d')} at {generated.strftime('%-I:%M %p %Z')}",
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text((LEFT + RIGHT) / 2, 0.045, "National Weather Service — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
