"""
"Longest Day of the Year" chart -- Kennewick, WA
Ingalls Weather

Three horizontal bars, each drawn to the true length of a calendar day in
Kennewick (America/Los_Angeles), shaded night/day by actual sunrise and
sunset:

  - Top:    the fall-back Sunday (first Sunday of November) -- 25 hours,
            with the repeated 01:00 hour highlighted.
  - Middle: the following June solstice -- an ordinary 24-hour day, with
            the most daylight of the year.
  - Bottom: the following spring-forward Sunday (second Sunday of March)
            -- 23 hours, with the skipped 02:00 hour marked.

Day lengths come straight from the tz database (time between consecutive
local midnights), not hard-coded, and every hour tick is labelled with
the local clock time at that instant -- so the doubled "01" and the
missing "02" fall out of the data.

Sunrise/sunset use the NOAA solar calculator equations (upper limb on a
sea-level horizon, -0.833 deg refraction allowance -- terrain ignored),
the same method as ../pnw-sunrise-map/.

USAGE
-----
    python build_chart.py                 # Nov 1 2026 / Jun 21 2027 / Mar 14 2027
    python build_chart.py --fall-year 2027
"""

import argparse
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle

# ---------------------------------------------------------------------------
# Paths / fonts / palette (same canvas as ../tri-cities-temp-chart/)
# ---------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
OUTPUT_DIR = THIS_DIR / "output"
LOGO_FILE = REPO_ROOT / "assets" / "ingalls_weather_logo.png"

FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
NIGHT_COLOR = "#2c3268"   # deep indigo -- late end of ../pnw-sunrise-map's ramp
DAY_COLOR = "#f6cf74"     # sunrise gold -- early end of the same ramp
ACCENT = "#c9531c"
MISSING_COLOR = "#e4e1d9"   # hours a short day doesn't have
MISSING_HATCH = "#c3beb2"
MISSING_EDGE = "#a8a397"        # warm amber accent (repo's climatology-line hue)

# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
PLACE = "Kennewick, WA"
LAT, LON = 46.2112, -119.1372
TZ = ZoneInfo("America/Los_Angeles")

BAR_HEIGHT = 0.86
TRACK_HOURS = 25          # every bar is drawn on the same 25-hour track
ROW_STEP = 1.85           # vertical distance between bars, data units
HEADER_OFFSET = 0.70      # header baseline above bar center, data units
FIG_W_IN, FIG_H_IN = 8.0, 10.0


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def june_solstice(year):
    """June solstice date in Pacific time (Meeus' mean-solstice
    polynomial, good to a few minutes -- plenty to pick the calendar day)."""
    y = (year - 2000) / 1000
    jde = 2451716.56767 + 365241.62603 * y + 0.00325 * y**2 + 0.00888 * y**3 - 0.00030 * y**4
    utc = datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=jde - 2451545.0)
    return utc.astimezone(TZ).date()


# ---------------------------------------------------------------------------
# Time / sun
# ---------------------------------------------------------------------------
def local_midnight_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=TZ).astimezone(timezone.utc)


def day_length_hours(d):
    """True length of the local calendar day (23, 24 or 25 h)."""
    return (local_midnight_utc(d + timedelta(days=1)) - local_midnight_utc(d)).total_seconds() / 3600


def sun_times_utc(d):
    """(sunrise, sunset) as UTC datetimes -- NOAA solar calculator."""
    jd = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() / 86400 + 2440587.5 + 20 / 24
    t = (jd - 2451545.0) / 36525
    l0 = math.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t)) + math.sin(2 * m) * (0.019993 - 0.000101 * t)
         + math.sin(3 * m) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    app_long = math.radians(math.degrees(l0) + c - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(app_long))
    y = math.tan(eps / 2) ** 2
    eqt = 4 * math.degrees(y * math.sin(2 * l0) - 2 * e * math.sin(m) + 4 * e * y * math.sin(m) * math.cos(2 * l0)
                           - 0.5 * y * y * math.sin(4 * l0) - 1.25 * e * e * math.sin(2 * m))
    lat_r = math.radians(LAT)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
                                - math.tan(lat_r) * math.tan(decl)))
    base = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    rise = base + timedelta(minutes=720 - 4 * (LON + ha) - eqt)
    sset = base + timedelta(minutes=720 - 4 * (LON - ha) - eqt)
    return rise, sset


