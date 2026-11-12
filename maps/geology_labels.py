"""
County-specific legend wording for the shared geology color classes.

Colors never change -- a class is the same color in every county and
state. Only the legend text is local:

  line 1: the local name(s) the source data gives that class in this
          county ("Little Butte Volcanics", "Crescent Formation",
          "Belt Supergroup"), when one or two names cover most of it;
          otherwise a regional fallback ("Cascade volcanic rocks") for
          the vaguest classes, or the generic class label.
  line 2: what kind of rock that is, plus the age range actually present
          in this county ("younger volcanic rocks, ~40-25 million years
          ago").

Name sources: Oregon (DOGAMI OGDC-7) -- the statewide "thematic" terrane /
group field (formation for intrusive rocks), used as-is except for
generic placeholder groups. Washington (DNR 1:100k) -- unit names, tidied
("Simcoe Mountains, volcanic rocks of" -> "Simcoe Mountains volcanic
rocks"; "Ravalli Group, Revett Formation, Belt Supergroup" -> "Belt
Supergroup"). The data wins wherever it has a name; REGION is only a
fallback for where it doesn't.
"""
import re

from shapely.geometry import shape

# Classes whose shared label is already as specific as the data allows.
FIXED = {"water", "ice", "surficial_loess", "surficial_flood", "crb", "crb_imnaha",
         "crb_grande_ronde", "crb_wanapum", "crb_saddle_mtns"}

NOUN = {
    "surficial": "glacial, river & landslide deposits",
    "cz_sedimentary": "younger sedimentary rocks",
    "cz_volcanic": "younger volcanic rocks",
    "crb": "Columbia River Basalt",
    "plutonic": "granite & other intrusive rocks",
    "mz_pz_sedimentary": "older sedimentary rocks",
    "mz_pz_volcanic": "older volcanic rocks",
    "metamorphic": "metamorphic rocks",
    "ultramafic": "serpentinite & related rocks",
    "precambrian": "Precambrian rocks",
}
# Fallback wording by region, only for the two vaguest classes.
FALLBACK_NOUN = {"cz_volcanic": "volcanic rocks", "cz_sedimentary": "sedimentary rocks"}

