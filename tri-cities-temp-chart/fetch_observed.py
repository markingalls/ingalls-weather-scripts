"""
Fetches the last N days of observed daily high temperature from ACIS (the
same backend behind xmacis.rcc-acis.org) for a station and writes
observed.json. No API key required.

Defaults to KPSC (Tri-Cities Airport, Pasco, WA) via ACIS station id
"KPSC 5" (the ICAO-code identifier type for that station -- ACIS also
knows it as "PSC 3", WBAN "24163 1", or GHCN "USW00024163 6", all
interchangeable).
"""
import argparse
import json
from datetime import date, timedelta

import requests

BASE_URL = "https://data.rcc-acis.org/StnData"

DEFAULT_SID = "KPSC 5"
DEFAULT_STATION = "KPSC"
DEFAULT_LABEL = "Pasco, WA"


def fetch(sid, sdate, edate):
    params = {"sid": sid, "sdate": sdate.isoformat(), "edate": edate.isoformat(), "elems": "maxt"}
    r = requests.get(BASE_URL, params={"params": json.dumps(params)}, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", default=DEFAULT_SID, help='ACIS station id, e.g. "KPSC 5"')
    ap.add_argument("--station", default=DEFAULT_STATION, help="Short station identifier shown in the chart title, e.g. KPSC")
    ap.add_argument("--label", default=DEFAULT_LABEL, help="Human-readable location, e.g. 'Pasco, WA'")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--end-date", default=None,
                     help="YYYY-MM-DD, defaults to yesterday (today's high is usually still incomplete)")
    ap.add_argument("--output", default="observed.json")
    args = ap.parse_args()

    end = date.fromisoformat(args.end_date) if args.end_date else date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)

    resp = fetch(args.sid, start, end)
    days = []
    for d, v in resp.get("data", []):
        days.append({"date": d, "maxt_f": None if v == "M" else float(v)})

    out = {
        "source": "ACIS (xmACIS) StnData, element maxt",
        "sid": args.sid,
        "station": args.station,
        "label": args.label,
        "days": days,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    n_missing = sum(1 for d in days if d["maxt_f"] is None)
    print(f"Saved {args.output}: {len(days)} days ({start} .. {end}) for {args.station}"
          + (f", {n_missing} missing" if n_missing else ""))
