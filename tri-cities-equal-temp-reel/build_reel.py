"""
Renders normals.json into a vertical (1080x1920, 9:16) FB/IG reel: a
year-clock pie (one wedge per calendar month, sized by day count, January
at 12 o'clock running clockwise) with a temperature that sweeps from the
coldest normal of the year to the warmest. At each step, every day whose
normal sits within +/- HALF_BAND_F of the current temperature lights up in
that temperature's color -- so the two "mirror" stretches of the year that
share the same normal (e.g. early April and late October) light up
together.

Colors come from the Ingalls Weather temperature color table (the same
fixed Kelvin-anchored table columbia-basin-temps uses), so a given shade
means the same absolute temperature here as on the maps.

Use --still TEMP_F to render a single PNG frame instead of the video
(handy for previewing layout, or as a cover image).
"""
import argparse
import json
import os
import subprocess
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Wedge, Circle, Rectangle
import numpy as np

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette (same canvas/ink as tri-cities-temp-chart) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
RULE = "#8a887e"
PIE_FACE = "white"

# ---------- temperature color table (verbatim from columbia-basin-temps) ----------
TEMP_COLOR_TABLE = [
    (205.53962824635747, [20, 1, 11]),
    (220.54105933801642, [72, 2, 42]),
    (223.30970412365585, [114, 5, 69]),
    (226.07834890929527, [156, 7, 95]),
    (228.8469936949347, [190, 31, 133]),
    (231.61563848057412, [216, 33, 184]),
    (234.38428326621354, [224, 94, 226]),
    (237.15292805185297, [208, 143, 208]),
    (239.9215728374924, [198, 174, 206]),
    (242.71111221757047, [177, 149, 200]),
    (245.48274194527255, [153, 122, 186]),
    (248.25437167297463, [120, 90, 160]),
    (251.02600140067673, [95, 67, 136]),
    (253.7976311283788, [75, 44, 128]),
    (256.5692608560809, [52, 34, 130]),
    (259.2740222360249, [44, 54, 150]),
    (262.11252031148507, [62, 73, 174]),
    (264.88415003918715, [79, 90, 198]),
    (267.13811875987665, [90, 128, 206]),
    (269.1251668409579, [100, 165, 214]),
    (271.1122149220392, [94, 194, 212]),
    (273.0992630031204, [40, 142, 160]),
    (275.0863110842017, [24, 105, 120]),
    (279.0604072463642, [28, 108, 79]),
    (283.03450340852675, [39, 132, 85]),
    (286.97216346781227, [60, 150, 83]),
    (289.741977590991, [112, 172, 91]),
    (292.5117917141697, [159, 190, 91]),
    (295.2816058373485, [208, 200, 84]),
    (298.0514199605272, [204, 172, 70]),
    (300.8212340837059, [212, 146, 61]),
    (303.5910482068847, [218, 121, 35]),
    (306.3608623300634, [208, 90, 31]),
    (309.13067645324213, [216, 59, 32]),
    (311.9004905764209, [182, 32, 7]),
    (314.6703046995996, [142, 36, 19]),
    (317.44011882277835, [102, 23, 10]),
    (320.20993294595706, [142, 15, 54]),
    (322.9797470691358, [194, 50, 94]),
    (325.74956119231456, [216, 120, 149]),
    (332.71070543555834, [204, 16, 171]),
]
TEMP_KMIN = TEMP_COLOR_TABLE[0][0]
TEMP_KMAX = TEMP_COLOR_TABLE[-1][0]


def build_temp_colormap():
    span = TEMP_KMAX - TEMP_KMIN
    stops = [((k - TEMP_KMIN) / span, [c / 255 for c in rgb]) for k, rgb in TEMP_COLOR_TABLE]
    return LinearSegmentedColormap.from_list("ingalls_temp", stops, N=1024)


def f_to_k(f):
    return (np.asarray(f) - 32) * 5 / 9 + 273.15


