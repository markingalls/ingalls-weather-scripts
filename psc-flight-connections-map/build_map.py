"""
PSC Flight Connections Map -- map builder
Ingalls Weather

Two styled maps -- one of the US + southern Canada, one of the whole world
-- of every airport you can fly to from Tri-Cities Airport (PSC, Pasco WA)
with zero or one layover, built entirely from Wikipedia's "Airlines and
destinations" tables.

  1. PSC's own Wikipedia article gives its nonstop destinations (the
     "hubs" -- SEA, SLC, DEN, etc.).
  2. Each hub's Wikipedia article gives that hub's nonstop destinations.
  3. Anything reachable from a hub that PSC doesn't already serve nonstop
     is a one-layover destination.

Dots are colored by which hub you'd connect through. Nonstop destinations
get their own color, and a one-layover destination reachable through two
or more different hubs gets a separate "multiple options" color (the
legend lists how many airports fall in each bucket on that map).

DATA SOURCES / METHODOLOGY
--------------------------
Wikipedia's MediaWiki API, action=parse, for each airport article's
rendered HTML. Only the passenger table(s) are read -- any table that sits
under a "Cargo" heading is skipped. Within a destinations cell:

  - Each wikilink is one destination airport (link targets are the airport
    articles themselves, e.g. "Seattle/Tacoma" -> Seattle-Tacoma
    International Airport, so the article title is the airport's identity
    -- redirects are resolved so two spellings of the same airport merge).
  - A bold "Seasonal:" label marks the links after it as seasonal; they're
    kept (it's a real scheduled route, just not year-round). "Charter:" /
    "Seasonal charter:" routes are dropped -- they aren't generally
    bookable as part of a connection.
  - A "(begins <date>)" note dated after today drops that route (not
    flying yet); an "(ends <date>)" note dated before today drops it too.
    Wikipedia editors don't always clean these up promptly, so the note's
    date -- not just the presence of the note -- decides.

Coordinates come from each article's primary {{coord}} (prop=coordinates),
with Wikidata P625 as a fallback; IATA codes come from Wikidata P238 (the
same item the article's infobox draws from).

What "one layover" does and doesn't mean here: any airline into the hub,
any airline out of it -- the tables don't say which routes interline or
share an alliance, so this is "physically possible with one stop", not
"bookable on one ticket". (In particular, Allegiant at PSC doesn't sell
connections, so its LAS/AZA/SNA connections are self-transfer only.)
Same-day schedule alignment isn't checked either.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cartopy.crs as ccrs
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from matplotlib.lines import Line2D
from matplotlib.transforms import offset_copy
from PIL import Image
from shapely.geometry import shape

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

WORLD_COUNTRIES_FILE = MAPS_DIR / "world_countries_50m.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

STATE_LINE_COUNTRIES = {"United States of America", "Canada", "Mexico"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------
ORIGIN_TITLE = "Tri-Cities Airport (Washington)"
ORIGIN_IATA = "PSC"
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Wikimedia asks automated clients for a descriptive User-Agent.
HTTP_HEADERS = {"User-Agent": "airport-connections-map/1.0 (python-requests; one-off map script)"}

# Pause between successful requests, to stay under Wikimedia's rate limit.
REQUEST_SPACING_S = 2.0

DATE_NOTE_RE = re.compile(r"\(\s*(begins|resumes|ends|until)\s+([^)]*?)\s*\)", re.I)
DATE_FORMATS = ("%B %d, %Y", "%d %B %Y", "%B %Y", "%b %d, %Y")

# ---------------------------------------------------------------------------
# Colors. Hub colors are fixed per IATA code (not assigned in order) so a
# hub keeps its color from run to run even if PSC's route list changes;
# anything not listed falls through to FALLBACK_HUB_COLORS.
# ---------------------------------------------------------------------------
NONSTOP_COLOR, NONSTOP_EDGE = "#1f1d1a", "white"
MULTI_COLOR, MULTI_EDGE = "#8f8b80", "#4f4c45"
ORIGIN_COLOR = "#e8332a"
HUB_COLORS = {
    "SEA": "#1f6fd1",
    "SLC": "#e8862a",
    "DEN": "#2e9e4f",
    "MSP": "#8a4fc7",
    "PHX": "#d94f8a",
    "SFO": "#16a3a3",
    "LAX": "#e0c12b",
    "PDX": "#6b8e23",
    "LAS": "#c0392b",
    "SNA": "#8b5a2b",
    "AZA": "#5dade2",
}
FALLBACK_HUB_COLORS = ["#b5651d", "#2c3e8f", "#a0a0d0", "#7b241c", "#1abc9c"]

LAND_COLOR, OCEAN_COLOR = "#d7dcd0", "#bfe1ef"

# ---------------------------------------------------------------------------
# Map definitions
# ---------------------------------------------------------------------------
MAPS = {
    "us": dict(
        fig_size=(10.8, 8.6),
        axes_rect=[0.03, 0.205, 0.94, 0.665],
        proj=ccrs.LambertConformal(central_longitude=-97.5, central_latitude=40,
                                   standard_parallels=(33, 45)),
        extent=[-124.0, -67.0, 22.5, 54.5],
        # Destinations are counted/drawn if they fall in this lon/lat box --
        # a little looser than `extent`, since LCC's curved parallels let the
        # frame's corners reach slightly beyond it.
        visible_box=(-135.0, -55.0, 18.0, 62.0),
        title="Where Can You Fly From PSC?",
        region_label="U.S. & Southern Canada",
        dot_size=26,
        nonstop_size=70,
        label_nonstop=True,
        legend_ncol=5,
    ),
    "world": dict(
        fig_size=(12.0, 8.0),
        axes_rect=[0.03, 0.19, 0.94, 0.68],
        proj=ccrs.Robinson(central_longitude=10),
        extent=None,  # global
        visible_box=(-180.0, 180.0, -90.0, 90.0),
        title="Where Can You Fly From PSC?",
        region_label="Worldwide",
        dot_size=16,
        nonstop_size=40,
        label_nonstop=False,
        legend_ncol=5,
    ),
}
# Per-airport (dx, dy) label offsets in points for the US map's nonstop
# labels; anything not listed sits 6pt to the right of its dot.
NONSTOP_LABEL_OFFSETS = {
    "SEA": (-6, 0), "PDX": (-6, 0),
    "LAX": (-6, 3), "SNA": (6, -4),
    "PHX": (-6, 2), "AZA": (6, -5),
}

FIG_DPI = 200
MAP_FRAME_INSET_PX = 22


# ===========================================================================
# Fetching
# ===========================================================================
def wiki_get(url, params, retries=7):
    """
    GET a MediaWiki API endpoint. Wikimedia rate-limits bursts of
    unauthenticated requests with HTTP 429, so back off (honoring
    Retry-After when given) rather than failing outright.
    """
    params = {**params, "format": "json", "formatversion": 2}
    for attempt in range(retries):
        wait = min(5 * 2 ** attempt, 120)
        try:
            r = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=60)
            if r.status_code == 429:
                ra = r.headers.get("Retry-After", "")
                wait = int(ra) if ra.isdigit() else wait
                raise requests.HTTPError("429 Too Many Requests")
            r.raise_for_status()
            time.sleep(REQUEST_SPACING_S)
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                raise
            print(f"  request failed ({e}); retrying in {wait}s")
            time.sleep(wait)


def parse_note_date(s):
    s = re.sub(r"\s+", " ", s.strip().rstrip(",."))
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def is_reference(el):
    """True if el sits inside a footnote marker / style block we should ignore."""
    for p in el.parents:
        if not isinstance(p, Tag):
            continue
        if p.name in ("sup", "style", "script"):
            return True
    return False


def parse_destination_cell(td, today):
    """
    Walk one destinations <td> in document order and return a list of
    {"title", "text", "seasonal"} for every route that's currently flying.
    """
    routes = []
    label = ""
    last = None
    for el in td.descendants:
        if is_reference(el):
            continue
        if isinstance(el, Tag):
            if el.name == "b":
                t = el.get_text(" ", strip=True)
                if t.endswith(":"):
                    label = t[:-1].strip().lower()
                continue
            if el.name == "a":
                href = el.get("href", "")
                if not href.startswith("/wiki/"):
                    continue
                title = requests.utils.unquote(href[len("/wiki/"):]).split("#")[0].replace("_", " ")
                if ":" in title.split(" ")[0]:  # File:, Help:, Wikipedia: ...
                    continue
                last = {"title": title, "text": el.get_text(" ", strip=True),
                        "seasonal": "seasonal" in label, "charter": "charter" in label,
                        "drop": False}
                routes.append(last)
        elif isinstance(el, NavigableString) and last is not None:
            for kind, when in DATE_NOTE_RE.findall(str(el)):
                d = parse_note_date(when)
                kind = kind.lower()
                if d is None:
                    continue
                if kind == "begins" and d > today:
                    last["drop"] = True
                if kind in ("ends", "until") and d < today:
                    last["drop"] = True
    return [r for r in routes if not r["drop"] and not r["charter"]]


def fetch_airport_routes(title, today):
    """
    Return (canonical_title, [route, ...]) for one airport article's
    passenger destinations tables.
    """
    data = wiki_get(WIKI_API, {"action": "parse", "page": title, "prop": "text", "redirects": 1})
    if "error" in data:
        print(f"  WARNING: couldn't parse {title!r}: {data['error'].get('info')}")
        return title, []
    canonical = data["parse"]["title"]
    soup = BeautifulSoup(data["parse"]["text"], "html.parser")
    routes = []
    for table in soup.find_all("table", class_="wikitable"):
        first_row = table.find("tr")
        if not first_row:
            continue
        headers = [c.get_text(" ", strip=True).lower() for c in first_row.find_all(["th", "td"])]
        if not any("airline" in h for h in headers) or not any("destination" in h for h in headers):
            continue
        heading = table.find_previous(["h2", "h3", "h4"])
        if heading and "cargo" in heading.get_text().lower():
            continue
        dest_col = next(i for i, h in enumerate(headers) if "destination" in h)
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) <= dest_col:
                continue
            airline = cells[0].get_text(" ", strip=True)
            for r in parse_destination_cell(cells[dest_col], today):
                r["airline"] = airline
                routes.append(r)
    return canonical, routes


def resolve_titles(titles):
    """
    Resolve redirects and fetch coordinates + Wikidata IDs for a batch of
    article titles. Returns {input_title: {"title", "lat", "lon", "qid"}}.
    """
    titles = sorted(set(titles))
    out = {}
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        data = wiki_get(WIKI_API, {
            "action": "query", "titles": "|".join(chunk), "redirects": 1,
            "prop": "coordinates|pageprops", "ppprop": "wikibase_item",
            "coprimary": "primary", "colimit": "max",
        })
        q = data.get("query", {})
        alias = {}
        for kind in ("normalized", "redirects"):
            for m in q.get(kind, []):
                alias[m["from"]] = m["to"]
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in chunk:
            final = t
            for _ in range(5):
                if final in alias:
                    final = alias[final]
            p = pages.get(final, {})
            coords = (p.get("coordinates") or [{}])[0]
            out[t] = {
                "title": final,
                "lat": coords.get("lat"),
                "lon": coords.get("lon"),
                "qid": (p.get("pageprops") or {}).get("wikibase_item"),
                "missing": p.get("missing", False),
            }
    return out


def fetch_wikidata(qids):
    """{qid: {"iata": str|None, "lat", "lon"}} from Wikidata P238 / P625."""
    qids = sorted({q for q in qids if q})
    out = {}
    for i in range(0, len(qids), 50):
        data = wiki_get(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                                       "props": "claims"})
        for qid, ent in data.get("entities", {}).items():
            claims = ent.get("claims", {})

            def first(prop):
                for c in claims.get(prop, []):
                    v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
                    if v is not None:
                        return v
                return None

            coord = first("P625") or {}
            out[qid] = {"iata": first("P238"), "lat": coord.get("latitude"), "lon": coord.get("longitude")}
    return out


def fetch_network():
    today = datetime.now(LOCAL_TZ).date()
    print(f"Fetching {ORIGIN_TITLE} ...")
    origin_title, origin_routes = fetch_airport_routes(ORIGIN_TITLE, today)

    # Hub (nonstop) list, keyed by canonical title. Keep the label text PSC's
    # table uses ("Seattle/Tacoma") for display.
    hub_link_titles = {r["title"] for r in origin_routes}
    resolved = resolve_titles(hub_link_titles | {origin_title})
    origin_canon = resolved[origin_title]["title"]
    hubs = {}
    for r in origin_routes:
        canon = resolved[r["title"]]["title"]
        h = hubs.setdefault(canon, {"text": r["text"], "airlines": set(), "seasonal": True})
        h["airlines"].add(r["airline"])
        h["seasonal"] = h["seasonal"] and r["seasonal"]
    print(f"  {len(hubs)} nonstop destinations: {', '.join(h['text'] for h in hubs.values())}")

    # Each hub's own destinations.
    hub_routes = {}
    for canon in hubs:
        print(f"Fetching {canon} ...")
        _, routes = fetch_airport_routes(canon, today)
        hub_routes[canon] = routes
        print(f"  {len(routes)} routes")

    # Resolve every destination link to a canonical airport.
    all_titles = {r["title"] for rs in hub_routes.values() for r in rs}
    print(f"Resolving {len(all_titles)} destination article titles ...")
    resolved.update(resolve_titles(all_titles - set(resolved)))
    canon_info = {v["title"]: v for v in resolved.values()}
    print("Fetching IATA codes from Wikidata ...")
    wd = fetch_wikidata(v["qid"] for v in canon_info.values())

    airports = {}

    def airport(canon, text):
        a = airports.get(canon)
        if a is None:
            info = canon_info.get(canon, {})
            w = wd.get(info.get("qid"), {})
            lat = info.get("lat") if info.get("lat") is not None else w.get("lat")
            lon = info.get("lon") if info.get("lon") is not None else w.get("lon")
            a = airports[canon] = {"title": canon, "name": text, "iata": w.get("iata"),
                                   "lat": lat, "lon": lon, "nonstop": False, "via": {}}
        return a

    for canon, h in hubs.items():
        a = airport(canon, h["text"])
        a["nonstop"] = True
        a["nonstop_airlines"] = sorted(h["airlines"])

    for hub, routes in hub_routes.items():
        hub_iata = airports[hub]["iata"] or hub
        for r in routes:
            canon = resolved[r["title"]]["title"]
            if canon in (origin_canon, hub):
                continue
            a = airport(canon, r["text"])
            a["via"].setdefault(hub_iata, set()).add(r["airline"])

    origin_info = canon_info.get(origin_canon, {})
    origin = {"title": origin_canon, "iata": ORIGIN_IATA, "name": "Tri-Cities",
              "lat": origin_info.get("lat"), "lon": origin_info.get("lon")}

    out = []
    dropped = []
    for a in airports.values():
        if a["lat"] is None or a["lon"] is None:
            dropped.append(a["title"])
            continue
        a["via"] = {k: sorted(v) for k, v in sorted(a["via"].items())}
        out.append(a)
    if dropped:
        print(f"  NOTE: {len(dropped)} destination link(s) had no coordinates and were skipped: "
              + ", ".join(sorted(dropped)))
    return origin, out, datetime.now(timezone.utc)


# ===========================================================================
# Classification
# ===========================================================================
def classify(a):
    """'nonstop', 'multi', or a hub IATA code."""
    if a["nonstop"]:
        return "nonstop"
    if len(a["via"]) > 1:
        return "multi"
    return next(iter(a["via"]))


def hub_color_map(airports):
    hubs = sorted({a["iata"] for a in airports if a["nonstop"] and a["iata"]})
    colors = {}
    fallback = iter(FALLBACK_HUB_COLORS)
    for h in hubs:
        colors[h] = HUB_COLORS.get(h) or next(fallback, "#555555")
    return colors


# ===========================================================================
# Rendering
# ===========================================================================
def load_world_countries():
    """(countries_except_antarctica, antarctica) -- the US map leaves Antarctica out."""
    with open(WORLD_COUNTRIES_FILE) as f:
        data = json.load(f)
    rest, antarctica = [], []
    for feat in data["features"]:
        if not feat.get("geometry"):
            continue
        is_ant = feat["properties"].get("ADMIN") == "Antarctica"
        (antarctica if is_ant else rest).append(shape(feat["geometry"]))
    return rest, antarctica


def load_states():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    out = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            continue
        if props.get("admin") in STATE_LINE_COUNTRIES:
            out.append(shape(feat["geometry"]))
    return out


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def build_map(kind, origin, airports, fetched_at, output_path):
    cfg = MAPS[kind]
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)
    fig_w, fig_h = cfg["fig_size"]

    countries, antarctica = load_world_countries()
    pc = ccrs.PlateCarree()
    geod = ccrs.Geodetic()

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes(cfg["axes_rect"], projection=cfg["proj"])
    if cfg["extent"]:
        ax.set_extent(cfg["extent"], crs=pc)
    else:
        ax.set_global()
    ax.set_facecolor(OCEAN_COLOR)

    ax.add_geometries(countries, crs=pc, facecolor=LAND_COLOR, edgecolor="#8a8578",
                      linewidth=0.35 if kind == "world" else 0.6, zorder=1)
    if kind == "world":
        ax.add_geometries(antarctica, crs=pc, facecolor=LAND_COLOR, edgecolor="#8a8578",
                          linewidth=0.35, zorder=1)
    else:
        ax.add_geometries(load_states(), crs=pc, facecolor="none", edgecolor="#a8a396",
                          linewidth=0.5, zorder=2)
        ax.add_geometries(load_boundary_lines(ADMIN0_LINES_FILE), crs=pc, facecolor="none",
                          edgecolor="#3a2f21", linewidth=1.0, zorder=2.5)

    lon0, lon1, lat0, lat1 = cfg["visible_box"]
    visible = [a for a in airports if lon0 <= a["lon"] <= lon1 and lat0 <= a["lat"] <= lat1]

    hub_colors = hub_color_map(airports)
    by_cat = {}
    for a in visible:
        by_cat.setdefault(classify(a), []).append(a)

    # Great-circle spokes PSC -> each nonstop destination.
    for a in by_cat.get("nonstop", []):
        ax.plot([origin["lon"], a["lon"]], [origin["lat"], a["lat"]], transform=geod,
                color="#1f1d1a", linewidth=1.0, alpha=0.55, zorder=20, solid_capstyle="round")

    # One-stop dots. Multi-option dots first (underneath), then single-hub
    # dots in a fixed hub order, so a lone hub-specific dot is never buried.
    draw_order = ["multi"] + sorted(k for k in by_cat if k not in ("multi", "nonstop"))
    for cat in draw_order:
        pts = by_cat.get(cat, [])
        if not pts:
            continue
        if cat == "multi":
            color, edge = MULTI_COLOR, MULTI_EDGE
        else:
            color, edge = hub_colors.get(cat, "#555555"), "white"
        ax.scatter([a["lon"] for a in pts], [a["lat"] for a in pts], s=cfg["dot_size"],
                   color=color, edgecolor=edge, linewidth=0.5, alpha=0.95, zorder=30, transform=pc)

    # Nonstop destinations on top.
    ns = by_cat.get("nonstop", [])
    ax.scatter([a["lon"] for a in ns], [a["lat"] for a in ns], s=cfg["nonstop_size"],
               color=NONSTOP_COLOR, edgecolor=NONSTOP_EDGE, linewidth=1.0, zorder=40, transform=pc)
    # PSC itself.
    ax.scatter([origin["lon"]], [origin["lat"]], s=cfg["nonstop_size"] * 1.9, marker="*",
               color=ORIGIN_COLOR, edgecolor="white", linewidth=0.8, zorder=45, transform=pc)

    stroke = [pe.withStroke(linewidth=2.0, foreground=(1, 1, 1, 0.9))]
    base_t = pc._as_mpl_transform(ax)
    if cfg["label_nonstop"]:
        # Labels go right of the dot by default; NONSTOP_LABEL_OFFSETS
        # overrides that for the close pairs (LAX/SNA, PHX/AZA) and the
        # coast, so they don't collide.
        for a in ns:
            dx, dy = NONSTOP_LABEL_OFFSETS.get(a["iata"], (6, 0))
            t = offset_copy(base_t, fig=fig, x=dx, y=dy, units="points")
            ax.text(a["lon"], a["lat"], a["iata"] or a["name"], transform=t, fontsize=8.5,
                    fontproperties=poppins_med, color="#1f1d1a", ha="left" if dx >= 0 else "right",
                    va="center", zorder=46, path_effects=stroke)
    t = offset_copy(base_t, fig=fig, x=0, y=9, units="points")
    ax.text(origin["lon"], origin["lat"], ORIGIN_IATA, transform=t, fontsize=9.5,
            fontproperties=poppins_med, color=ORIGIN_COLOR, ha="center", va="bottom",
            zorder=46, path_effects=stroke)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # ---- Legend ----
    fig.canvas.draw()
    frame = ax.get_window_extent()
    frame_center = (frame.x0 + frame.x1) / 2 / (fig_w * FIG_DPI)

    def handle(color, edge, label, size=7.5, marker="o", mew=0.6):
        return Line2D([0], [0], marker=marker, linestyle="none", color=color, markeredgecolor=edge,
                      markeredgewidth=mew, markersize=size, label=label)

    handles = [handle(ORIGIN_COLOR, "white", "PSC", size=11, marker="*")]
    handles.append(handle(NONSTOP_COLOR, NONSTOP_EDGE, f"Nonstop ({len(ns)})", size=8.5, mew=1.0))
    for h in sorted(hub_colors):
        n = len(by_cat.get(h, []))
        if n:
            handles.append(handle(hub_colors[h], "white", f"Only via {h} ({n})"))
    n_multi = len(by_cat.get("multi", []))
    if n_multi:
        handles.append(handle(MULTI_COLOR, MULTI_EDGE, f"Multiple layover options ({n_multi})"))

    legend_top = (frame.y0 / (fig_h * FIG_DPI)) - 0.022
    leg = fig.legend(handles=handles, loc="upper center", frameon=False, prop=poppins_reg,
                     fontsize=9, ncol=cfg["legend_ncol"], handletextpad=0.5, columnspacing=1.6,
                     labelspacing=0.75, bbox_to_anchor=(frame_center, legend_top))
    for txt in leg.get_texts():
        txt.set_color("#2b2a26")
        txt.set_fontsize(9.25)

    # ---- Title block ----
    n_one = len(visible) - len(ns)
    fig.text(0.03, 0.977, cfg["title"], fontsize=21, fontproperties=poppins_reg,
             color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.937,
             f"{cfg['region_label']} • {len(visible)} airports with 0 or 1 layovers "
             f"({len(ns)} nonstop, {n_one} with one stop)",
             fontsize=12, fontproperties=poppins_med, color="#3a3835", ha="left", va="top")
    fetched_local = fetched_at.astimezone(LOCAL_TZ)
    fig.text(0.03, 0.905,
             f"Colored by layover airport • scheduled passenger routes as listed "
             f"{fetched_local.strftime('%b %-d, %Y')}, charters excluded, seasonal included",
             fontsize=10.25, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")
    fig.text(0.5, 0.012, "Route data: Wikipedia airport \"Airlines and destinations\" tables — Ingalls Weather",
             fontsize=9, fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved {kind} map to {output_path}")

    # ---- Logo, bottom-left inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        frame_left = int(frame.x0)
        frame_bottom = bh - int(frame.y0)
        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * (0.07 if kind == "us" else 0.06))
        target_h = int(logo.height * target_w / logo.width)
        logo = logo.resize((target_w, target_h), Image.LANCZOS)
        pos = (frame_left + MAP_FRAME_INSET_PX, frame_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo, pos)
        base.save(output_path)
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping.")


def print_summary(airports):
    cats = {}
    for a in airports:
        cats.setdefault(classify(a), []).append(a)
    for c in sorted(cats, key=lambda c: (c != "nonstop", c == "multi", c)):
        names = sorted(a["iata"] or a["name"] for a in cats[c])
        print(f"  {c:8s} {len(names):4d}  {' '.join(names[:40])}{' ...' if len(names) > 40 else ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build Ingalls Weather maps of airports reachable from PSC with 0 or 1 layovers.")
    parser.add_argument("--file", type=Path, default=None,
                        help="Render from a saved snapshot (.json) instead of fetching Wikipedia live.")
    parser.add_argument("--map", choices=["us", "world", "both"], default="both")
    args = parser.parse_args()

    if args.file:
        if not args.file.exists():
            sys.exit(f"--file {args.file} not found.")
        snap = json.loads(args.file.read_text())
        origin, airports = snap["origin"], snap["airports"]
        fetched_at = datetime.fromisoformat(snap["fetched_at"])
    else:
        origin, airports, fetched_at = fetch_network()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snap_path = OUTPUT_DIR / f"snapshot_{fetched_at.strftime('%Y-%m-%dT%H%M%SZ')}.json"
        snap_path.write_text(json.dumps({"origin": origin, "airports": airports,
                                         "fetched_at": fetched_at.isoformat()}, indent=1))
        print(f"Saved snapshot to {snap_path}")

    print_summary(airports)
    stamp = fetched_at.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    kinds = ["us", "world"] if args.map == "both" else [args.map]
    for k in kinds:
        build_map(k, origin, airports, fetched_at, OUTPUT_DIR / f"psc_connections_{k}_{stamp}.png")
