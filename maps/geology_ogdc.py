"""
Crosswalk from DOGAMI's Oregon Geologic Data Compilation, release 7
(OGDC-7, GeMS schema) to the shared color classes in geology_classes.json.

OGDC-7 tags every map-unit polygon with standardized statewide "thematic"
fields -- ThematicRockType (volcanic rocks, sediments, batholith rocks...),
ThematicAge (Miocene, Permian/Triassic...), ThematicTerraneGroup (Columbia
River Basalt Group, Baker Terrane...) and ThematicFormation (Grande Ronde
Basalt, Loess...) -- so classes come from those, plus the unit name for
ultramafic rocks. Unknown combinations raise, so a new county can't be
mis-colored silently.
"""
import re

CRB_FORMATIONS = {
    "Imnaha Basalt": "crb_imnaha",
    "Grande Ronde Basalt": "crb_grande_ronde",
    "Wanapum Basalt": "crb_wanapum",
    "Saddle Mountain Basalt": "crb_saddle_mtns",
    "Saddle Mountains Basalt": "crb_saddle_mtns",
}
ULTRAMAFIC = re.compile(r"serpentin|peridotit|dunite|harzburgite|ultramafic", re.I)
CENOZOIC = re.compile(r"Paleocene|Eocene|Oligocene|Miocene|Pliocene|Pleistocene|Holocene"
                      r"|Tertiary|Quaternary", re.I)
QUATERNARY_ONLY = {"Quaternary", "Holocene", "Pleistocene"}
VOLCANIC = {"volcanic rocks", "volcanic rock", "volcaniclastic rocks", "volcaniclastic rock",
            "vent and pyroclastic rocks", "invasive extrusive rocks", "marine volcanic rocks"}
SEDIMENTARY = {"marine sedimentary rocks", "terrestrial sedimentary rocks", "melange rocks"}


def classify(rock_type, age, terrane, formation, name=""):
    rock = (rock_type or "").strip().lower()
    age = (age or "").strip()
    terrane = (terrane or "").strip()
    formation = (formation or "").strip()
    name = name or ""

    if re.fullmatch(r"(open )?water|lakes?|reservoir", name.strip(), re.I):
        return "water"
    if terrane == "Columbia River Basalt Group":
        return CRB_FORMATIONS.get(formation, "crb")
    if ULTRAMAFIC.search(name):
        return "ultramafic"
    # The first age named is the oldest ("Permian/Triassic"); a unit is
    # Cenozoic only if that oldest age is.
    oldest = age.split("/")[0]
    young = bool(CENOZOIC.fullmatch(oldest))
    quaternary = oldest in QUATERNARY_ONLY or (oldest == "Pleistocene")

    if rock == "sediments":
        if formation == "Loess" or re.search(r"\bloess\b", name, re.I):
            return "surficial_loess"
        if re.search(r"flood", formation, re.I):
            return "surficial_flood"
        return "surficial" if quaternary or young else "mz_pz_sedimentary"
    if rock in ("intrusive rocks", "batholith rocks"):
        return "plutonic"
    if rock == "metamorphic rocks":
        return "metamorphic"
    if rock in VOLCANIC:
        return "cz_volcanic" if young else "mz_pz_volcanic"
    if rock in SEDIMENTARY:
        return "cz_sedimentary" if young else "mz_pz_sedimentary"
    raise ValueError(f"unclassified OGDC unit {name!r} ({rock_type!r}, {age!r}, "
                     f"{terrane!r}, {formation!r}) -- extend the rules in geology_ogdc.py")
