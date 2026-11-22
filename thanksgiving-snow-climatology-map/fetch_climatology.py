"""
Fetches every Thanksgiving Day's snowfall and snow depth for every ACIS
station (the same backend behind xmacis.rcc-acis.org) inside the map's
bounding box -- WA/OR/ID plus the visible parts of BC, AB, MT, WY, UT,
NV, and CA, so the grid extends past the WA/OR/ID borders --
across the full period of record, and writes output/thanksgiving_snow.json:
one entry per station with its location, elevation, and per-year snowfall
(inches) and snow depth (inches) on that year's Thanksgiving.

One ACIS MultiStnData call per year (the whole bbox at once, both
elements), so a full 1890-present pull is ~135 requests, run in a small
thread pool; takes several minutes. No API key required. Canadian
stations come through ACIS's GHCN-Daily feed (ECCC and CoCoRaHS-Canada
sites), so coverage north of the border is thinner than in the US.

The per-station "% of Thanksgivings with snow" is computed in build_map.py
rather than here, so the threshold / metric / minimum-years settings can
change without re-fetching.

Thanksgiving date (US, by year) -- see thanksgiving_date():
  - 1942-present: 4th Thursday of November (Congress, 1941).
  - 1939-1941: Roosevelt's "Franksgiving" -- the second-to-last Thursday
    of November, the federal date (roughly half of states, Idaho among
    them, kept the old last-Thursday date instead; the federal date is
    used here for all three states for consistency).
  - Before 1939: the last Thursday of November (Lincoln's 1863
    proclamation, followed by every president through 1938).

Data-quality note: COOP observers typically read their gauges once a day
around 7 AM local, and ACIS assigns that reading to the observation date.
So a COOP "Thanksgiving" value is really the 24 hours ending Thanksgiving
morning, not midnight-to-midnight. First-order (ASOS/airport) stations are
true calendar-day values. That's the standard caveat for any COOP-based
day-of climatology -- worth knowing, not worth correcting.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests

BASE_URL = "https://data.rcc-acis.org/MultiStnData"
# Map frame (build_map.py's LON/LAT_MIN/MAX) padded by its GRID_PAD_DEG,
# so stations just outside the frame still inform the grid at its edges.
BBOX = (-126.0, 40.45, -109.7, 50.25)  # lon_min, lat_min, lon_max, lat_max

FIRST_YEAR = 1890  # ACIS's daily COOP record in WA/OR/ID starts in the early 1890s

THIS_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = THIS_DIR / "output" / "thanksgiving_snow.json"


def thanksgiving_date(year):
    """US Thanksgiving for a given year (see module docstring)."""
    nov1 = date(year, 11, 1)
    first_thu = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
    thursdays = [first_thu + timedelta(weeks=i) for i in range(5) if (first_thu + timedelta(weeks=i)).month == 11]
    if year >= 1942:
        return thursdays[3]
    if 1939 <= year <= 1941:
        return thursdays[-2]
    return thursdays[-1]


def parse_inches(v):
    """ACIS value -> float inches. 'T' (trace) -> 0.0 (not measurable),
    'M' / 'S' (missing / subsequent-accumulated) / anything else -> None.
    ACIS may also append a flag letter to a number (e.g. '1.0A' =
    accumulated over multiple days), which is treated as missing since it
    doesn't pin the value to Thanksgiving itself."""
    if v == "T":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_year(year):
    day = thanksgiving_date(year).isoformat()
    params = {"bbox": ",".join(str(v) for v in BBOX), "sdate": day, "edate": day, "elems": "snow,snwd",
              "meta": "uid,name,state,ll,elev,sids"}
    for attempt in range(4):
        try:
            r = requests.post(BASE_URL, data={"params": json.dumps(params)}, timeout=120)
            r.raise_for_status()
            return year, day, r.json().get("data", [])
        except requests.RequestException:
            if attempt == 3:
                raise


def main():
    parser = argparse.ArgumentParser(description="Fetch Pacific Northwest Thanksgiving snow history from ACIS.")
    parser.add_argument("--first-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--last-year", type=int, default=None,
                        help="Last Thanksgiving to include (default: the most recent one already past).")
    args = parser.parse_args()

    today = date.today()
    last_year = args.last_year or (today.year if thanksgiving_date(today.year) < today else today.year - 1)
    years = list(range(args.first_year, last_year + 1))

    stations = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for year, day, rows in pool.map(fetch_year, years):
            n = 0
            for row in rows:
                meta = row["meta"]
                if "ll" not in meta:
                    continue
                snow, snwd = (parse_inches(v) for v in row["data"])
                if snow is None and snwd is None:
                    continue
                uid = str(meta["uid"])
                stn = stations.setdefault(uid, {
                    "name": meta.get("name", ""), "state": meta.get("state", ""),
                    "lon": meta["ll"][0], "lat": meta["ll"][1], "elev_ft": meta.get("elev"),
                    "sids": meta.get("sids", []), "years": {},
                })
                stn["years"][str(year)] = {"date": day, "snow": snow, "snwd": snwd}
                n += 1
            print(f"{day}: {n} stations reporting")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"first_year": years[0], "last_year": years[-1], "bbox": BBOX,
                   "stations": stations}, f)
    print(f"Wrote {len(stations)} stations, {years[0]}-{years[-1]}, to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
