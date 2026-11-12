"""
RRFS low-level wind cross section -- fetcher
Ingalls Weather

Pulls NOAA RRFS (3 km CONUS) pressure-level winds/heights from the surface
up through 700 mb, plus model terrain, surface pressure and 10 m wind, and
samples them along a straight line between two points. Writes
cross_section.json for build_chart.py to render.

Data source: NOMADS (nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod/).
RRFS's old AWS Open Data prefix (noaa-rrfs-pds/rrfs_a/) is empty now that
RRFS is operational, and Herbie's "rrfs" template still points there -- so
this fetches straight from NOMADS, using each file's .idx to byte-range
just the GRIB messages it needs (~45 messages, a few tens of MB) instead of
the full ~700 MB prslev file.

Run selection: by default, the newest RRFS cycle whose prslev file for the
requested valid time is already posted. RRFS runs hourly; every cycle goes
out at least 18h, the synoptic cycles further (to 84h).

USAGE
-----
    python3 fetch_cross_section.py --valid 2026-11-13T02          # newest run covering 02z
    python3 fetch_cross_section.py --valid 2026-11-13T02 --run 2026-11-12T12
    python3 fetch_cross_section.py --start '{"label":"Irrigon","lat":45.8957,"lon":-119.4903}' \\
                                   --end   '{"label":"Tollgate","lat":45.7790,"lon":-118.0870}'
"""

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
import xarray as xr
from scipy.interpolate import griddata

NOMADS = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod"

DEFAULT_START = {"label": "Irrigon", "lat": 45.8957, "lon": -119.4903}
DEFAULT_END = {"label": "Tollgate", "lat": 45.7790, "lon": -118.0870}

# 1000 mb up to 700 mb, every 25 mb (RRFS prslev's native spacing down low).
LEVELS_MB = list(range(1000, 699, -25))

N_SAMPLES = 241  # points along the section (~0.45 km apart over ~110 km)

# Towns near (not necessarily on) the line, labeled along the bottom of the
# chart at their along-section position if they fall within
# TOWN_MAX_OFFSET_KM of it (or their own "max_offset_km"). Listed in label
# priority order: build_chart.py drops a lower-priority label that would
# collide with a higher-priority one (e.g. Adams gives way to Pendleton).
NEARBY_TOWNS = [
    # Pendleton sits ~11 mi south of the line, but it's the area's anchor
    # town, so it gets a wider allowance than the rest.
    {"label": "Pendleton", "lat": 45.6721, "lon": -118.7886, "max_offset_km": 25.0},
    {"label": "Hermiston", "lat": 45.8404, "lon": -119.2895},
    {"label": "Stanfield", "lat": 45.7804, "lon": -119.2164},
    {"label": "Echo", "lat": 45.7426, "lon": -119.1942},
    {"label": "Athena", "lat": 45.8118, "lon": -118.4908},
    {"label": "Weston", "lat": 45.8143, "lon": -118.4233},
    {"label": "Adams", "lat": 45.7671, "lon": -118.5619},
]
TOWN_MAX_OFFSET_KM = 9.0

EARTH_R_KM = 6371.0


def parse_args():
    ap = argparse.ArgumentParser(description="Fetch an RRFS low-level wind cross section.")
    ap.add_argument("--valid", default=None,
                     help="valid time, UTC, YYYY-MM-DDTHH (default: the next 02z)")
    ap.add_argument("--run", default=None, help="RRFS init time, UTC, YYYY-MM-DDTHH (default: newest available)")
    ap.add_argument("--start", default=json.dumps(DEFAULT_START))
    ap.add_argument("--end", default=json.dumps(DEFAULT_END))
    ap.add_argument("--output", default="cross_section.json")
    return ap.parse_args()


def get(url, **kw):
    # NOMADS sends a padded Content-Length header that some HTTP/2 stacks
    # reject outright; requests speaks HTTP/1.1, which is fine.
    # NOMADS also drops the occasional range request mid-body, so retry.
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=120, **kw)
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            if attempt == 4:
                raise
            print(f"    retrying ({e.__class__.__name__})")
            time.sleep(2 * (attempt + 1))


def file_url(run, fhr, kind):
    return (f"{NOMADS}/rrfs.{run:%Y%m%d}/{run:%H}/"
            f"rrfs.t{run:%H}z.{kind}.3km.f{fhr:03d}.conus.grib2")


def idx_available(url):
    try:
        r = requests.head(url + ".idx", timeout=30)
        return r.status_code == 200
    except requests.RequestException:
        return False


