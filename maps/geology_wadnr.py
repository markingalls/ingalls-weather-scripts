"""
Crosswalk from Washington DNR's 1:100,000 statewide geologic map (GeMS
edition, "100k Map Unit" + "100k Description of Map Units") to the shared
color classes in geology_classes.json.

DNR map-unit symbols follow one statewide grammar: an age prefix in
capitals (Q, PL, M, E, K, J, TR, PZ, pC, ...) then lithology letters in
lower case, then an optional (member/formation) tag -- e.g. Ql = Quaternary
loess, Qfg = Quaternary flood gravel, Mv(wr) = Miocene volcanic, Roza
Member of the Wanapum Basalt, Kigd = Cretaceous granodiorite. Classes come
from the lithology letters plus DNR's age text (more reliable than the
prefix -- "O" is Oligocene in some quads), with Columbia River Basalt
formations picked out by name. Unknown patterns raise, so a new county
can't be mis-colored silently: extend the rules and re-run.
"""
import re

from geology_sgmc import era_of, is_quaternary

CRB = [
    ("crb_imnaha", re.compile(r"Imnaha Basalt", re.I)),
    ("crb_saddle_mtns", re.compile(r"Saddle Mountains? Basalt", re.I)),
    ("crb_wanapum", re.compile(r"Wanapum Basalt", re.I)),
    ("crb_grande_ronde", re.compile(r"Grande Ronde Basalt", re.I)),
    ("crb", re.compile(r"Columbia River Basalt", re.I)),
]

# Lithology-letter groups (the lower-case letters after the age prefix).
METAMORPHIC = {"og", "bg", "mg", "mi", "hm", "hmc", "am", "sc", "sh", "q", "mb", "gn"}
LOW_GRADE_SED = {"mt", "mm", "ms", "ph", "ar", "mc"}   # argillite/phyllite/metawacke
METAVOLCANIC = {"mv"}
# 'w' = wacke / arenite (e.g. COw, Carboniferous-Ordovician chert-quartz arenite)
SEDIMENTARY_PREFIX = ("c", "m", "n", "s", "bx", "e", "w")  # continental/marine/nearshore...
SURFICIAL_PREFIX = ("a", "g", "l", "ls", "d", "o", "t", "p", "w", "f")

SYMBOL = re.compile(r"^((?:p[A-Z]|PLM|PL|PM|PZ|MZ|PA|CZ|TR|[A-Z])+)([a-z]*)")


def split_symbol(sym):
    m = SYMBOL.match(sym or "")
    return (m.group(1), m.group(2)) if m else ("", "")


def classify(symbol, name, age, description=""):
    name, age, description = name or "", age or "", description or ""
    if symbol in ("wtr", "water") or name.lower() == "water":
        return "water"
    if symbol == "ice" or re.fullmatch(r"(glacial )?ice|glaciers?", name, re.I):
        return "ice"
    for key, pat in CRB:
        if pat.search(name):
            return key
    _, lith = split_symbol(symbol)
    # "pre-Tertiary" etc. would otherwise read as Tertiary (Cenozoic).
    era = "mesozoic" if age.lower().startswith("pre-") else era_of(age)
    text = f"{name} {description}"

    # Units with no age/lithology code in DNR's symbol (statewide only a
    # handful): tectonic zones / breccias of older rock -> metamorphic.
    if re.search(r"tectonic zone|tectonic breccia", name, re.I) or symbol == "bx":
        return "metamorphic"
    if lith == "u" or re.search(r"\bserpentinite\b|peridotite|harzburgite|dunite", name, re.I):
        return "ultramafic"
    if lith.startswith("i"):
        return "plutonic"
    if is_quaternary(age) and not age.lower().startswith("pre-"):
        if lith.startswith("v"):
            return "cz_volcanic"
        if lith == "l" or re.search(r"\bloess\b|Palouse Formation", text, re.I):
            return "surficial_loess"
        if lith.startswith("f") or re.search(r"Missoula|outburst flood|Bonneville flood", name, re.I):
            return "surficial_flood"
        return "surficial"
    if lith in METAMORPHIC:
        return "metamorphic"
    if era == "precambrian":
        return "precambrian"
    young = era == "cenozoic"
    if lith in METAVOLCANIC or lith.startswith("v"):
        return "cz_volcanic" if young else "mz_pz_volcanic"
    if lith in LOW_GRADE_SED or lith.startswith(SEDIMENTARY_PREFIX):
        return "cz_sedimentary" if young else "mz_pz_sedimentary"
    if lith.startswith(SURFICIAL_PREFIX) and young:
        return "surficial"
    # No lithology letters: fall back to the rock named in the description.
    if re.search(r"gneiss|schist|migmatite|amphibolite|marble", text, re.I):
        return "metamorphic"
    if re.search(r"granit|granodiorite|tonalite|diorite|gabbro|pluton", text, re.I):
        return "plutonic"
    raise ValueError(f"unclassified DNR unit {symbol!r} ({name!r}, {age!r}) -- "
                     "extend the rules in geology_wadnr.py")
