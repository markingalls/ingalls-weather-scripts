"""
Crosswalk from USGS State Geologic Map Compilation (SGMC) units to the
shared color classes in geology_classes.json, for any state.

SGMC's per-state sources differ a lot in detail -- Oregon's (Walker &
MacLeod 1991) splits the Columbia River Basalt into formations, while
Washington's lumps it into "Miocene volcanic rocks" -- so classes are
assigned from SGMC's standardized fields, which every state has:

  - the unit's lithologies in <ST>_lith.csv (lith1 = Igneous /
    Sedimentary / Metamorphic / Unconsolidated / Water ..., lith2 =
    Volcanic / Plutonic / Clastic / Carbonate / Schist ...), and
  - its age string in <ST>_units.csv,

plus a short list of named overrides (Columbia River Basalt formations,
and state units known to be CRB that the generic rules can't see).

Usage from a map project:
    import sys; sys.path.insert(0, "../maps")
    from geology_sgmc import load_classes, classify_state
    classes = load_classes()                 # ordered list of class dicts
    lookup = classify_state("/tmp/sgmc_or", "OR")   # unit_link -> class key
"""
import json
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# State-specific units the generic rules would misfile. Keep this short and
# commented -- every entry is a judgment call about a source map.
UNIT_OVERRIDES = {
    # The only SGMC unit (of OR/WA/ID) with no lithology rows; it's
    # described as wacke (graywacke sandstone).
    "WAPzu;0": "mz_pz_sedimentary",
    # Washington's SGMC source maps the Columbia River Basalt Group only as
    # "Miocene volcanic rocks" (tholeiite, Middle Miocene).
    "WAMIv;0": "crb",
}

CRB_NAME = re.compile(r"Columbia River Basalt|Grande Ronde|Wanapum|Saddle Mountains"
                      r"|Picture Gorge|Columbia Plateau", re.I)
IMNAHA_NAME = re.compile(r"Imnaha Basalt", re.I)
ULTRAMAFIC = re.compile(r"serpentin|peridotit|dunite|ultramafic|harzburgite", re.I)

# Oldest era named in an SGMC age string wins ("Permian to Triassic" ->
# paleozoic). Checked oldest-first.
ERA_WORDS = [
    ("precambrian", r"Proterozoic|Archean|Precambrian"),
    ("paleozoic", r"Cambrian|Ordovician|Silurian|Devonian|Mississippian"
                  r"|Pennsylvanian|Carboniferous|Permian|Paleozoic"),
    ("mesozoic", r"Triassic|Jurassic|Cretaceous|Mesozoic"),
    ("cenozoic", r"Paleocene|Eocene|Oligocene|Miocene|Pliocene|Tertiary"
                 r"|Pleistocene|Holocene|Quaternary|Cenozoic"),
]


QUATERNARY = re.compile(r"Pleistocene|Holocene|Quaternary", re.I)
PRE_QUATERNARY = re.compile(r"Pliocene|Miocene|Oligocene|Eocene|Paleocene|Tertiary"
                            r"|Cretaceous|Jurassic|Triassic|Paleozoic|Permian|Proterozoic", re.I)


def is_quaternary(age):
    age = age or ""
    return bool(QUATERNARY.search(age)) and not PRE_QUATERNARY.search(age)


def load_classes():
    with open(os.path.join(HERE, "geology_classes.json")) as fh:
        return json.load(fh)["classes"]


def era_of(age):
    age = age or ""
    for era, pat in ERA_WORDS:
        if re.search(pat, age, re.I):
            return era
    return None


def classify_unit(unit_link, name, age, liths):
    """liths: list of (rank, lith1, lith2, lith3) for the unit, in file order."""
    if unit_link in UNIT_OVERRIDES:
        return UNIT_OVERRIDES[unit_link]
    name = name or ""
    if IMNAHA_NAME.search(name):
        return "crb_imnaha"
    if CRB_NAME.search(name):
        return "crb"

    major = [l for l in liths if str(l[0]).strip() == "Major"] or \
            [l for l in liths if "major" in str(l[0]).lower()] or liths
    if not major:
        raise ValueError(f"{unit_link}: no lithology rows")
    l1, l2 = str(major[0][1]), str(major[0][2])
    all_major_text = " ".join(" ".join(map(str, l[1:])) for l in major)
    era = era_of(age)

    if l1 == "Water":
        return "water"
    if l1 == "Ice" or (re.search(r"\bice\b|glacier", name, re.I) and l1 not in ("Unconsolidated",)):
        return "ice"
    if l1 == "Unconsolidated":
        return "surficial"
    if ULTRAMAFIC.search(all_major_text) or ULTRAMAFIC.search(name):
        return "ultramafic"
    if l1 == "Igneous" and l2 in ("Plutonic", "Hypabyssal"):
        return "plutonic"
    if era == "precambrian":
        return "precambrian"

    young = era == "cenozoic"
    has_volcanic = any(str(l[1]) == "Igneous" and str(l[2]) == "Volcanic"
                       or str(l[2]) in ("Greenstone", "Metavolcanic") for l in major)
    if l1 == "Igneous":  # Volcanic
        return "cz_volcanic" if young else "mz_pz_volcanic"
    if l1 == "Sedimentary":
        # Many states file Ice Age alluvium/till/lake beds as "Sedimentary"
        # rather than "Unconsolidated" -- an all-Quaternary age settles it.
        if is_quaternary(age):
            return "surficial"
        if young:
            return "cz_sedimentary"
        # Old mixed sedimentary/volcanic packages (island-arc terranes)
        # read as volcanic when a volcanic lithology is also major.
        return "mz_pz_volcanic" if has_volcanic else "mz_pz_sedimentary"
    if l1 == "Metamorphic":
        if l2 in ("Greenstone", "Metavolcanic"):
            return "cz_volcanic" if young else "mz_pz_volcanic"
        if l2 in ("Argillite", "Slate", "Phyllite", "Metasedimentary"):
            # low-grade: still reads as the sedimentary/volcanic package
            if has_volcanic:
                return "cz_volcanic" if young else "mz_pz_volcanic"
            return "cz_sedimentary" if young else "mz_pz_sedimentary"
        return "metamorphic"
    raise ValueError(f"{unit_link}: unhandled lithology {l1}/{l2}")


def classify_state(sgmc_dir, state):
    """Return {unit_link: class_key} for every unit in a state's SGMC files."""
    units = pd.read_csv(os.path.join(sgmc_dir, f"{state}_units.csv"))
    lith = pd.read_csv(os.path.join(sgmc_dir, f"{state}_lith.csv"))
    units["unit_link"] = units["unit_link"].str.strip()
    lith["unit_link"] = lith["unit_link"].str.strip()
    by_unit = {k: list(g[["lith_rank", "lith1", "lith2", "lith3"]].itertuples(index=False, name=None))
               for k, g in lith.groupby("unit_link", sort=False)}
    return {row.unit_link: classify_unit(row.unit_link, row.unit_name, row.unit_age,
                                         by_unit.get(row.unit_link, []))
            for row in units.itertuples()}