REGION = {
    ("WA", "Adams"): "Columbia Basin", ("WA", "Asotin"): "Blue Mountains",
    ("WA", "Benton"): "Columbia Basin", ("WA", "Chelan"): "Cascade",
    ("WA", "Clallam"): "Olympic Peninsula", ("WA", "Clark"): "Cascade",
    ("WA", "Columbia"): "Blue Mountains", ("WA", "Cowlitz"): "Cascade",
    ("WA", "Douglas"): "Columbia Basin", ("WA", "Ferry"): "Okanogan Highlands",
    ("WA", "Franklin"): "Columbia Basin", ("WA", "Garfield"): "Blue Mountains",
    ("WA", "Grant"): "Columbia Basin", ("WA", "Grays Harbor"): "Coast Range",
    ("WA", "Island"): "Puget Lowland", ("WA", "Jefferson"): "Olympic Peninsula",
    ("WA", "King"): "Cascade", ("WA", "Kitsap"): "Puget Lowland",
    ("WA", "Kittitas"): "Cascade", ("WA", "Klickitat"): "Cascade",
    ("WA", "Lewis"): "Cascade", ("WA", "Lincoln"): "Columbia Basin",
    ("WA", "Mason"): "Olympic Peninsula", ("WA", "Okanogan"): "Okanogan Highlands",
    ("WA", "Pacific"): "Willapa Hills", ("WA", "Pend Oreille"): "Selkirk Mountains",
    ("WA", "Pierce"): "Cascade", ("WA", "San Juan"): "San Juan Islands",
    ("WA", "Skagit"): "North Cascades", ("WA", "Skamania"): "Cascade",
    ("WA", "Snohomish"): "Cascade", ("WA", "Spokane"): "Columbia Basin",
    ("WA", "Stevens"): "Okanogan Highlands", ("WA", "Thurston"): "Puget Lowland",
    ("WA", "Wahkiakum"): "Willapa Hills", ("WA", "Walla Walla"): "Columbia Basin",
    ("WA", "Whatcom"): "North Cascades", ("WA", "Whitman"): "Columbia Basin",
    ("WA", "Yakima"): "Cascade",
    ("OR", "Baker"): "Blue Mountains", ("OR", "Benton"): "Coast Range",
    ("OR", "Clackamas"): "Cascade", ("OR", "Clatsop"): "Coast Range",
    ("OR", "Columbia"): "Coast Range", ("OR", "Coos"): "Coast Range",
    ("OR", "Crook"): "Central Oregon", ("OR", "Curry"): "Klamath Mountains",
    ("OR", "Deschutes"): "Cascade", ("OR", "Douglas"): "Southern Oregon",
    ("OR", "Gilliam"): "Columbia Plateau", ("OR", "Grant"): "Blue Mountains",
    ("OR", "Harney"): "High Desert", ("OR", "Hood River"): "Cascade",
    ("OR", "Jackson"): "Cascade", ("OR", "Jefferson"): "Central Oregon",
    ("OR", "Josephine"): "Klamath Mountains", ("OR", "Klamath"): "Cascade",
    ("OR", "Lake"): "High Desert", ("OR", "Lane"): "Cascade",
    ("OR", "Lincoln"): "Coast Range", ("OR", "Linn"): "Cascade",
    ("OR", "Malheur"): "High Desert", ("OR", "Marion"): "Cascade",
    ("OR", "Morrow"): "Columbia Plateau", ("OR", "Multnomah"): "Cascade",
    ("OR", "Polk"): "Coast Range", ("OR", "Sherman"): "Columbia Plateau",
    ("OR", "Tillamook"): "Coast Range", ("OR", "Umatilla"): "Blue Mountains",
    ("OR", "Union"): "Blue Mountains", ("OR", "Wallowa"): "Blue Mountains",
    ("OR", "Wasco"): "Cascade", ("OR", "Washington"): "Coast Range",
    ("OR", "Wheeler"): "Central Oregon", ("OR", "Yamhill"): "Coast Range",
}

# OGDC groups that are placeholders, not names.
OR_GENERIC = {"", "no data", "quaternary surficial deposits", "quaternary sedimentary deposits",
              "neogene sedimentary rocks", "neogene volcanic rocks", "paleogene sedimentary rocks",
              "paleogene volcanic rocks", "quaternary volcanics", "nevadan intrusives",
              "coastal intrusives group"}
WA_NOT_NAMES = {"unconsolidated materials", "ultramafic rocks", "undifferentiated till",
                "nonmarine ice-contact deposits", "morainal deposits", "water"}

NAME_SHARE = 0.2      # the main name must cover >= 20% of the class
SECOND_SHARE = {"WA": 0.05, "OR": 0.2}  # a second name: WA lists any unit >= 5%
                      # (Ringold is only ~7% of Benton's exposed sediments --
                      # mostly buried under flood deposits -- but belongs there)
NAMED_TOTAL = 0.4     # ... and the listed names >= 40% together, else fallback
MAX_NAME_CHARS = 46
AGE_MIN_SHARE = 0.05  # units under 5% of a class don't stretch its age range


