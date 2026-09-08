"""
Fetches a station-based "average frost-free period length" climatology
for the Pacific Northwest + southern/central BC domain from NOAA's
GHCN-Daily archive and writes climatology.json: for every qualifying
station, the 1991-2020 average number of days between the last spring
date and the first fall date its daily low temperature drops to <=32F
(0C).

Companion to ../pnw-first-freeze-map/ (same domain, same station
discovery, same GHCN-Daily/NCEI Access Data Service approach -- see that
project's module docstring and README for why GHCN-Daily specifically,
not ACIS or a gridded product). The difference is what's measured: that
project's first-fall-freeze date alone; this one, the length of the
freeze-free season between spring and fall -- which needs each year's
*last spring* freeze too, so this script fetches full calendar years
(Jan 1 - Dec 31) rather than July-December only.

USAGE
-----
    python fetch_climatology.py                    # full PNW+BC domain
    python fetch_climatology.py --min-years 25      # stricter completeness
    python fetch_climatology.py --output data.json

METHODOLOGY
-----------
- Domain and station discovery: identical to
  ../pnw-first-freeze-map/fetch_climatology.py (same bbox, same TMIN
  inventory prefilter).
- Daily TMIN: same NCEI Access Data Service batching approach as the
  sibling map, but the full 1991-01-01..2020-12-31 continuous range
  (rather than starting July 1) so every year's January-June is
  available for the spring side of the season, not just discarded.
- Per station, per year: the LAST date on or before June 30 whose TMIN
  is <=32F ("last spring freeze") and the FIRST date on or after July 1
  whose TMIN is <=32F ("first fall freeze") -- July 1 is the same
  spring/fall boundary the sibling map uses. If both are found that
  year, that year's frost-free length is the exact number of days
  between them (plain `date` subtraction, so leap years are handled
  automatically -- no manual day-of-year offset math needed, since unlike
  the sibling map this script never needs to *average a calendar date*
  across years, only a day *count*).
- A station is kept only if at least MIN_YEARS_DEFAULT of the 30
  candidate years produced a qualifying frost-free length (both a spring
  and a fall freeze that year). Mean and median frost-free days are both
  recorded; build_map.py plots the mean.
- Caveat inherited from the sibling map's July 1 spring/fall boundary: a
  station where freezing conditions persist past June 30 (e.g. high
  mountain sites) will have its spring search cut off at that boundary,
  and an early-July freeze there gets counted as *that year's fall
  freeze* instead -- "frost-free period" isn't a very meaningful concept
  at a site like that to begin with, so this isn't treated as a special
  case, just inherited as-is from the sibling map's convention.
"""
import argparse
import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests

STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

# Same domain as ../pnw-first-freeze-map/ and ../dew-point-storm-map/.
LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2

START_YEAR, END_YEAR = 1991, 2020
FREEZE_THRESHOLD_F = 32.0

# Loose prefilter on GHCN's own inventory firstyear/lastyear -- same as
# ../pnw-first-freeze-map/fetch_climatology.py.
INVENTORY_FIRSTYEAR_MAX = 1995
INVENTORY_LASTYEAR_MIN = 2018

MIN_YEARS_DEFAULT = 20

GHCN_BATCH_SIZE = 50
MAX_WORKERS = 4
REQUEST_TIMEOUT_S = 120
MAX_RETRIES = 3

HEADERS = {"User-Agent": "ingalls-weather-scripts/pnw-frost-free-days-map (contact: weather.ingalls@gmail.com)"}


def fetch_text(url):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    r.raise_for_status()
    return r.text


def load_candidate_stations():
    """Stations inside the domain bbox with a TMIN inventory span that
    plausibly overlaps 1991-2020. Returns {id: {lat, lon, elev_m, name}}."""
    print("Fetching GHCN-Daily station list...")
    stations = {}
    for line in fetch_text(STATIONS_URL).splitlines():
        if not line.strip():
            continue
        sid = line[0:11].strip()
        lat = float(line[12:20])
        lon = float(line[21:30])
        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            stations[sid] = {
                "lat": lat,
                "lon": lon,
                "elev_m": float(line[31:37]),
                "name": line[41:71].strip(),
            }

    print(f"  {len(stations)} station(s) inside the domain bbox.")
    print("Fetching GHCN-Daily inventory (filtering to TMIN coverage of 1991-2020)...")
    candidates = {}
    for line in fetch_text(INVENTORY_URL).splitlines():
        if not line.strip():
            continue
        sid = line[0:11].strip()
        if sid not in stations or sid in candidates:
            continue
        if line[31:35].strip() != "TMIN":
            continue
        firstyear, lastyear = int(line[36:40]), int(line[41:45])
        if firstyear <= INVENTORY_FIRSTYEAR_MAX and lastyear >= INVENTORY_LASTYEAR_MIN:
            candidates[sid] = stations[sid]

    print(f"  {len(candidates)} candidate station(s) with plausible TMIN coverage.")
    return candidates


