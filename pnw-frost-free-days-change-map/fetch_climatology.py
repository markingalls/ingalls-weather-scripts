"""
Fetches a station-based "frost-free period length, then vs. now" change
for the Pacific Northwest + southern/central BC domain from NOAA's
GHCN-Daily archive and writes climatology_change.json: for every
qualifying station, the average number of days between the last spring
and first fall date its daily low temperature drops to <=32F (0C),
computed separately for 1961-1975 and 2006-2020, plus the change between
them.

Companion to ../pnw-frost-free-days-map/ (same domain, same
last-spring/first-fall methodology) and to
../pnw-first-freeze-change-map/ (same two-period comparison design,
same much-stricter ~60-year-span station filter -- see that project's
module docstring/README for why the candidate pool is far smaller than
the sibling climatology map's). The difference from
../pnw-first-freeze-change-map/ is what's measured: that project's
first-fall-freeze date alone; this one, the freeze-free season length,
which needs full calendar years (Jan 1 - Dec 31) per period rather than
July-December only, so each year's spring side is available too.

USAGE
-----
    python fetch_climatology.py                    # full PNW+BC domain
    python fetch_climatology.py --min-years 8       # looser per-period completeness
    python fetch_climatology.py --output data.json
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

# Same domain as ../pnw-frost-free-days-map/ and ../dew-point-storm-map/.
LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2

PERIOD_EARLY = (1961, 1975)
PERIOD_RECENT = (2006, 2020)
FREEZE_THRESHOLD_F = 32.0

# Same station filter as ../pnw-first-freeze-change-map/: a station needs
# to plausibly span from before PERIOD_EARLY's start to after
# PERIOD_RECENT's end.
INVENTORY_FIRSTYEAR_MAX = PERIOD_EARLY[0] + 1
INVENTORY_LASTYEAR_MIN = PERIOD_RECENT[1] - 1

MIN_YEARS_PER_PERIOD_DEFAULT = 10

GHCN_BATCH_SIZE = 50
MAX_WORKERS = 4
REQUEST_TIMEOUT_S = 120
MAX_RETRIES = 3

HEADERS = {"User-Agent": "ingalls-weather-scripts/pnw-frost-free-days-change-map (contact: weather.ingalls@gmail.com)"}


def fetch_text(url):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    r.raise_for_status()
    return r.text


def load_candidate_stations():
    """Stations inside the domain bbox with a TMIN inventory span that
    plausibly covers both PERIOD_EARLY and PERIOD_RECENT. Returns
    {id: {lat, lon, elev_m, name}}."""
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
    print(f"Fetching GHCN-Daily inventory (filtering to TMIN coverage of "
          f"{PERIOD_EARLY[0]}-{PERIOD_RECENT[1]})...")
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

    print(f"  {len(candidates)} candidate station(s) with plausible TMIN coverage of both periods.")
    return candidates


def fetch_batch_tmin(station_ids, start_year, end_year):
    """TMIN readings (whole degrees F, per units=standard) for one batch
    of station IDs across [start_year, end_year]. Returns
    {station_id: {year: [(date, tmin_f), ...]}}."""
    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(station_ids),
        "startDate": f"{start_year}-01-01",
        "endDate": f"{end_year}-12-31",
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


def fetch_period(candidate_ids, start_year, end_year, label):
    batches = [candidate_ids[i:i + GHCN_BATCH_SIZE] for i in range(0, len(candidate_ids), GHCN_BATCH_SIZE)]
    print(f"Fetching {label} ({start_year}-01-01..{end_year}-12-31) TMIN for {len(candidate_ids)} "
          f"station(s) in {len(batches)} batch(es) of up to {GHCN_BATCH_SIZE}...")
    raw = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(fetch_batch_tmin, batch, start_year, end_year) for batch in batches]
        done = 0
        for fut in as_completed(futures):
            raw.update(fut.result())
            done += 1
            print(f"  [{label}] batch {done}/{len(batches)} done ({len(raw)} station(s) with data so far)")
    return raw


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
                spring_last = d
            elif fall_first is None:
                fall_first = d
        if spring_last is not None and fall_first is not None:
            result[year] = (fall_first - spring_last).days
    return result


def period_mean_days(year_readings, min_years):
    per_year = frost_free_days_per_year(year_readings)
    if len(per_year) < min_years:
        return None
    values = list(per_year.values())
    return {"mean_frost_free_days": sum(values) / len(values), "n_years": len(values)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-years", type=int, default=MIN_YEARS_PER_PERIOD_DEFAULT,
                     help=f"Minimum qualifying years per 15-year period required to keep a station "
                          f"(default: {MIN_YEARS_PER_PERIOD_DEFAULT}).")
    ap.add_argument("--output", default="climatology_change.json")
    args = ap.parse_args()

    candidates = load_candidate_stations()
    candidate_ids = list(candidates)

    raw_early = fetch_period(candidate_ids, *PERIOD_EARLY, label="early")
    raw_recent = fetch_period(candidate_ids, *PERIOD_RECENT, label="recent")

    stations_out = []
    dropped = 0
    for sid, meta in candidates.items():
        early = period_mean_days(raw_early.get(sid, {}), args.min_years)
        recent = period_mean_days(raw_recent.get(sid, {}), args.min_years)
        if early is None or recent is None:
            dropped += 1
            continue
        stations_out.append({
            "id": sid,
            "name": meta["name"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "elev_m": meta["elev_m"],
            "early_mean_frost_free_days": round(early["mean_frost_free_days"], 1),
            "early_n_years": early["n_years"],
            "recent_mean_frost_free_days": round(recent["mean_frost_free_days"], 1),
            "recent_n_years": recent["n_years"],
            "change_days": round(recent["mean_frost_free_days"] - early["mean_frost_free_days"], 1),
        })

    out = {
        "source": "NOAA GHCN-Daily, element TMIN (element data via NCEI Access Data Service)",
        "domain": {"lon_min": LON_MIN, "lon_max": LON_MAX, "lat_min": LAT_MIN, "lat_max": LAT_MAX},
        "period_early": f"{PERIOD_EARLY[0]}-{PERIOD_EARLY[1]}",
        "period_recent": f"{PERIOD_RECENT[0]}-{PERIOD_RECENT[1]}",
        "freeze_threshold_f": FREEZE_THRESHOLD_F,
        "min_years_per_period": args.min_years,
        "change_reference": "recent period mean frost-free days minus early period mean frost-free days; "
                             "positive = the frost-free season is now longer than it used to be",
        "n_candidate_stations": len(candidates),
        "n_stations_kept": len(stations_out),
        "stations": stations_out,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {args.output}: {len(stations_out)} station(s) kept "
          f"({dropped} dropped for <{args.min_years} qualifying years in one or both periods) "
          f"of {len(candidates)} candidates.")
    if stations_out:
        changes = [s["change_days"] for s in stations_out]
        longer = max(stations_out, key=lambda s: s["change_days"])
        shorter = min(stations_out, key=lambda s: s["change_days"])
        print(f"  Mean change across kept stations: {sum(changes) / len(changes):+.1f} days")
        print(f"  Largest lengthening: {longer['name']} ({longer['id']}) -- {longer['change_days']:+.1f} days")
        print(f"  Largest shortening:  {shorter['name']} ({shorter['id']}) -- {shorter['change_days']:+.1f} days")