TEMP_CMAP = build_temp_colormap()
TEMP_NORM = Normalize(TEMP_KMIN, TEMP_KMAX)


def temp_color(f):
    return TEMP_CMAP(TEMP_NORM(f_to_k(f)))


# ---------- graphic constants ----------
# The year lights up wherever its normal is within HALF_BAND_F of the
# current temperature. Normals are linearly interpolated between day
# centers at SUBSTEPS points per day, so lit slices grow/shrink smoothly
# (sub-day) from frame to frame instead of snapping a whole day at a time.
HALF_BAND_F = 0.5
SUBSTEPS = 24
MAX_RUNS = 8  # wedge patches kept in the pool; a sweep never needs more than ~3

# Output is 1080x2340 (9:19.5, modern phone screens) so the reel fills the
# whole screen instead of letterboxing. The layout itself is designed on a
# 1080x1920 (9:16) content block, centered on the canvas and scaled down to
# CONTENT_SCALE of the canvas width, so there's plain background margin on
# every side (clear of IG/FB's side buttons and top/bottom overlays).
# X()/Y() map a position in that block to a figure fraction of the full
# canvas, WF()/HF() map a width/height; scaling is done via DPI, so fonts,
# line widths and the logo all shrink together and the content's
# proportions never change.
W_PX, H_PX = 1080, 2340
CONTENT_W_PX, CONTENT_H_PX = 1080, 1920   # design units of the content block
CONTENT_SCALE = 0.80                      # content width / canvas width
DES_W = CONTENT_W_PX / CONTENT_SCALE      # canvas size in design units
DES_H = DES_W * H_PX / W_PX
DPI = 200 * CONTENT_SCALE                 # 200 dpi = the original 1080-wide design
FIG_W, FIG_H = W_PX / DPI, H_PX / DPI


def X(frac):
    """x fraction of the content block -> fraction of the full canvas."""
    return ((DES_W - CONTENT_W_PX) / 2 + frac * CONTENT_W_PX) / DES_W


def Y(frac):
    """y fraction of the content block -> fraction of the full canvas."""
    return ((DES_H - CONTENT_H_PX) / 2 + frac * CONTENT_H_PX) / DES_H


def WF(frac):
    return frac * CONTENT_W_PX / DES_W


def HF(frac):
    return frac * CONTENT_H_PX / DES_H

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
YEAR0 = date(2010, 1, 1)  # non-leap reference year, matching fetch_normals.py


def parse_args():
    ap = argparse.ArgumentParser(description="Render the equal-temperature year-clock reel.")
    ap.add_argument("--normals", default="normals.json")
    ap.add_argument("--output", default="tri_cities_equal_temp_reel.mp4")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--sweep-seconds", type=float, default=10.0,
                    help="Time to sweep from the coldest normal to the warmest")
    ap.add_argument("--hold-seconds", type=float, default=1.2,
                    help="Pause at the start (coldest) and end (warmest) of the sweep")
    ap.add_argument("--cycles", type=int, default=2,
                    help="Number of coldest->warmest->coldest round trips (default 2)")
    ap.add_argument("--still", type=float, default=None, metavar="TEMP_F",
                    help="Render one PNG frame at this temperature instead of the video")
    return ap.parse_args()


def fmt_day(i):
    d = YEAR0 + timedelta(days=int(i))
    return f"{d.strftime('%b')} {d.day}"


def lit_runs(mask):
    """Contiguous runs of True in a circular day mask -> [(start, end)],
    with a Dec->Jan run joined into one."""
    n = len(mask)
    if mask.all():
        return [(0, n - 1)]
    # rotate so index 0 is an off day, then unwrap
    off = int(np.argmin(mask))
    rolled = np.roll(mask, -off)
    runs, start = [], None
    for j, m in enumerate(rolled):
        if m and start is None:
            start = j
        elif not m and start is not None:
            runs.append(((start + off) % n, (j - 1 + off) % n))
            start = None
    if start is not None:
        runs.append(((start + off) % n, (n - 1 + off) % n))
    # chronological by start-of-run, starting from Jan
    return sorted(runs, key=lambda r: r[0])


