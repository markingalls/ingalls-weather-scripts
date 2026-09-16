"""
Fetches daily high temperature for June-July-August (JJA, meteorological
summer) at a station from ACIS (the same backend behind
xmacis.rcc-acis.org) -- observed maxt, the NCEI 1991-2020 mean daily
normal, and the departure from that normal -- and writes jja_highs.json.
No API key required.

Defaults to KPSC (Tri-Cities Airport, Pasco, WA) and the most recently
*completed* JJA: the current year once September has started, otherwise
last year (this JJA's own year, mid-season, would still be missing its
back half).

ACIS's "normal" element flag (unlike its percentile/threshold reduce
codes -- see tri-cities-temp-chart/fetch_climatology.py for why those
don't give a usable percentile distribution) exposes NCEI's own
mean-based daily normal directly, and a "departure" flag that returns
observed-minus-normal already computed server-side -- both requested
here in the same call as the raw maxt column, so there's no need to
separately fetch and difference a climatology series.
"""
import argparse
import json
from datetime import date

import requests

BASE_URL = "https://data.rcc-acis.org/StnData"

DEFAULT_SID = "KPSC 5"
DEFAULT_STATION = "KPSC"
DEFAULT_LABEL = "Pasco, WA"

NORMALS_PERIOD = "1991-2020"


def default_year(today):
    """Most recently completed JJA: this year once Sept has started
    (JJA is over), else last year (this year's JJA isn't over yet)."""
    return today.year if today >= date(today.year, 9, 1) else today.year - 1


def fetch(sid, sdate, edate):
    params = {
        "sid": sid,
        "sdate": sdate.isoformat(),
        "edate": edate.isoformat(),
        "elems": [
            {"name": "maxt"},
            {"name": "maxt", "normal": "1"},
            {"name": "maxt", "normal": "departure"},
        ],
    }
    r = requests.get(BASE_URL, params={"params": json.dumps(params)}, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", default=DEFAULT_SID, help='ACIS station id, e.g. "KPSC 5"')
    ap.add_argument("--station", default=DEFAULT_STATION, help="Short station identifier shown in the calendar title, e.g. KPSC")
    ap.add_argument("--label", default=DEFAULT_LABEL, help="Human-readable location, e.g. 'Pasco, WA'")
    ap.add_argument("--year", type=int, default=None, help="JJA year, defaults to the most recently completed summer")
    ap.add_argument("--output", default="jja_highs.json")
    args = ap.parse_args()

    year = args.year if args.year else default_year(date.today())
    sdate, edate = date(year, 6, 1), date(year, 8, 31)

    resp = fetch(args.sid, sdate, edate)
    days = []
    for d, maxt, normal, departure in resp.get("data", []):
        days.append({
            "date": d,
            "maxt_f": None if maxt == "M" else float(maxt),
            "normal_f": None if normal == "M" else float(normal),
            "departure_f": None if departure == "M" else float(departure),
        })

    out = {
        "source": f"ACIS (xmACIS) StnData, element maxt + NCEI {NORMALS_PERIOD} mean normal & departure",
        "sid": args.sid,
        "station": args.station,
        "label": args.label,
        "year": year,
        "normals_period": NORMALS_PERIOD,
        "days": days,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    n_missing = sum(1 for d in days if d["maxt_f"] is None)
    print(f"Saved {args.output}: {len(days)} days (JJA {year}) for {args.station}"
          + (f", {n_missing} missing" if n_missing else ""))
