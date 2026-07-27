"""
Fetches Tri-Cities (KPSC) daily-high climatology from ACIS (the same
backend behind xmacis.rcc-acis.org) and writes climatology.json: for every
calendar day of the year --

  - P10 / P25 / P50 / P75 / P90 percentiles of daily high temperature,
    computed client-side from the raw multi-year daily series. ACIS has no
    precomputed percentile-of-distribution element (its "normal" flag only
    exposes NCEI's mean-based normals, and its "pct_xx_yyy" reduce code is
    a threshold-exceedance count, not a statistical percentile) -- so this
    pulls the full period-of-record daily maxt series in one call and
    computes percentiles per (month, day) in Python. P50 (the median) is
    what the chart plots as the "daily normal" line -- sampled from the
    same raw series as the other percentiles, rather than NCEI's separate
    smoothed-mean normals product, so the whole climatology backdrop (band
    edges and the normal line alike) comes from one consistent sample.
  - The record high + record year per calendar day, via ACIS's own
    groupby=year period-of-record reduction (one call, no client-side scan
    needed).

No API key required. This has nothing to do with the current forecast run,
so it only needs re-running if you change station.

Data-quality note: for KPSC specifically, ACIS's raw daily maxt series has
large historical gaps (essentially no data 1947-1997), so both the
percentiles and the "period of record" used for record highs are
effectively drawn from ~1998-present, not the station's full nominal
period of record -- see README.
"""
import argparse
import json

import numpy as np
import requests

BASE_URL = "https://data.rcc-acis.org/StnData"
DEFAULT_SID = "KPSC 5"

# Skip percentiles for a calendar day if fewer than this many years of raw
# data are available for it (keeps thin/noisy samples, e.g. a data-poor
# Feb 29, from producing a misleadingly precise-looking band).
MIN_YEARS_FOR_PERCENTILE = 5


def acis_query(params):
    r = requests.get(BASE_URL, params={"params": json.dumps(params)}, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_raw_series(sid):
    """Full period-of-record daily maxt series, grouped by (month, day)
    across all years, for client-side percentiles."""
    data = acis_query({"sid": sid, "sdate": "por", "edate": "por", "elems": "maxt"})["data"]
    by_day = {}
    years_seen = set()
    for date_str, v in data:
        if v == "M":
            continue
        by_day.setdefault(date_str[5:], []).append(float(v))
        years_seen.add(date_str[:4])
    return by_day, years_seen


def fetch_records(sid):
    """Per-calendar-day record high + year, via ACIS's own period-of-record
    reduction (see docs example "period of record maximum temperatures and
    date of occurrence for every day of the year")."""
    resp = acis_query({
        "sid": sid, "sdate": "por", "edate": "por",
        "elems": [{"name": "maxt", "interval": [0, 0, 1], "duration": 1,
                   "smry": {"reduce": "max", "add": "date"},
                   "smry_only": 1, "groupby": "year"}],
    })
    out = {}
    for value, date_str in resp["smry"][0]:
        if value == "M":
            continue
        out[date_str[5:]] = {"record_f": float(value), "record_year": int(date_str[:4])}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", default=DEFAULT_SID, help='ACIS station id, e.g. "KPSC 5"')
    ap.add_argument("--output", default="climatology.json")
    args = ap.parse_args()

    print("Fetching full period-of-record daily series (for percentiles)...")
    raw_by_day, years_seen = fetch_raw_series(args.sid)
    print("Fetching per-calendar-day record highs...")
    records = fetch_records(args.sid)

    days = {}
    thin_days = []
    for month_day, values in raw_by_day.items():
        entry = {"n_years": len(values)}
        if len(values) >= MIN_YEARS_FOR_PERCENTILE:
            entry.update({
                "p10": round(float(np.percentile(values, 10)), 1),
                "p25": round(float(np.percentile(values, 25)), 1),
                "p50": round(float(np.percentile(values, 50)), 1),
                "p75": round(float(np.percentile(values, 75)), 1),
                "p90": round(float(np.percentile(values, 90)), 1),
            })
        else:
            thin_days.append(month_day)
        if month_day in records:
            entry.update(records[month_day])
        days[month_day] = entry

    year_list = sorted(years_seen)
    out = {
        "source": "ACIS (xmACIS) StnData, element maxt",
        "sid": args.sid,
        "percentile_years": f"{year_list[0]}-{year_list[-1]}" if year_list else None,
        "n_percentile_years": len(year_list),
        "record_note": ("Record highs reflect ACIS's period-of-record maximum for this "
                         "station, which has large historical gaps -- treat as a record "
                         "for the years actually on file (see percentile_years), not "
                         "necessarily the true all-time record."),
        "days": days,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    msg = (f"Saved {args.output}: {len(days)} calendar days, "
           f"{len(year_list)} years of raw data ({out['percentile_years']})")
    if thin_days:
        msg += f"; {len(thin_days)} day(s) skipped percentiles (<{MIN_YEARS_FOR_PERCENTILE} years)"
    print(msg)
