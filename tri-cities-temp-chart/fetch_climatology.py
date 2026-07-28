"""
Fetches Tri-Cities daily-high climatology from ACIS (the same backend
behind xmacis.rcc-acis.org) and writes climatology.json: for every
calendar day of the year --

  - P10 / P25 / P50 / P75 / P90 percentiles of daily high temperature,
    restricted to the 1991-2020 climate normals period and computed
    client-side from KPSC's raw daily series in that window. ACIS has no
    precomputed percentile-of-distribution element (its "normal" flag only
    exposes NCEI's mean-based normals, and its "pct_xx_yyy" reduce code is
    a threshold-exceedance count, not a statistical percentile) -- so this
    pulls KPSC's daily maxt series for 1991-01-01..2020-12-31 in one call
    and computes percentiles per (month, day) in Python. P50 (the median)
    is what the chart plots as the "daily normal" line -- sampled from the
    same 1991-2020 series as the other percentiles, rather than NCEI's
    separate smoothed-mean normals product, so the whole percentile
    backdrop comes from one consistent sample and period.
  - The record high + record year per calendar day, pooled across KPSC and
    the other long-running Tri-Cities-area stations (Kennewick, Richland)
    via ACIS's own groupby=year period-of-record reduction, one call per
    station, then the max across stations per calendar day. Unlike the
    percentiles, this deliberately is NOT restricted to 1991-2020 or to
    KPSC alone -- see the data-quality note below on why.

No API key required. This has nothing to do with the current forecast run,
so it only needs re-running if you change station.

Data-quality note: KPSC's own raw daily data has a large historical gap
(essentially no data 1947-1997), so within the 1991-2020 percentile
window only 1998-2020 (~23 years) actually has data -- percentile_years
in the output reports the real sample, not the nominal 30-year window.
Kennewick (COOP 454154) has a much longer, largely gap-free daily record
back to 1894, and Richland (COOP 457015) back to 1944 -- both a few miles
from KPSC in the same Tri-Cities metro area -- so record highs are pooled
across all three rather than relying on KPSC's comparatively short
history, which would understate true records for many calendar days.
"""
import argparse
import json

import numpy as np
import requests

BASE_URL = "https://data.rcc-acis.org/StnData"
DEFAULT_SID = "KPSC 5"

# Tri-Cities-area stations to pool for record highs (see module docstring).
# KPSC alone only reliably covers ~1998-present; Kennewick and Richland
# fill in the historical depth KPSC's own record lacks.
RECORD_STATIONS = [
    ("KPSC 5", "Pasco Tri-Cities Airport"),
    ("454154 2", "Kennewick"),
    ("457015 2", "Richland"),
]

PERCENTILE_PERIOD = "1991-2020"
PERCENTILE_SDATE = "1991-01-01"
PERCENTILE_EDATE = "2020-12-31"

# Skip percentiles for a calendar day if fewer than this many years of raw
# data are available for it (keeps thin/noisy samples, e.g. a data-poor
# Feb 29, from producing a misleadingly precise-looking band).
MIN_YEARS_FOR_PERCENTILE = 5


def acis_query(params):
    r = requests.get(BASE_URL, params={"params": json.dumps(params)}, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_raw_series(sid, sdate, edate):
    """Daily maxt series for [sdate, edate], grouped by (month, day) across
    years, for client-side percentiles."""
    data = acis_query({"sid": sid, "sdate": sdate, "edate": edate, "elems": "maxt"})["data"]
    by_day = {}
    years_seen = set()
    for date_str, v in data:
        if v == "M":
            continue
        by_day.setdefault(date_str[5:], []).append(float(v))
        years_seen.add(date_str[:4])
    return by_day, years_seen


def fetch_station_records(sid):
    """Per-calendar-day record high + year for one station, via ACIS's own
    period-of-record reduction (see docs example "period of record maximum
    temperatures and date of occurrence for every day of the year")."""
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
        out[date_str[5:]] = (float(value), int(date_str[:4]))
    return out


def fetch_area_records(stations):
    """Record high + year + which station it came from, per calendar day,
    pooled (max) across all `stations`."""
    combined = {}
    for sid, name in stations:
        print(f"  {name} ({sid})...")
        try:
            station_records = fetch_station_records(sid)
        except requests.RequestException as e:
            print(f"  WARNING: record fetch failed for {name} ({sid}): {e}")
            continue
        for month_day, (value, year) in station_records.items():
            best = combined.get(month_day)
            if best is None or value > best[0]:
                combined[month_day] = (value, year, name)
    return combined


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", default=DEFAULT_SID, help='ACIS station id for percentiles, e.g. "KPSC 5"')
    ap.add_argument("--output", default="climatology.json")
    args = ap.parse_args()

    print(f"Fetching {PERCENTILE_PERIOD} daily series (for percentiles)...")
    raw_by_day, years_seen = fetch_raw_series(args.sid, PERCENTILE_SDATE, PERCENTILE_EDATE)
    print("Fetching per-calendar-day record highs across Tri-Cities-area stations:")
    records = fetch_area_records(RECORD_STATIONS)

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
            record_f, record_year, record_station = records[month_day]
            entry["record_f"] = record_f
            entry["record_year"] = record_year
            entry["record_station"] = record_station
        days[month_day] = entry

    year_list = sorted(years_seen)
    out = {
        "source": "ACIS (xmACIS) StnData, element maxt",
        "sid": args.sid,
        "percentile_period": PERCENTILE_PERIOD,
        "percentile_years": f"{year_list[0]}-{year_list[-1]}" if year_list else None,
        "n_percentile_years": len(year_list),
        "record_stations": [name for _, name in RECORD_STATIONS],
        "record_note": (f"Record highs are pooled (max) across {', '.join(n for _, n in RECORD_STATIONS)} "
                         "-- see record_station on each day -- rather than drawn from a single "
                         "station's period of record, which would be far shorter for KPSC alone."),
        "days": days,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    msg = (f"Saved {args.output}: {len(days)} calendar days, "
           f"{len(year_list)} years of {PERCENTILE_PERIOD} percentile data ({out['percentile_years']})")
    if thin_days:
        msg += f"; {len(thin_days)} day(s) skipped percentiles (<{MIN_YEARS_FOR_PERCENTILE} years)"
    print(msg)
