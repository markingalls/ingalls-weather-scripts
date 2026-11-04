"""
Fetches Pacific Northwest snowpack (snow water equivalent, SWE) from
automated snow-pillow stations via the NRCS Air and Water Database (AWDB)
REST API -- NRCS SNOTEL in the U.S. states, and the BC River Forecast
Centre's automated snow weather stations in British Columbia, which AWDB
also carries (network code MSNT) -- and
writes snowpack.json: a regional daily SWE series for the current water
year (Oct 1 .. the most recent day reported) plus the full-season
(Oct 1 .. Sep 30) NRCS daily-median curve to plot it against. No API key
required.

AWDB calls cover every automated station in the requested states/
provinces (default WA, OR, ID, BC) via a "*:<STATE>:<NETWORK>" wildcard
triplet -- SNTL for U.S. states, MSNT for BC (see NETWORK_BY_STATE):

  1. The NRCS daily median (AWDB's centralTendencyType=MEDIAN -- the
     1991-2020 normals) for every calendar day of the year. AWDB only
     returns a central tendency alongside a date that actually has an
     observed value, so a future date in the current water year comes
     back empty, and so does any day a station was down. To get a full
     season's curve this reads the "median" field from several completed
     reference water years (default WY2024, WY2023, WY2025 -- WY2024
     includes Feb 29) and merges them, first year to have a given
     calendar day wins. The medians are the same normals whichever year
     they're read from; merging just papers over station outages, which
     are common at the BC stations. A Feb 29 still missing after that is
     filled with the mean of Feb 28 and Mar 1.
  2. The current water year's observed daily SWE, Oct 1 .. today.

Regional aggregation (see README Notes for the reasoning):

  - The station set is fixed to stations that have a median for every
    calendar day (stations too new to have normals drop out here), so the median curve is one consistent set of
    sites all season.
  - The regional median curve is the mean of those stations' daily
    medians.
  - On each observed day, percent of median is
    sum(observed) / sum(median) across only the stations that actually
    reported that day (NRCS's own "same stations on both sides" index
    method), and the plotted regional SWE is that ratio times the regional
    median curve -- so a few stations dropping out on a given day doesn't
    make the line jump.
  - The series is truncated to the most recent day on which at least
    MIN_REPORTING_FRACTION of the station set reported, so a partially
    ingested "today" doesn't drag the last point down.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

BASE_URL = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data"

DEFAULT_STATES = ["WA", "OR", "ID", "BC"]

# AWDB network code for each region's automated snow-pillow stations.
# U.S. states use NRCS SNOTEL; BC's automated snow weather stations (run by
# the BC River Forecast Centre) are carried in AWDB under MSNT. BC's manual
# snow courses (network SNOW) are monthly, not daily, so they're left out.
NETWORK_BY_STATE = {"BC": "MSNT"}
DEFAULT_NETWORK = "SNTL"
DEFAULT_LABEL = "Pacific Northwest"

# Completed water years to read the daily medians from, merged in order
# (see module docstring). WY2024 goes first because it includes Feb 29.
DEFAULT_REFERENCE_WYS = [2024, 2023, 2025]

NORMALS_PERIOD = "1991-2020"

# Drop a trailing day from the observed series unless at least this
# fraction of the station set has reported it (today's values often post
# station by station through the morning).
MIN_REPORTING_FRACTION = 0.5

# Below this regional-median SWE (inches) -- early October, late summer --
# a percent-of-median is a ratio of near-zeros and is meaningless, so the
# plotted value falls back to the plain mean of reporting stations.
MIN_MEDIAN_FOR_RATIO_IN = 0.05


def water_year_for(d):
    """Water year N runs Oct 1 of N-1 .. Sep 30 of N."""
    return d.year + 1 if d.month >= 10 else d.year


def awdb_daily_swe(states, begin, end, with_median):
    params = {
        "stationTriplets": ",".join(f"*:{s}:{NETWORK_BY_STATE.get(s, DEFAULT_NETWORK)}" for s in states),
        "elements": "WTEQ",
        "duration": "DAILY",
        "beginDate": begin.isoformat(),
        "endDate": end.isoformat(),
    }
    if with_median:
        params["centralTendencyType"] = "MEDIAN"
    r = requests.get(BASE_URL, params=params, timeout=300)
    r.raise_for_status()
    return r.json()


def merge_normals(resps):
    """{triplet: {"MM-DD": median_in}}, merged across reference-year
    responses (first response to have a given calendar day wins)."""
    out = {}
    for resp in resps:
        for stn in resp:
            if not stn.get("data"):
                continue
            medians = out.setdefault(stn["stationTriplet"], {})
            for v in stn["data"][0].get("values", []):
                if v.get("median") is not None:
                    medians.setdefault(v["date"][5:10], float(v["median"]))
    for medians in out.values():
        if "02-29" not in medians and "02-28" in medians and "03-01" in medians:
            medians["02-29"] = round((medians["02-28"] + medians["03-01"]) / 2, 2)
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
                    help="State/province codes whose stations to pool, e.g. WA OR ID BC")
    ap.add_argument("--label", default=DEFAULT_LABEL, help="Region name shown in the chart title")
    ap.add_argument("--end-date", default=None, help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--reference-wys", type=int, nargs="+", default=DEFAULT_REFERENCE_WYS,
                    help="Completed water years to read the daily medians from, merged in order")
    ap.add_argument("--output", default="snowpack.json")
    args = ap.parse_args()

    states = [s.upper() for s in args.states]
    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    wy = water_year_for(end)
    wy_start = date(wy - 1, 10, 1)

    # All the AWDB calls are independent and slow (~1 min each), so run
    # them concurrently.
    ref_wys = ", ".join(f"WY{y}" for y in args.reference_wys)
    print(f"Fetching daily medians ({NORMALS_PERIOD}; reference {ref_wys}) and WY{wy} observed SWE "
          f"({wy_start} .. {end}) for {', '.join(states)}...")
    with ThreadPoolExecutor(max_workers=len(args.reference_wys) + 1) as ex:
        ref_futures = [ex.submit(awdb_daily_swe, states, date(y - 1, 10, 1), date(y, 9, 30), True)
                       for y in args.reference_wys]
        obs_future = ex.submit(awdb_daily_swe, states, wy_start, end, False)
        normals = merge_normals([f.result() for f in ref_futures])
        observed = parse_observed(obs_future.result())

    n_all = len(normals)
    normals = {t: m for t, m in normals.items() if len(m) >= 366}
    stations = sorted(normals)
    by_state = {}
    for t in stations:
        st = t.split(":")[1]
        by_state[st] = by_state.get(st, 0) + 1
    print(f"  {len(stations)} of {n_all} stations have a median for every calendar day: "
          + ", ".join(f"{st} {by_state.get(st, 0)}" for st in states))

    # Full-season regional median curve.
    median_curve = []
    for d in season_dates(wy):
        md = d.isoformat()[5:]
        vals = [normals[t][md] for t in stations if md in normals[t]]
        if not vals:
            continue
        median_curve.append({"date": d.isoformat(), "median_swe_in": round(sum(vals) / len(vals), 2)})
    median_by_date = {row["date"]: row["median_swe_in"] for row in median_curve}

    # Observed regional series, Oct 1 .. end.
    obs_days = []
    d = wy_start
    while d <= end:
        ds, md = d.isoformat(), d.isoformat()[5:]
        reporting = [t for t in stations if ds in observed.get(t, {}) and md in normals[t]]
        row = {"date": ds, "n_reporting": len(reporting), "swe_in": None, "pct_of_median": None}
        if reporting and ds in median_by_date:
            cur_sum = sum(observed[t][ds] for t in reporting)
            median_sum = sum(normals[t][md] for t in reporting)
            cur_mean, median_mean = cur_sum / len(reporting), median_sum / len(reporting)
            if median_mean >= MIN_MEDIAN_FOR_RATIO_IN:
                ratio = cur_sum / median_sum
                row["pct_of_median"] = round(100 * ratio, 1)
                row["swe_in"] = round(ratio * median_by_date[ds], 2)
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

    peak = max(median_curve, key=lambda r: r["median_swe_in"])
    out = {
        "source": ("NRCS AWDB REST API, element WTEQ (daily snow water equivalent): "
                   "NRCS SNOTEL (U.S.) + BC River Forecast Centre automated snow weather stations"),
        "label": args.label,
        "states": states,
        "water_year": wy,
        "normals_period": NORMALS_PERIOD,
        "normals_statistic": "median",
        "normals_reference_wys": args.reference_wys,
        "n_stations": len(stations),
        "stations_by_state": {st: by_state.get(st, 0) for st in states},
        "latest_date": obs_days[-1]["date"],
        "median_peak": {"date": peak["date"], "median_swe_in": peak["median_swe_in"]},
        "median": median_curve,
        "observed": obs_days,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    last = obs_days[-1]
    pct = f", {last['pct_of_median']:.0f}% of median" if last["pct_of_median"] is not None else ""
    print(f"Saved {args.output}: WY{wy} through {last['date']} -- regional SWE {last['swe_in']:.1f}\""
          f"{pct} ({last['n_reporting']}/{len(stations)} stations reporting)")