def fmt_run(r):
    a, b = r
    a, b = int(round(a)) % 365, int(round(b)) % 365
    if a == b:
        return fmt_day(a)
    da, db = YEAR0 + timedelta(days=a), YEAR0 + timedelta(days=b)
    if da.month == db.month:
        return f"{da.strftime('%b')} {da.day}–{db.day}"
    return f"{fmt_day(a)} – {fmt_day(b)}"


class Reel:
    def __init__(self, ndata):
        self.ndata = ndata
        self.normals = np.array([d["normal_f"] for d in ndata["days"]])
        self.n = len(self.normals)
        # fine, circular, linearly interpolated normals: sample k sits at
        # fractional day-of-year x = k / SUBSTEPS (day i's value at x = i + 0.5)
        xs = np.arange(self.n * SUBSTEPS) / SUBSTEPS
        centers = np.arange(self.n + 2) - 0.5
        wrapped = np.concatenate([[self.normals[-1]], self.normals, [self.normals[0]]])
        self.fine = np.interp(xs, centers, wrapped)
        self.tmin, self.tmax = float(self.normals.min()), float(self.normals.max())
        self.annual_mean = ndata["annual_mean_f"]

        self.fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
        self.fig.patch.set_facecolor(BG)
        self._build_header()
        self._build_pie()
        self._build_readout()
        self._build_colorbar()
        self._build_footer()

    # ---------- static pieces ----------
    def _build_header(self):
        fig = self.fig
        lx = X(0.07)
        loc = self.ndata.get("label") or self.ndata["station_name"].title()
        el = self.ndata["element_label"]
        # two-line title, per element (avgt is the default reel)
        line1, line2 = {
            "avgt": (f"{loc} Average", "Annual Temperatures"),
            "maxt": (f"{loc} Annual", "High Temperatures"),
            "mint": (f"{loc} Annual", "Low Temperatures"),
        }[self.ndata["element"]]
        fig.text(lx, Y(0.892), line1,
                 fontproperties=f_bold, fontsize=19, color=INK)
        fig.text(lx, Y(0.862), line2,
                 fontproperties=f_bold, fontsize=19, color=INK)
        fig.text(lx, Y(0.836),
                 f"Times of year that share the same normal daily {el}",
                 fontproperties=f_reg, fontsize=8.6, color=INK_SECONDARY)
        fig.text(lx, Y(0.820),
                 f"NCEI {self.ndata['period']} daily normals • {self.ndata.get('station_label') or self.ndata['station_name'].title()}",
                 fontproperties=f_reg, fontsize=8.6, color=INK_SECONDARY)

    def _build_pie(self):
        fig = self.fig
        size_w = WF(0.86)
        size_h = size_w * FIG_W / FIG_H
        self.pie_ax = ax = fig.add_axes([0.5 - size_w / 2, Y(0.335), size_w, size_h])
        ax.set_xlim(-1.06, 1.06)
        ax.set_ylim(-1.06, 1.06)
        ax.set_aspect("equal")
        ax.axis("off")

        ax.add_patch(Circle((0, 0), 1, facecolor=PIE_FACE, edgecolor="none", zorder=1))

        # pool of wedges, one per lit run of the year; reshaped per frame
        self.run_wedges = []
        for _ in range(MAX_RUNS):
            w = Wedge((0, 0), 1, 0, 1, facecolor="none", edgecolor="none",
                      linewidth=0, zorder=2, visible=False)
            ax.add_patch(w)
            self.run_wedges.append(w)

        # month spokes + labels
        start = 0
        label_stroke = [pe.withStroke(linewidth=3, foreground="white")]
        for m in range(12):
            ndays = (date(2010, m + 2, 1) if m < 11 else date(2011, 1, 1)) - date(2010, m + 1, 1)
            ndays = ndays.days
            ang = np.deg2rad(90 - start * 360 / self.n)
            ax.plot([0, np.cos(ang)], [0, np.sin(ang)], color=INK, linewidth=0.9,
                    zorder=4, solid_capstyle="butt")
            mid = np.deg2rad(90 - (start + ndays / 2) * 360 / self.n)
            t = ax.text(0.72 * np.cos(mid), 0.72 * np.sin(mid), MONTH_ABBR[m],
                        ha="center", va="center", fontproperties=f_med, fontsize=12.5,
                        color=INK, zorder=5)
            t.set_path_effects(label_stroke)
            start += ndays

        ax.add_patch(Circle((0, 0), 1, facecolor="none", edgecolor=INK, linewidth=1.3, zorder=6))
        ax.add_patch(Circle((0, 0), 0.018, facecolor=INK, edgecolor="none", zorder=6))

    def _build_readout(self):
        fig = self.fig
        self.temp_text = fig.text(0.5, Y(0.283), "", ha="center", va="center",
                                  fontproperties=f_bold, fontsize=30, color=INK)
        self.temp_text.set_path_effects([pe.withStroke(linewidth=1.2, foreground=INK)])
        self.period_text = fig.text(0.5, Y(0.236), "", ha="center", va="center",
                                    fontproperties=f_med, fontsize=10.5, color=INK,
                                    linespacing=1.5)

    def _build_colorbar(self):
        fig = self.fig
        # bar range: rounded outward to 5F around the year's normals
        self.cb_lo = 5 * np.floor((self.tmin - 1) / 5)
        self.cb_hi = 5 * np.ceil((self.tmax + 1) / 5)
        cb_left, cb_w, cb_bot, cb_h = X(0.09), WF(0.82), Y(0.172), HF(0.026)
        self.cax = cax = fig.add_axes([cb_left, cb_bot, cb_w, cb_h])
        grad = np.linspace(self.cb_lo, self.cb_hi, 512)
        cax.imshow(f_to_k(grad).reshape(1, -1), aspect="auto", cmap=TEMP_CMAP, norm=TEMP_NORM,
                   extent=[self.cb_lo, self.cb_hi, 0, 1], zorder=1)
        cax.set_xlim(self.cb_lo, self.cb_hi)
        cax.set_ylim(0, 1)
        cax.set_yticks([])
        for spine in cax.spines.values():
            spine.set_edgecolor(RULE)
            spine.set_linewidth(0.6)
        ticks = [t for t in range(-50, 131, 10) if self.cb_lo <= t <= self.cb_hi]
        cax.set_xticks(ticks)
        cax.set_xticklabels([f"{t}°F" for t in ticks])
        cax.tick_params(axis="x", labelsize=8.5, color=RULE, labelcolor=INK, length=3)
        for lab in cax.get_xticklabels():
            lab.set_fontproperties(f_reg)

        # annual mean marker (like the original's "UK mean" line)
        cax.axvline(self.annual_mean, color=INK, linewidth=1.1, zorder=3)
        cax.text(self.annual_mean, 1.12, f"Annual mean {self.annual_mean:.1f}°F",
                 transform=cax.transData, ha="center", va="bottom",
                 fontproperties=f_reg, fontsize=7.5, color=INK_SECONDARY, clip_on=False)

        # moving band box + pointer
        self.band_box = Rectangle((0, -0.12), 2 * HALF_BAND_F, 1.24, facecolor="none",
                                  edgecolor=INK, linewidth=1.6, zorder=4, clip_on=False)
        cax.add_patch(self.band_box)

    def _build_footer(self):
        fig = self.fig
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "assets", "ingalls_weather_logo.png")
        if os.path.exists(logo_path):
            img = plt.imread(logo_path)
            logo_w = WF(0.11)
            logo_h = logo_w * FIG_W / FIG_H * img.shape[0] / img.shape[1]
            lax = fig.add_axes([0.5 - logo_w / 2, Y(0.028), logo_w, logo_h], zorder=20)
            lax.imshow(img)
            lax.axis("off")
        else:
            print(f"NOTE: no logo found at {logo_path} -- skipping logo placement.")
        fig.text(0.5, Y(0.104), "Data: NCEI 1991–2020 normals via ACIS/xmACIS — Ingalls Weather",
                 ha="center", fontproperties=f_reg, fontsize=7, color=INK_SECONDARY)

    # ---------- per-frame ----------
    def update(self, temp_f):
        col = temp_color(temp_f)
        lit = np.abs(self.fine - temp_f) <= HALF_BAND_F
        runs = lit_runs(lit) if lit.any() else []
        nf = len(self.fine)
        step = 360.0 / nf
        for j, w in enumerate(self.run_wedges):
            if j < len(runs):
                a, b = runs[j]
                length = (b - a) % nf + 1
                theta2 = 90 - a * step
                w.set_theta1(theta2 - length * step)
                w.set_theta2(theta2)
                w.set_facecolor(col)
                w.set_visible(True)
            else:
                w.set_visible(False)
        # runs in day units (sample index / SUBSTEPS), dropping sub-day
        # slivers from tiny wiggles in the normals curve
        day_runs = [(a / SUBSTEPS, b / SUBSTEPS) for a, b in runs
                    if ((b - a) % nf + 1) >= SUBSTEPS * 0.5]

        self.temp_text.set_text(f"{temp_f:.0f}°F")
        self.temp_text.set_color(col)
        self.temp_text.set_path_effects([pe.withStroke(linewidth=1.2, foreground=col)])

        if day_runs:
            self.period_text.set_text("   ≈   ".join(fmt_run(r) for r in day_runs))
        else:
            self.period_text.set_text("")

        self.band_box.set_x(temp_f - HALF_BAND_F)

    def frame_rgb(self):
        self.fig.canvas.draw()
        buf = np.asarray(self.fig.canvas.buffer_rgba())
        return buf[:, :, :3]


