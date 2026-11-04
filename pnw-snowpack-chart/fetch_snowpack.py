"""
Fetches Pacific Northwest snowpack (snow water equivalent, SWE) from the
NRCS SNOTEL network via the NRCS Air and Water Database (AWDB) REST API and
writes snowpack.json: a regional daily SWE series for the current water
year (Oct 1 .. the most recent day reported) plus the full-season
(Oct 1 .. Sep 30) NRCS daily-average curve to plot it against. No API key
required.

Two AWDB calls, both covering every SNOTEL station in the requested states
(default WA, OR, ID) via a "*:<STATE>:SNTL" wildcard triplet:

  1. The NRCS daily average (AWDB's centralTendencyType=AVERAGE -- NRCS's
     1991-2020 normals) for every calendar day of the year. AWDB only
     returns central tendencies alongside dates that actually have data,
     so a future date in the current water year comes back empty -- to
     get the full season's curve this pulls a completed reference water
     year instead (default WY2024, which includes Feb 29, so every
     calendar day is covered) and keeps just its per-day "average" field.
  2. The current water year's observed daily SWE, Oct 1 .. today.

Regional aggregation (see README Notes for the reasoning):

  - The station set is fixed to stations that have an NRCS average for
    every calendar day, so the average curve is one consistent set of
    sites all season.
  - The regional average curve is the mean of those stations' daily
    averages.
  - On each observed day, percent of average is
    sum(observed) / sum(average) across only the stations that actually
    reported that day (NRCS's own "same stations on both sides" index
    method), and the plotted regional SWE is that ratio times the regional
    average curve -- so a few stations dropping out on a given day doesn't
    make the line jump.
  - The series is truncated to the most recent day on which at least
    MIN_REPORTING_FRACTION of the station set reported, so a partially
    ingested "today" doesn't drag the last point down.
"""
import argparse
import json
from datetime import date, timedelta

import requests

BASE_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"

DEFAULT_STATES = ["WA", "OR", "ID"]
DEFAULT_LABEL = "Pacific Northwest"

# A completed water year containing Feb 29, so the normals cover all 366
# calendar days. Any completed water year works -- the "average" values are
# the same 1991-2020 normals regardless -- this one just covers leap day.
DEFAULT_REFERENCE_WY = 2024

NORMALS_PERIOD = "1991-2020"

# Drop a trailing day from the observed series unless at least this
# fraction of the station set has reported it (today's values often post
# station by station through the morning).
MIN_REPORTING_FRACTION = 0.5

# Below this regional-average SWE (inches) -- early October, late summer --
# a percent-of-average is a ratio of near-zeros and is meaningless, so the
# plotted value falls back to the plain mean of reporting stations.
MIN_AVG_FOR_RATIO_IN = 0.05


def water_year_for(d):
    """Water year N runs Oct 1 of N-1 .. Sep 30 of N."""
    return d.year + 1 if d.month >= 10 else d.year


def awdb_daily_swe(states, begin, end, with_average):
    params = {
        "stationTriplets": ",".join(f"*:{s}:SNTL" for s in states),
        "elements": "WTEQ",
        "duration": "DAILY",
        "beginDate": begin.isoformat(),
        "endDate": end.isoformat(),
    }
    if with_average:
        params["centralTendencyType"] = "AVERAGE"
    r = requests.get(BASE_URL, params=params, timeout=300)
    r.raise_for_status()
    return r.json()


def parse_normals(resp):
    """{triplet: {"MM-DD": average_in}} for stations with an average on
    every calendar day of the reference year."""
    out = {}
    for stn in resp:
        if not stn.get("data"):
            continue
        avgs = {}
        for v in stn["data"][0].get("values", []):
            if v.get("average") is not None:
                avgs[v["date"][5:10]] = float(v["average"])
        out[stn["stationTriplet"]] = avgs
    return out


def parse_observed(resp):
    """{triplet: {"YYYY-MM-DD": swe_in}}."""
    out = {}
    for stn in resp:
        if not stn.get("data"):
            continue
        vals = {}
        for v in stn["data"][0].get("values", []):
            if v.get("value") is not None:
                vals[v["date"][:10]] = float(v["value"])
        out[stn["stationTriplet"]] = vals
    return out