def elapsed_hours(d, t_utc):
    return (t_utc - local_midnight_utc(d)).total_seconds() / 3600


def clock(t_utc):
    """Local HH:MM, rounded (not truncated) to the nearest minute."""
    return (t_utc + timedelta(seconds=30)).astimezone(TZ).strftime("%H:%M")


def fmt_duration(hours):
    total = int(round(hours * 60))
    return f"{total // 60}h {total % 60:02d}m"


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def draw_day_bar(ax, y, d, accent_ticks=()):
    n = day_length_hours(d)
    rise, sset = sun_times_utc(d)
    r, s = elapsed_hours(d, rise), elapsed_hours(d, sset)
    h = BAR_HEIGHT

    # Shared 25-hour track: whatever this day doesn't have is a hatched gray
    # stub, so all three bars read against the same full-length frame.
    if n < TRACK_HOURS:
        ax.add_patch(Rectangle((n, y - h / 2), TRACK_HOURS - n, h, facecolor=MISSING_COLOR,
                               edgecolor=MISSING_HATCH, hatch="////", linewidth=0, zorder=1.5))
        ax.add_patch(Rectangle((n, y - h / 2), TRACK_HOURS - n, h, facecolor="none",
                               edgecolor=MISSING_EDGE, linewidth=1.0, zorder=1.6))
    ax.add_patch(Rectangle((0, y - h / 2), r, h, facecolor=NIGHT_COLOR, edgecolor="none", zorder=2))
    ax.add_patch(Rectangle((r, y - h / 2), s - r, h, facecolor=DAY_COLOR, edgecolor="none", zorder=2))
    ax.add_patch(Rectangle((s, y - h / 2), n - s, h, facecolor=NIGHT_COLOR, edgecolor="none", zorder=2))
    ax.add_patch(Rectangle((0, y - h / 2), n, h, facecolor="none", edgecolor=INK, linewidth=1.0, zorder=4))

    # Hour ticks + local clock label at each hour boundary.
    mid = local_midnight_utc(d)
    labels = []
    for k in range(int(round(n)) + 1):
        t = mid + timedelta(hours=k)
        ax.plot([k, k], [y - h / 2, y - h / 2 + 0.07], color=(1, 1, 1, 0.55) if 0 < k < n else INK,
                linewidth=0.8, zorder=3)
        label = "24" if k == round(n) else t.astimezone(TZ).strftime("%H")
        labels.append(label)
        accent = k in accent_ticks
        ax.text(k, y - h / 2 - 0.05, label, ha="center", va="top",
                fontproperties=f_bold if accent else f_reg, fontsize=8.6,
                color=ACCENT if accent else INK_SECONDARY, zorder=5)

    # Sunrise / sunset callouts just above the bar.
    for x, txt in ((r, f"Sunrise {clock(rise)}"), (s, f"Sunset {clock(sset)}")):
        ax.text(x, y + h / 2 + 0.04, txt, ha="center", va="bottom", fontproperties=f_med, fontsize=9.2,
                color=INK, zorder=5)
    ax.text((r + s) / 2, y, f"{fmt_duration(s - r)} of daylight", ha="center", va="center",
            fontproperties=f_med, fontsize=10.5, color=INK, zorder=5)

    return n, labels


