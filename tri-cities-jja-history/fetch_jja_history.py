"""
Fetches Tri-Cities daily high temperature departure from normal (element
`maxt`, NCEI 1991-2020 mean normal, and observed-minus-normal departure --
see tri-cities-jja-calendar/fetch_jja_highs.py for why ACIS's `normal`
flag gives this directly, no client-side percentile math needed) across
several years of JJA, and writes jja_history.json: for each year, the
average daily-high departure for June, July, August, and the full JJA
season, plus each year's raw (not departure) JJA mean high, and the
constant 1991-2020 JJA mean high itself (`normal_mean_high`) -- together
what build_trend_chart.py plots as a long-term line chart, alongside
build_history_grid.py's year x month departure grid.

One ACIS StnData call spans the whole start-year..end-year range (ACIS
doesn't mind the non-summer months coming back too; they're just filtered
out client-side), rather than one call per year.

Defaults to KPSC (Tri-Cities Airport, Pasco, WA), 2019 through the most
recently *completed* JJA (see tri-cities-jja-calendar/fetch_jja_highs.py's
same default_year logic).
"""
import argparse
import json
from datetime import date

import requests

BASE_URL = "https://data.rcc-acis.org/StnData"

DEFAULT_SID = "KPSC 5"
DEFAULT_STATION = "KPSC"
DEFAULT_LABEL = "Pasco, WA"
DEFAULT_START_YEAR = 2019

NORMALS_PERIOD = "1991-2020"
MONTHS = [6, 7, 8]


def default_end_year(today):
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
    r = requests.get(BASE_URL, params={"params": json.dumps(params)}, timeout=60)
    r.raise_for_status()
    return r.json()


def mean(values):
    return sum(values) / len(values) if values else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", default=DEFAULT_SID, help='ACIS station id, e.g. "KPSC 5"')
    ap.add_argument("--station", default=DEFAULT_STATION, help="Short station identifier shown in the graphic title, e.g. KPSC")
    ap.add_argument("--label", default=DEFAULT_LABEL, help="Human-readable location, e.g. 'Pasco, WA'")
    ap.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    ap.add_argument("--end-year", type=int, default=None, help="defaults to the most recently completed JJA")
    ap.add_argument("--output", default="jja_history.json")
    args = ap.parse_args()

    end_year = args.end_year if args.end_year else default_end_year(date.today())
    start_year = args.start_year

    resp = fetch(args.sid, date(start_year, 6, 1), date(end_year, 8, 31))

    # departures_by_year[year][month] = [daily departures in that month];
    # maxt_by_year[year] = [raw daily highs across JJA]; normal_by_day
    # (unique calendar day -> normal high) since a calendar day's normal is
    # the same every year -- collecting it once per unique day, rather than
    # once per year, means the mean below isn't biased by which years
    # happen to have more/fewer missing days.
    departures_by_year = {y: {m: [] for m in MONTHS} for y in range(start_year, end_year + 1)}
    maxt_by_year = {y: [] for y in range(start_year, end_year + 1)}
    normal_by_day = {}
    for d, maxt, normal, departure in resp.get("data", []):
        y, m = int(d[:4]), int(d[5:7])
        if m not in MONTHS or y not in departures_by_year:
            continue
        if departure != "M":
            departures_by_year[y][m].append(float(departure))
        if maxt != "M":
            maxt_by_year[y].append(float(maxt))
        if normal != "M":
            normal_by_day[d[5:]] = float(normal)

    years = {}
    for y in range(start_year, end_year + 1):
        by_month = departures_by_year[y]
        season_deps = [dep for m in MONTHS for dep in by_month[m]]
        years[str(y)] = {
            "june": mean(by_month[6]),
            "july": mean(by_month[7]),
            "august": mean(by_month[8]),
            "season": mean(season_deps),
            "maxt_mean": mean(maxt_by_year[y]),
            "n_days": len(season_deps),
        }

    out = {
        "source": f"ACIS (xmACIS) StnData, element maxt + NCEI {NORMALS_PERIOD} mean normal & departure",
        "sid": args.sid,
        "station": args.station,
        "label": args.label,
        "start_year": start_year,
        "end_year": end_year,
        "normals_period": NORMALS_PERIOD,
        "normal_mean_high": mean(list(normal_by_day.values())),
        "years": years,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {args.output}: {start_year}-{end_year} for {args.station}")
    for y, v in years.items():
        print(f"  {y}: Jun {v['june']:+.1f}  Jul {v['july']:+.1f}  Aug {v['august']:+.1f}  Season {v['season']:+.1f}  ({v['n_days']} days)")