def season_dates(wy):
    d, end = date(wy - 1, 10, 1), date(wy, 9, 30)
    while d <= end:
        yield d
        d += timedelta(days=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--states", nargs="+", default=DEFAULT_STATES,
                    help="State codes whose SNOTEL stations to pool, e.g. WA OR ID")
    ap.add_argument("--label", default=DEFAULT_LABEL, help="Region name shown in the chart title")
    ap.add_argument("--end-date", default=None, help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--reference-wy", type=int, default=DEFAULT_REFERENCE_WY,
                    help="Completed water year to read the daily averages from")
    ap.add_argument("--output", default="snowpack.json")
    args = ap.parse_args()

    states = [s.upper() for s in args.states]
    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    wy = water_year_for(end)
    wy_start = date(wy - 1, 10, 1)

    print(f"Fetching NRCS daily averages ({NORMALS_PERIOD}) for SNOTEL in {', '.join(states)} "
          f"(reference WY{args.reference_wy})...")
    ref_start, ref_end = date(args.reference_wy - 1, 10, 1), date(args.reference_wy, 9, 30)
    normals = parse_normals(awdb_daily_swe(states, ref_start, ref_end, with_average=True))
    n_ref_days = (ref_end - ref_start).days + 1
    normals = {t: a for t, a in normals.items() if len(a) >= n_ref_days}
    stations = sorted(normals)
    print(f"  {len(stations)} stations with a full year of daily averages")

    print(f"Fetching WY{wy} observed SWE ({wy_start} .. {end})...")
    observed = parse_observed(awdb_daily_swe(states, wy_start, end, with_average=False))

    # Full-season regional average curve.
    average_curve = []
    for d in season_dates(wy):
        md = d.isoformat()[5:]
        vals = [normals[t][md] for t in stations if md in normals[t]]
        if not vals:  # Feb 29 in a non-leap reference year -- shouldn't happen with WY2024
            continue
        average_curve.append({"date": d.isoformat(), "avg_swe_in": round(sum(vals) / len(vals), 2)})
    avg_by_date = {row["date"]: row["avg_swe_in"] for row in average_curve}

    # Observed regional series, Oct 1 .. end.
    obs_days = []
    d = wy_start
    while d <= end:
        ds, md = d.isoformat(), d.isoformat()[5:]
        reporting = [t for t in stations if ds in observed.get(t, {}) and md in normals[t]]
        row = {"date": ds, "n_reporting": len(reporting), "swe_in": None, "pct_of_avg": None}
        if reporting and ds in avg_by_date:
            cur_sum = sum(observed[t][ds] for t in reporting)
            avg_sum = sum(normals[t][md] for t in reporting)
            cur_mean, avg_mean = cur_sum / len(reporting), avg_sum / len(reporting)
            if avg_mean >= MIN_AVG_FOR_RATIO_IN:
                ratio = cur_sum / avg_sum
                row["pct_of_avg"] = round(100 * ratio, 1)
                row["swe_in"] = round(ratio * avg_by_date[ds], 2)
            else:
                row["swe_in"] = round(cur_mean, 2)
        obs_days.append(row)
        d += timedelta(days=1)

    # Truncate to the most recent sufficiently-reported day.
    min_reporting = MIN_REPORTING_FRACTION * len(stations)
    while obs_days and (obs_days[-1]["swe_in"] is None or obs_days[-1]["n_reporting"] < min_reporting):
        dropped = obs_days.pop()
        print(f"  dropping {dropped['date']}: only {dropped['n_reporting']}/{len(stations)} stations reported")
    if not obs_days:
        raise SystemExit("No sufficiently-reported observed days -- nothing to plot.")

    peak = max(average_curve, key=lambda r: r["avg_swe_in"])
    out = {
        "source": "NRCS AWDB REST API, SNOTEL element WTEQ (daily snow water equivalent)",
        "label": args.label,
        "states": states,
        "water_year": wy,
        "normals_period": NORMALS_PERIOD,
        "normals_statistic": "average",
        "normals_reference_wy": args.reference_wy,
        "n_stations": len(stations),
        "latest_date": obs_days[-1]["date"],
        "average_peak": {"date": peak["date"], "avg_swe_in": peak["avg_swe_in"]},
        "average": average_curve,
        "observed": obs_days,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    last = obs_days[-1]
    pct = f", {last['pct_of_avg']:.0f}% of average" if last["pct_of_avg"] is not None else ""
    print(f"Saved {args.output}: WY{wy} through {last['date']} -- regional SWE {last['swe_in']:.1f}\""
          f"{pct} ({last['n_reporting']}/{len(stations)} stations reporting)")