def clean_wa_name(name):
    n = (name or "").strip()
    if not n or n[0].islower() or n.lower() in WA_NOT_NAMES:
        if n.lower().startswith("mostly vashon"):
            return "Vashon glacial deposits"
        return None
    n = re.sub(r"\s+of\s+[A-Z][A-Za-z]+(\s+and others)?\s*\(\d{4}\)", "", n)
    n = re.sub(r"\s*\([^)]*\)", "", n)
    parts = [p.strip() for p in n.split(",") if p.strip()]
    rank = [(r"Supergroup\b", 5), (r"\bterrane\b", 4), (r"\bGroup\b", 3), (r"[Bb]atholith\b", 2.5),
            (r"\bFormation\b", 2), (r"\bComplex\b|\bcomplex\b", 1.5)]

    def score(p):
        return max([s for pat, s in rank if re.search(pat, p)] or [0])
    # A formation/group named anywhere wins over its member or subunit:
    # "Ellensburg Formation, Snipes Mountain conglomerate member of" ->
    # "Ellensburg Formation"; "Roslyn Formation, lower member of" -> "Roslyn Formation"
    named = [p for p in parts if score(p) >= 2 and not p.endswith(" of")]
    # "Simcoe Mountains, volcanic rocks of" -> "Simcoe Mountains volcanic rocks"
    for i, p in enumerate(parts if not named else []):
        if p.endswith(" of") and i > 0:
            kind = p[:-3].split(" and ")[0]
            return f"{parts[i - 1]} {kind}".replace("Mount St Helens", "Mount St. Helens")
    best = max(parts, key=lambda p: (score(p), -parts.index(p)))
    best = re.sub(r"\bWinderemere\b", "Windermere", best)
    if re.search(r"Belt Supergroup|Ravalli Group|Missoula Group|Piegan Group|Prichard Formation"
                 r"|Wallace Formation|Revett Formation|Burke Formation|St Regis Formation", n):
        return "Belt Supergroup"
    return best[0].upper() + best[1:]


WEST_WA = {"Puget Lowland", "Olympic Peninsula", "Coast Range", "Willapa Hills",
           "San Juan Islands", "North Cascades", "Cascade"}


def is_proper(name):
    """A real name has >= 2 capitalized words ("Ringold Formation", "Basalt
    Peak dacite"); one-capital phrases are descriptions ("Mass-wasting
    deposits", "Intrusive rocks", "Chelan complex")."""
    return sum(w[:1].isupper() for w in re.split(r"[\s/-]+", name)) >= 2


VOLCANIC_NAME = re.compile(r"[Vv]olcanic|Lavas|Basalt\b")
INTRUSIVE_NAME = re.compile(r"[Bb]atholith|[Pp]luton|[Ii]ntrusive|[Cc]omplex|[Ss]tock|[Dd]iabase"
                            r"|[Gg]abbro|[Oo]phiolite|[Gg]ranite|[Gg]ranodiorite|[Tt]onalite"
                            r"|[Tt]rondhjemite|[Qq]uartz [Mm]onzonite|[Dd]iorite|Plutonic")


def local_name(props, state, cls, county=None):
    n = _local_name(props, state, cls, county)
    if not n:
        return None
    # a volcanic unit's name shouldn't label sedimentary or intrusive rock,
    # and an intrusive class needs a name that describes an intrusion
    if cls in ("cz_sedimentary", "mz_pz_sedimentary", "plutonic") and VOLCANIC_NAME.search(n):
        return None
    if cls == "plutonic" and not INTRUSIVE_NAME.search(n):
        return None
    return n


def _local_name(props, state, cls, county=None):
    if state == "OR":
        if cls == "plutonic":
            f = (props.get("formation") or "").strip()
            if f and f.lower() not in ("no data",):
                return f
        g = (props.get("group") or "").strip()
        return None if g.lower() in OR_GENERIC else g
    n = clean_wa_name(props.get("name"))
    if n == "Vashon glacial deposits":
        # DNR: "mostly Vashon Stade in western WA; unnamed in eastern WA"
        return n if REGION.get(("WA", county)) in WEST_WA else None
    return n if n and is_proper(n) else None


# ---------- ages ----------
EPOCHS = [  # (pattern, start Ma, end Ma); more specific first
    ("Holocene", 0.0117, 0), ("Pleistocene", 2.58, 0.0117), ("Quaternary", 2.58, 0),
    ("Pliocene", 5.33, 2.58), ("Miocene", 23.0, 5.33), ("Oligocene", 33.9, 23.0),
    ("Eocene", 56.0, 33.9), ("Paleocene", 66.0, 56.0), ("Neogene", 23.0, 2.58),
    ("Paleogene", 66.0, 23.0), ("Tertiary", 66.0, 2.58), ("Cretaceous", 145, 66),
    ("Jurassic", 201, 145), ("Triassic", 252, 201), ("Permian", 299, 252),
    ("Pennsylvanian", 323, 299), ("Mississippian", 359, 323), ("Carboniferous", 359, 299),
    ("Devonian", 419, 359), ("Silurian", 444, 419), ("Ordovician", 485, 444),
    ("Cambrian", 539, 485), ("Mesozoic", 252, 66), ("Paleozoic", 539, 252),
    ("Cenozoic", 66, 0), ("Proterozoic", 2500, 539), ("Precambrian", 2500, 539),
    ("Archean", 4000, 2500),
]


