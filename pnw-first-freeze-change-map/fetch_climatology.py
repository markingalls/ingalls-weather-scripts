"""
Fetches a station-based "first fall freeze, then vs. now" comparison for
the Pacific Northwest + southern/central BC domain from NOAA's GHCN-Daily
archive and writes climatology_change.json: for every qualifying station
-- one with a long enough continuous record to cover both windows -- the
average day its daily low temperature first drops to <=32F (0C) after
July 1, computed separately for 1961-1975 and 2006-2020, plus the change
in days between them.

Companion to ../pnw-first-freeze-map/ (same domain, same freeze
definition, same GHCN-Daily source and NCEI Access Data Service
fetching approach -- see that project's README for why GHCN-Daily rather
than ACIS or a gridded product). This script differs in three ways:

  - Two 15-year windows instead of one 30-year window, fetched and
    scored independently per station.
  - A much stricter station filter: a station needs a real TMIN record
    on *both ends* of a ~60-year span, not just somewhere in 1991-2020,
    which drops the candidate pool from ~1,400 to ~550 -- long-running
    COOP stations tend to survive this filter; newer ASOS/AWOS airport
    automation generally doesn't. See the module docstring in
    ../pnw-first-freeze-map/fetch_climatology.py for the shared
    request-batching/date-range mechanics.
  - The output is a per-station *change* in days, not an absolute date,
    since that's what a change map plots.

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

# Same domain as ../pnw-first-freeze-map/ and ../dew-point-storm-map/.
LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2

PERIOD_EARLY = (1961, 1975)
PERIOD_RECENT = (2006, 2020)
FREEZE_THRESHOLD_F = 32.0

# Loose prefilter on GHCN's own inventory firstyear/lastyear -- a station
# needs to plausibly span from before PERIOD_EARLY's start to after
# PERIOD_RECENT's end. Real completeness within each 15-year window is
# checked against actual fetched daily values.
INVENTORY_FIRSTYEAR_MAX = PERIOD_EARLY[0] + 1
INVENTORY_LASTYEAR_MIN = PERIOD_RECENT[1] - 1

# A station needs a qualifying freeze date in at least this many of each
# period's 15 candidate years to be kept for that period; a station is
# only kept overall if it qualifies in *both* periods.
MIN_YEARS_PER_PERIOD_DEFAULT = 10

GHCN_BATCH_SIZE = 50
MAX_WORKERS = 4
REQUEST_TIMEOUT_S = 120
MAX_RETRIES = 3

HEADERS = {"User-Agent": "ingalls-weather-scripts/pnw-first-freeze-change-map (contact: weather.ingalls@gmail.com)"}


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
    of station IDs, restricted to July-December of each candidate year in
    [start_year, end_year]. Returns {station_id: {year: [(offset_days, tmin_f), ...]}}."""
    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(station_ids),
        "startDate": f"{start_year}-07-01",
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
        if d.month < 7:
            continue  # outside the July-December window (see module docstring)
        offset = (d - date(d.year, 7, 1)).days
        out.setdefault(row["STATION"], {}).setdefault(d.year, []).append((offset, int(tmin_raw)))
    return out


def fetch_period(candidate_ids, start_year, end_year, label):
    batches = [candidate_ids[i:i + GHCN_BATCH_SIZE] for i in range(0, len(candidate_ids), GHCN_BATCH_SIZE)]
    print(f"Fetching {label} ({start_year}-07-01..{end_year}-12-31) TMIN for {len(candidate_ids)} "
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


def first_freeze_offsets(year_readings):
    """{year: [(offset, tmin_f), ...]} -> {year: first_freeze_offset_days}
    for years whose readings include a qualifying <=32F crossing."""
    result = {}
    for year, readings in year_readings.items():
        readings.sort()
        for offset, tmin_f in readings:
            if tmin_f <= FREEZE_THRESHOLD_F:
                result[year] = offset
                break
    return result


def period_mean_offset(year_readings, min_years):
    offsets = first_freeze_offsets(year_readings)
    if len(offsets) < min_years:
        return None
    values = list(offsets.values())
    return {"mean_offset_days": sum(values) / len(values), "n_years": len(values)}


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
        early = period_mean_offset(raw_early.get(sid, {}), args.min_years)
        recent = period_mean_offset(raw_recent.get(sid, {}), args.min_years)
        if early is None or recent is None:
            dropped += 1
            continue
        stations_out.append({
            "id": sid,
            "name": meta["name"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "elev_m": meta["elev_m"],
            "early_mean_offset_days": round(early["mean_offset_days"], 2),
            "early_n_years": early["n_years"],
            "recent_mean_offset_days": round(recent["mean_offset_days"], 2),
            "recent_n_years": recent["n_years"],
            "change_days": round(recent["mean_offset_days"] - early["mean_offset_days"], 2),
        })

    out = {
        "source": "NOAA GHCN-Daily, element TMIN (element data via NCEI Access Data Service)",
        "domain": {"lon_min": LON_MIN, "lon_max": LON_MAX, "lat_min": LAT_MIN, "lat_max": LAT_MAX},
        "period_early": f"{PERIOD_EARLY[0]}-{PERIOD_EARLY[1]}",
        "period_recent": f"{PERIOD_RECENT[0]}-{PERIOD_RECENT[1]}",
        "freeze_threshold_f": FREEZE_THRESHOLD_F,
        "min_years_per_period": args.min_years,
        "offset_reference": "days since July 1 of that year",
        "change_reference": "recent period mean offset minus early period mean offset; "
                             "positive = freeze now arrives later in the year than it used to",
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
        later = max(stations_out, key=lambda s: s["change_days"])
        earlier = min(stations_out, key=lambda s: s["change_days"])
        print(f"  Mean change across kept stations: {sum(changes) / len(changes):+.1f} days")
        print(f"  Largest later shift: {later['name']} ({later['id']}) -- {later['change_days']:+.1f} days")
        print(f"  Largest earlier shift: {earlier['name']} ({earlier['id']}) -- {earlier['change_days']:+.1f} days")