def fetch_batch_tmin(station_ids):
    """TMIN readings (whole degrees F, per units=standard) for one batch
    of station IDs across the full START_YEAR-END_YEAR span. Returns
    {station_id: {year: [(date, tmin_f), ...]}}."""
    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(station_ids),
        "startDate": f"{START_YEAR}-01-01",
        "endDate": f"{END_YEAR}-12-31",
        "dataTypes": "TMIN",
        "format": "csv",
        "includeStationName": "false",
        "includeStationLocation": "false",
        "includeAttributes": "false",
        "units": "standard",
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(DATA_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * attempt)
    else:
        print(f"  WARNING: batch of {len(station_ids)} station(s) failed after {MAX_RETRIES} attempts: {last_err}")
        return {}

    out = {}
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        tmin_raw = (row.get("TMIN") or "").strip()
        if not tmin_raw:
            continue
        d = date.fromisoformat(row["DATE"])
        out.setdefault(row["STATION"], {}).setdefault(d.year, []).append((d, int(tmin_raw)))
    return out


def frost_free_days_per_year(year_readings):
    """{year: [(date, tmin_f), ...]} -> {year: frost_free_days} for years
    with both a last-spring (<=Jun 30) and first-fall (>=Jul 1) freeze."""
    result = {}
    for year, readings in year_readings.items():
        readings.sort()
        spring_last = None
        fall_first = None
        for d, tmin_f in readings:
            if tmin_f > FREEZE_THRESHOLD_F:
                continue
            if d.month <= 6:
                spring_last = d  # keep overwriting -- last match wins
            elif fall_first is None:
                fall_first = d  # first match in Jul-Dec wins
        if spring_last is not None and fall_first is not None:
            result[year] = (fall_first - spring_last).days
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-years", type=int, default=MIN_YEARS_DEFAULT,
                     help=f"Minimum qualifying years of {END_YEAR - START_YEAR + 1} required to keep a station "
                          f"(default: {MIN_YEARS_DEFAULT}).")
    ap.add_argument("--output", default="climatology.json")
    args = ap.parse_args()

    candidates = load_candidate_stations()
    candidate_ids = list(candidates)
    batches = [candidate_ids[i:i + GHCN_BATCH_SIZE] for i in range(0, len(candidate_ids), GHCN_BATCH_SIZE)]

    print(f"Fetching {START_YEAR}-01-01..{END_YEAR}-12-31 TMIN for {len(candidate_ids)} station(s) "
          f"in {len(batches)} batch(es) of up to {GHCN_BATCH_SIZE}...")
    raw = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_batch_tmin, batch): i for i, batch in enumerate(batches)}
        done = 0
        for fut in as_completed(futures):
            raw.update(fut.result())
            done += 1
            print(f"  batch {done}/{len(batches)} done ({len(raw)} station(s) with data so far)")

    stations_out = []
    dropped_thin = 0
    for sid, meta in candidates.items():
        year_readings = raw.get(sid)
        if not year_readings:
            dropped_thin += 1
            continue
        per_year = frost_free_days_per_year(year_readings)
        if len(per_year) < args.min_years:
            dropped_thin += 1
            continue
        values = sorted(per_year.values())
        n = len(values)
        mean_days = sum(values) / n
        median_days = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        stations_out.append({
            "id": sid,
            "name": meta["name"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "elev_m": meta["elev_m"],
            "n_years": n,
            "mean_frost_free_days": round(mean_days, 1),
            "median_frost_free_days": round(median_days, 1),
        })

    out = {
        "source": "NOAA GHCN-Daily, element TMIN (element data via NCEI Access Data Service)",
        "domain": {"lon_min": LON_MIN, "lon_max": LON_MAX, "lat_min": LAT_MIN, "lat_max": LAT_MAX},
        "period": f"{START_YEAR}-{END_YEAR}",
        "freeze_threshold_f": FREEZE_THRESHOLD_F,
        "min_years_required": args.min_years,
        "n_candidate_stations": len(candidates),
        "n_stations_kept": len(stations_out),
        "stations": stations_out,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {args.output}: {len(stations_out)} station(s) kept "
          f"({dropped_thin} dropped for <{args.min_years} qualifying years or no data) "
          f"of {len(candidates)} candidates.")
    if stations_out:
        shortest = min(stations_out, key=lambda s: s["mean_frost_free_days"])
        longest = max(stations_out, key=lambda s: s["mean_frost_free_days"])
        print(f"  Shortest average frost-free period: {shortest['name']} ({shortest['id']}) "
              f"-- {shortest['mean_frost_free_days']:.0f} days")
        print(f"  Longest average frost-free period:  {longest['name']} ({longest['id']}) "
              f"-- {longest['mean_frost_free_days']:.0f} days")