def age_range(age):
    """(oldest, youngest) Ma covered by an age string, or None."""
    a = age or ""
    if a.lower().startswith("pre-"):
        return None
    hits = [(s, e) for pat, s, e in EPOCHS if re.search(pat, a, re.I)]
    if not hits:
        return None
    return max(s for s, _ in hits), min(e for _, e in hits)


def fmt_ma(ma):
    if ma >= 100:
        return f"{round(ma, -1):,.0f}"
    if ma >= 10:
        return f"{ma:.0f}"
    return f"{ma:.1f}".rstrip("0").rstrip(".")


def fmt_age(old, young):
    if young < 0.02:
        return f"~{fmt_ma(old)} million years ago to today" if old >= 1 else "Ice Age to today"
    if young < 1:
        return f"~{fmt_ma(old)} million to ~{young * 1e6:,.0f} years ago"
    if fmt_ma(old) == fmt_ma(young):
        return f"~{fmt_ma(old)} million years ago"
    return f"~{fmt_ma(old)}–{fmt_ma(young)} million years ago"


# ---------- per-county labels ----------
def county_labels(features, state, county, classes):
    """{class_key: legend label} for one county's geology features."""
    by_cls = {}
    for f in features:
        p = f["properties"]
        by_cls.setdefault(p["class"], []).append((p, shape(f["geometry"]).area))
    base = {c["key"]: c for c in classes}
    out = {}
    for cls, items in by_cls.items():
        c = base[cls]
        if cls in FIXED or cls not in NOUN:
            out[cls] = f"{c['label']}\n({c['age']})" if c.get("age") else c["label"]
            continue
        total = sum(a for _, a in items) or 1
        # names
        names = {}
        for p, a in items:
            n = local_name(p, state, cls, county)
            if n:
                names[n] = names.get(n, 0) + a
        ranked = [(n, a / total) for n, a in sorted(names.items(), key=lambda x: -x[1])]
        top = []
        if ranked and ranked[0][1] >= NAME_SHARE:
            top = [ranked[0]] + [r for r in ranked[1:2] if r[1] >= SECOND_SHARE[state]]
        title = None
        if top and sum(s for _, s in top) >= NAMED_TOTAL:
            title = " & ".join(n for n, _ in top)
            # "Ellensburg Formation & Ringold Formation" -> "Ellensburg & Ringold Formations"
            m = re.fullmatch(r"(.+) (Formation|Group) & (.+) \2", title)
            if m:
                title = f"{m.group(1)} & {m.group(3)} {m.group(2)}s"
            if len(title) > MAX_NAME_CHARS:
                title = top[0][0]
        # age range from units covering >= AGE_MIN_SHARE of the class
        ages = {}
        for p, a in items:
            r = age_range(p.get("age"))
            if r:
                ages[r] = ages.get(r, 0) + a
        keep = [r for r, a in ages.items() if a / total >= AGE_MIN_SHARE] or list(ages)
        age = fmt_age(max(r[0] for r in keep), min(r[1] for r in keep)) if keep else c.get("age")
        if cls == "surficial":
            out[cls] = (f"{title}\n({NOUN[cls]}, {c['age']})" if title
                        else f"{c['label']}\n({c['age']})")
        elif title:
            out[cls] = f"{title}\n({NOUN[cls]}, {age})"
        elif cls in FALLBACK_NOUN and (state, county) in REGION:
            out[cls] = f"{REGION[(state, county)]} {FALLBACK_NOUN[cls]}\n({age})"
        else:
            out[cls] = f"{c['label']}\n({age})"
    return out
