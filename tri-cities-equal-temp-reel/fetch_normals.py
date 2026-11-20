"""
Fetches 1991-2020 NCEI daily climate normals for one station from ACIS
(the backend behind xmacis.rcc-acis.org) and writes normals.json: one
smoothed normal value per calendar day (365 days, Feb 29 dropped).

Uses ACIS's `normal: "1"` flag, which exposes NCEI's official smoothed
daily normals -- deliberately NOT client-side percentiles of the raw
series like tri-cities-temp-chart does. KPSC's raw daily data is missing
1991-1997, and a raw per-day average over ~23 years is noisy enough that
the "same temperature" periods would fragment into speckle; NCEI's normals
are smoothed and gap-filled, so each temperature maps to clean arcs of
the year (the whole point of the graphic).

No API key required. Only needs re-running if you change station/element.
"""
import argparse
import json

import requests

BASE_URL = "https://data.rcc-acis.org/StnData"
ELEMENT_LABELS = {
    "avgt": "average temperature",
    "maxt": "high temperature",
    "mint": "low temperature",
}


def parse_args():
    ap = argparse.ArgumentParser(description="Fetch NCEI 1991-2020 daily normals via ACIS.")
    ap.add_argument("--sid", default="KPSC 5", help="ACIS station id (default: KPSC 5, Tri-Cities Airport)")
    ap.add_argument("--label", default="Tri-Cities", help="Place name for the graphic's title")
    ap.add_argument("--station-label", default="Pasco / Tri-Cities Airport, Washington",
                    help="Station name as shown in the graphic's subtitle "
                         "(ACIS's own name is all-caps and unpunctuated)")
    ap.add_argument("--element", default="avgt", choices=sorted(ELEMENT_LABELS),
                    help="avgt (daily mean, default), maxt (highs) or mint (lows)")
    ap.add_argument("--output", default="normals.json")
    return ap.parse_args()


def main():
    args = parse_args()
    # Any non-leap year works -- normals are the same every year; 2010 just
    # gives a clean 365-day calendar.
    params = {"sid": args.sid, "sdate": "2010-01-01", "edate": "2010-12-31",
              "elems": [{"name": args.element, "normal": "1"}], "meta": "name,ll,sids"}
    r = requests.get(BASE_URL, params={"params": json.dumps(params)}, timeout=60)
    r.raise_for_status()
    resp = r.json()
    if "error" in resp:
        raise SystemExit(f"ACIS error: {resp['error']}")

    days = []
    for date_str, v in resp["data"]:
        if v in ("M", "", None):
            raise SystemExit(f"missing normal for {date_str} -- station may lack NCEI normals")
        days.append({"md": date_str[5:], "normal_f": float(v)})

    meta = resp["meta"]
    lon, lat = meta["ll"]
    out = {
        "station_name": meta["name"],
        "station_label": args.station_label,
        "sid": args.sid,
        "label": args.label,
        "lat": lat, "lon": lon,
        "element": args.element,
        "element_label": ELEMENT_LABELS[args.element],
        "period": "1991-2020",
        "source": "NCEI 1991-2020 daily normals via ACIS",
        "annual_mean_f": round(sum(d["normal_f"] for d in days) / len(days), 2),
        "days": days,
    }
    json.dump(out, open(args.output, "w"), indent=1)
    vals = [d["normal_f"] for d in days]
    print(f"{meta['name']}: {args.element} normals {min(vals):.1f}..{max(vals):.1f}°F, "
          f"annual mean {out['annual_mean_f']:.2f}°F -> {args.output}")


if __name__ == "__main__":
    main()