def pick_run(valid, run_arg):
    if run_arg:
        run = datetime.strptime(run_arg, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        return run, int((valid - run).total_seconds() // 3600)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for back in range(0, 30):
        run = now - timedelta(hours=back)
        fhr = int((valid - run).total_seconds() // 3600)
        if fhr < 0:
            continue
        if fhr > 84:
            break
        if idx_available(file_url(run, fhr, "prslev")) and idx_available(file_url(run, fhr, "2dfld")):
            return run, fhr
    raise SystemExit("No RRFS run on NOMADS covers that valid time yet.")


def parse_idx(text):
    rows = []
    for line in text.strip().splitlines():
        parts = line.split(":")
        rows.append({"offset": int(parts[1]), "var": parts[3], "level": parts[4]})
    for i, row in enumerate(rows):
        row["end"] = rows[i + 1]["offset"] - 1 if i + 1 < len(rows) else None
    return rows


def fetch_field(url, rows, var, level, workdir):
    """Byte-ranges one GRIB message out of a NOMADS file and decodes it."""
    match = [r for r in rows if r["var"] == var and r["level"] == level]
    if not match:
        raise SystemExit(f"{var}:{level} not in {url}")
    r = match[0]
    rng = f"bytes={r['offset']}-{r['end'] if r['end'] is not None else ''}"
    data = get(url, headers={"Range": rng}).content
    path = os.path.join(workdir, f"{var}_{level.replace(' ', '_')}.grib2")
    with open(path, "wb") as f:
        f.write(data)
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    name = list(ds.data_vars)[0]
    da = ds[name]
    return da


def great_circle_points(a, b, n):
    """n evenly spaced points from a to b along the great circle (fine to
    treat as straight at this ~110 km scale, but this is just as easy)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    d = 2 * np.arcsin(np.sqrt(np.sin((lat2 - lat1) / 2) ** 2 +
                              np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2))
    f = np.linspace(0, 1, n)
    A = np.sin((1 - f) * d) / np.sin(d)
    B = np.sin(f * d) / np.sin(d)
    x = A * np.cos(lat1) * np.cos(lon1) + B * np.cos(lat2) * np.cos(lon2)
    y = A * np.cos(lat1) * np.sin(lon1) + B * np.cos(lat2) * np.sin(lon2)
    z = A * np.sin(lat1) + B * np.sin(lat2)
    lats = np.degrees(np.arctan2(z, np.sqrt(x ** 2 + y ** 2)))
    lons = np.degrees(np.arctan2(y, x))
    return lats, lons, f * d * EARTH_R_KM


def local_xy(lat, lon, lat0, lon0):
    """Equirectangular km offsets -- plenty accurate over ~150 km."""
    x = np.radians(lon - lon0) * EARTH_R_KM * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * EARTH_R_KM
    return x, y


class LineSampler:
    """Linear (Delaunay) interpolation of 2D model fields onto the section
    line, triangulated once on a small box of grid points around it."""

    def __init__(self, grid_lat, grid_lon, lats, lons):
        lon_g = np.where(grid_lon > 180, grid_lon - 360, grid_lon)
        pad = 0.15
        self.mask = ((grid_lat >= lats.min() - pad) & (grid_lat <= lats.max() + pad) &
                     (lon_g >= lons.min() - pad) & (lon_g <= lons.max() + pad))
        lat0, lon0 = lats.mean(), lons.mean()
        gx, gy = local_xy(grid_lat[self.mask], lon_g[self.mask], lat0, lon0)
        self.grid_pts = np.column_stack([gx, gy])
        tx, ty = local_xy(lats, lons, lat0, lon0)
        self.targets = np.column_stack([tx, ty])

    def __call__(self, field):
        return griddata(self.grid_pts, np.asarray(field)[self.mask], self.targets, method="linear")


def earth_relative(u, v, da):
    """RRFS's Lambert conformal GRIB winds are grid-relative (GRIB2
    resolution/component flag bit 5 set). Rotate to true north/east so the
    direction barbs on the chart are real compass directions."""
    if not int(da.attrs.get("GRIB_uvRelativeToGrid", 0)):
        return u, v
    lov = float(da.attrs["GRIB_LoVInDegrees"])
    latin1 = float(da.attrs["GRIB_Latin1InDegrees"])
    latin2 = float(da.attrs["GRIB_Latin2InDegrees"])
    if abs(latin1 - latin2) < 1e-6:
        n = np.sin(np.radians(latin1))
    else:
        l1, l2 = np.radians(latin1), np.radians(latin2)
        n = (np.log(np.cos(l1) / np.cos(l2)) /
             np.log(np.tan(np.pi / 4 + l2 / 2) / np.tan(np.pi / 4 + l1 / 2)))
    lon = da.longitude.values
    dlon = ((lon - lov + 180) % 360) - 180
    ang = np.radians(n * dlon)
    ue = np.cos(ang) * u + np.sin(ang) * v
    ve = -np.sin(ang) * u + np.cos(ang) * v
    return ue, ve


def main():
    args = parse_args()
    start, end = json.loads(args.start), json.loads(args.end)

    if args.valid:
        valid = datetime.strptime(args.valid, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        valid = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if valid <= now:
            valid += timedelta(days=1)

    run, fhr = pick_run(valid, args.run)
    print(f"RRFS {run:%Y-%m-%d %H}z F{fhr:03d} -> valid {valid:%Y-%m-%d %H}z")

    prs_url, sfc_url = file_url(run, fhr, "prslev"), file_url(run, fhr, "2dfld")
    prs_rows = parse_idx(get(prs_url + ".idx").text)
    sfc_rows = parse_idx(get(sfc_url + ".idx").text)

    lats, lons, dist_km = great_circle_points(start, end, N_SAMPLES)

    with tempfile.TemporaryDirectory() as work:
        hgt_sfc = fetch_field(sfc_url, sfc_rows, "HGT", "surface", work)
        sampler = LineSampler(hgt_sfc.latitude.values, hgt_sfc.longitude.values, lats, lons)

        out = {
            "model": "NOAA RRFS (3 km CONUS)",
            "initialization_time": run.strftime("%Y-%m-%dT%H:00Z"),
            "valid_time": valid.strftime("%Y-%m-%dT%H:00Z"),
            "forecast_hour": fhr,
            "start": start,
            "end": end,
            "lat": lats.round(5).tolist(),
            "lon": lons.round(5).tolist(),
            "distance_km": dist_km.round(3).tolist(),
            "surface_height_m": sampler(hgt_sfc.values).round(1).tolist(),
        }
        out["surface_pressure_mb"] = (sampler(fetch_field(sfc_url, sfc_rows, "PRES", "surface", work).values)
                                      / 100).round(2).tolist()
        u10 = fetch_field(sfc_url, sfc_rows, "UGRD", "10 m above ground", work)
        v10 = fetch_field(sfc_url, sfc_rows, "VGRD", "10 m above ground", work)
        ue, ve = earth_relative(u10.values, v10.values, u10)
        out["u10_ms"] = sampler(ue).round(2).tolist()
        out["t2m_c"] = (sampler(fetch_field(sfc_url, sfc_rows, "TMP", "2 m above ground", work).values)
                        - 273.15).round(2).tolist()
        out["v10_ms"] = sampler(ve).round(2).tolist()

        out["levels_mb"] = LEVELS_MB
        out["height_m"], out["u_ms"], out["v_ms"], out["t_c"] = [], [], [], []
        for lev in LEVELS_MB:
            level = f"{lev} mb"
            print(f"  {level}")
            h = fetch_field(prs_url, prs_rows, "HGT", level, work)
            u = fetch_field(prs_url, prs_rows, "UGRD", level, work)
            v = fetch_field(prs_url, prs_rows, "VGRD", level, work)
            ue, ve = earth_relative(u.values, v.values, u)
            t = fetch_field(prs_url, prs_rows, "TMP", level, work)
            out["height_m"].append(sampler(h.values).round(1).tolist())
            out["t_c"].append((sampler(t.values) - 273.15).round(2).tolist())
            out["u_ms"].append(sampler(ue).round(2).tolist())
            out["v_ms"].append(sampler(ve).round(2).tolist())

    # Nearby towns, projected onto the section.
    lat0, lon0 = lats.mean(), lons.mean()
    lx, ly = local_xy(lats, lons, lat0, lon0)
    towns = []
    for t in NEARBY_TOWNS:
        tx, ty = local_xy(np.array(t["lat"]), np.array(t["lon"]), lat0, lon0)
        d = np.hypot(lx - tx, ly - ty)
        i = int(d.argmin())
        if d[i] <= t.get("max_offset_km", TOWN_MAX_OFFSET_KM) and 0 < i < N_SAMPLES - 1:
            towns.append({"label": t["label"], "distance_km": round(float(dist_km[i]), 2)})
    out["towns"] = towns

    with open(args.output, "w") as f:
        json.dump(out, f)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