def build_chart(fall_year, output_path):
    fall = nth_sunday(fall_year, 11, 1)
    solstice = june_solstice(fall_year + 1)
    spring = nth_sunday(fall_year + 1, 3, 2)

    # 4:5 portrait -- Instagram's tallest feed format (1080x1350 at 135
    # dpi; saved at 200 dpi = 1600x2000, same aspect). Row headers sit above
    # each bar so the bars get the full width.
    fig = plt.figure(figsize=(FIG_W_IN, FIG_H_IN), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.05, 0.085, 0.90, 0.725])
    ax.set_xlim(-0.3, TRACK_HOURS + 0.3)
    ax.set_ylim(-0.8, 2 * ROW_STEP + 0.92)
    ax.axis("off")

    # accent_ticks: hour-boundary indices whose clock label gets the accent
    # color -- the two "01"s on the fall-back day, and the "03" that comes
    # straight after "01" on the spring-forward day.
    rows = [
        (2 * ROW_STEP, fall, "Fall back", "Clocks repeat 01:00", (1, 2)),
        (ROW_STEP, solstice, "Summer solstice", "Most daylight of the year", ()),
        (0, spring, "Spring forward", "Clocks skip 02:00", (2,)),
    ]
    for y, d, head, sub, accent_ticks in rows:
        n, _ = draw_day_bar(ax, y, d, accent_ticks)
        print(f"{d}  {n:.0f} h  sunrise {clock(sun_times_utc(d)[0])}  sunset {clock(sun_times_utc(d)[1])}")
        # One header line above the bar, baseline-aligned pieces laid end to
        # end: length (bold, leads) : date · what happens (accent) · detail.
        x = 0.0
        renderer = fig.canvas.get_renderer()
        for txt, font, size, color in ((f"{n:.0f} hours:", f_bold, 17, INK),
                                       (f" {d.strftime('%a, %b')} {d.day}, {d.year}", f_med, 13, INK),
                                       (f"   {head}", f_med, 12, ACCENT),
                                       (f"  •  {sub}", f_reg, 11, INK_SECONDARY)):
            t = ax.text(x, y + HEADER_OFFSET, txt, fontproperties=font, fontsize=size, color=color,
                        ha="left", va="baseline")
            x = ax.transData.inverted().transform((t.get_window_extent(renderer).x1, 0))[0]

    h = BAR_HEIGHT
    # Fall back: the repeated hour -- 01:00 PDT (elapsed 1-2) then 01:00
    # PST (elapsed 2-3). Outline both, label the pair.
    y = 2 * ROW_STEP
    ax.add_patch(Rectangle((1, y - h / 2), 2, h, facecolor="none", edgecolor=ACCENT, linewidth=2.4, zorder=6))
    ax.plot([2, 2], [y - h / 2, y + h / 2], color=ACCENT, linewidth=1.2, linestyle=(0, (2, 2)), zorder=6)
    ax.text(1.5, y, "01", ha="center", va="center", fontproperties=f_bold, fontsize=10, color="white", zorder=7)
    ax.text(2.5, y, "01", ha="center", va="center", fontproperties=f_bold, fontsize=10, color="white", zorder=7)

    # Spring forward: 02:00 never happens -- clocks jump 01:59 -> 03:00 at
    # elapsed hour 2.
    y = 0
    ax.plot([2, 2], [y - h / 2, y + h / 2], color=ACCENT, linewidth=2.6, zorder=6)
    # Callout directly under the (accented) "03" label, below the hour-label
    # row so it can't collide with anything.
    ax.text(2, y - h / 2 - 0.27, "02 skipped", fontproperties=f_med, fontsize=9.5, color=ACCENT,
            ha="center", va="top", zorder=7)

    # Title block
    fig.text(0.05, 0.962, "Today Is the Longest\nDay of the Year", fontproperties=f_bold, fontsize=25,
             color=INK, ha="left", va="top", linespacing=0.98)
    fig.text(0.05, 0.868,
             f"Clocks fall back, giving us 25 hours  •  {PLACE}",
             fontproperties=f_reg, fontsize=12.5, color=INK_SECONDARY, ha="left", va="top")

    # Logo, bottom-right (matching ../tri-cities-temp-chart/)
    if LOGO_FILE.exists():
        img = plt.imread(LOGO_FILE)
        w_fig = 0.095
        h_fig = w_fig * FIG_W_IN / FIG_H_IN * img.shape[0] / img.shape[1]
        lax = fig.add_axes([0.95 - w_fig, 0.025, w_fig, h_fig], zorder=20)
        lax.imshow(img)
        lax.axis("off")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Ingalls Weather 'longest day' DST chart.")
    parser.add_argument("--fall-year", type=int, default=2026,
                        help="Year of the fall-back day on the top bar (default: 2026). The solstice and "
                             "spring-forward bars use the following year.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/longest_day_<fall-year>.png).")
    args = parser.parse_args()
    build_chart(args.fall_year, args.out or (OUTPUT_DIR / f"longest_day_{args.fall_year}.png"))
