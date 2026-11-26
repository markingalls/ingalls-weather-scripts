"""
Rotation track finder -- waypoints for a storm-following loop
Ingalls Weather

Follows a velocity couplet through the lowest-tilt velocity sweeps and
prints a --waypoints string for build_loop.py. Give it a rough first
guess of the storm's path (two points are enough, e.g. a warning's
"storm location + motion" extrapolated back); each sweep is searched for
the strongest azimuthal shear within --radius-km of that guess.

  python3 rotation_track.py --site KATX \\
      --start 2026-11-26T17:20Z --end 2026-11-26T20:40Z \\
      --guess "2026-11-26T17:36Z,47.133,-123.399;2026-11-26T19:52Z,47.503,-122.024"

Uses (and fills) the same output/cache/ as build_loop.py, so the loop
render afterwards doesn't re-download anything. Read the per-sweep log
before trusting the result: a detection far off the guess, or with weak
shear, is usually a different feature. Hand-edit the waypoints if needed.
"""

import argparse
from multiprocessing import Pool

import numpy as np
from scipy.ndimage import uniform_filter

import build_loop as B

# Detections weaker than this (1/s, after smoothing) aren't used as
# waypoints -- typical background shear in a broad band runs 2-5e-3.
MIN_SHEAR = 5e-3


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--guess", required=True,
                    help="'ISO,lat,lon;ISO,lat,lon;...' rough path (extrapolated)")
    ap.add_argument("--radius-km", type=float, default=15)
    ap.add_argument("--every-min", type=float, default=8,
                    help="waypoint spacing in the printed string")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    start = B.parse_time(args.start, None)
    end = B.parse_time(args.end, None)
    guess = B.SmoothTrack(B.parse_waypoints(args.guess))
    import os
    os.makedirs(B.CACHE_DIR, exist_ok=True)
    scans = B.list_scans(args.site.upper(), start, end)
    with Pool(args.workers) as pool:
        swept = pool.map(B.fetch_sweeps, [(k, "vel", True) for _, k in scans])
    sweeps = sorted(x for vol in swept for x in vol if start <= x[0] <= end)

    hits = []
    for t, path in sweeps:
        s = B.load_sweep(path)
        v = s["data"] / B.MS_TO_KT
        order = np.argsort(s["az"])
        v, az = v[order], s["az"][order]
        r = s["first_gate"] + np.arange(v.shape[1]) * s["gate_width"]
        # Azimuthal shear across ~1 deg (two super-res radials).
        sh = (np.roll(v, -2, axis=0) - v) / (r[None, :] * np.radians(1.0) * 1000)
        sh = uniform_filter(np.where(np.isfinite(sh), sh, 0), size=(3, 5))
        rr = np.broadcast_to(r[None, :], sh.shape)
        aa = np.broadcast_to(az[:, None], sh.shape)
        lon, lat, _ = B.geod.fwd(np.full(sh.shape, s["lon"]), np.full(sh.shape, s["lat"]),
                                 aa, rr * 1000)
        gl, go, _ = guess.at(t)
        _, _, d = B.geod.inv(np.full(sh.shape, go), np.full(sh.shape, gl), lon, lat)
        x = np.where(d < args.radius_km * 1000, np.abs(sh), 0)
        i, j = np.unravel_index(np.argmax(x), x.shape)
        ok = x[i, j] >= MIN_SHEAR
        print(f"{t:%H:%M:%S}  shear {x[i, j] * 1000:5.1f}e-3/s at {lat[i, j]:.3f},{lon[i, j]:.3f}"
              f"  ({d[i, j] / 1000:4.1f} km off guess){'' if ok else '  -- weak, skipped'}")
        if ok:
            hits.append((t, float(lat[i, j]), float(lon[i, j])))

    # Thin to about one waypoint per --every-min; build_loop's spline
    # smooths whatever jitter is left.
    pts, last = [], None
    for t, la, lo in hits:
        if last is None or (t - last).total_seconds() >= args.every_min * 60:
            pts.append(f"{t:%Y-%m-%dT%H:%MZ},{la:.3f},{lo:.3f}")
            last = t
    print("\n--waypoints \"" + ";".join(pts) + "\"")


if __name__ == "__main__":
    main()