def ease_in_out(x):
    return 0.5 - 0.5 * np.cos(np.pi * x)


def temp_schedule(lo, hi, fps, sweep_s, hold_s, cycles):
    """Hold at coldest, then `cycles` x (sweep up, hold, sweep down, hold).
    Ends where it starts, so the reel loops seamlessly."""
    n_sweep = int(round(sweep_s * fps))
    n_hold = int(round(hold_s * fps))
    up = lo + (hi - lo) * ease_in_out(np.linspace(0, 1, n_sweep))
    seq = [np.full(n_hold, lo)]
    for _ in range(max(cycles, 1)):
        seq += [up, np.full(n_hold, hi), up[::-1], np.full(n_hold, lo)]
    return np.concatenate(seq)


def main():
    args = parse_args()
    ndata = json.load(open(args.normals))
    reel = Reel(ndata)

    if args.still is not None:
        reel.update(args.still)
        out = os.path.splitext(args.output)[0] + ".png"
        reel.fig.savefig(out, facecolor=BG, dpi=DPI)
        print(f"saved {out}")
        return

    # sweep slightly inside the extremes so the first/last frames still
    # light a real (non-empty) slice of the year
    temps = temp_schedule(reel.tmin + 0.2, reel.tmax - 0.2, args.fps,
                          args.sweep_seconds, args.hold_seconds, args.cycles)

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W_PX}x{H_PX}", "-r", str(args.fps),
           "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-movflags", "+faststart", args.output]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k, t in enumerate(temps):
        reel.update(float(t))
        frame = reel.frame_rgb()
        if frame.shape[:2] != (H_PX, W_PX):
            raise SystemExit(f"frame size {frame.shape[:2]} != {(H_PX, W_PX)}")
        proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        if k % 60 == 0:
            print(f"  frame {k + 1}/{len(temps)}  {t:.1f}°F")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print(f"saved {args.output} ({len(temps) / args.fps:.1f}s @ {args.fps} fps)")


if __name__ == "__main__":
    main()
