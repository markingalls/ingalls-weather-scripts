# WM-6 Ensemble Surface Low Landfall Map

One-off, Instagram-portrait (4:5, 1728x2160) map of a Pacific surface low
coming ashore in the Pacific Northwest, built from all 128 members of
WindBorne's WeatherMesh-6 global ensemble:

- **Thin blue lines**: each member's own surface-low track, from its own
  MSLP field, every 3 hours, ending where it crosses the coast.
- **Bold line**: the ensemble mean track. If the members' landfall points
  split into two real groups, you get a northern and a southern
  **cluster mean** instead (see *Clustering* below).
- **Colored coastline**: the chance the low's center makes landfall
  within 100 km of each point on the outer coast. This is the share of
  *all* 128 members, so members whose low fills offshore count as "no".
  Only coast above 2% is highlighted, and only towns above 2% get a
  callout.

The projection is the same `NearsidePerspective` satellite view
(4,000 km height) as
[`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/),
centered on this domain. Land uses that map's soft warm gray (`#e3e1da`),
so the coast band is the only warm color. Country and state borders come
from `admin0`/`admin1_boundary_lines.json`, clipped to land. Unclipped,
they draw maritime boundaries across the water, such as the US/Canada
line down the Strait of Juan de Fuca.

Defaults are set for the low that comes ashore Thursday night into Friday
morning, 2026-09-25. Point it at another system with `--start`, `--end`,
and `--seed`.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
export WB_API_KEY=...
python build_map.py                 # latest WM-6 run, default window/seed
python build_map.py --start 2026-09-24T06 --end 2026-09-26T06   # UTC
python build_map.py --seed 42 -134.5                            # lat lon
python build_map.py --file output/snapshot_20260923_22.npz      # no re-fetch
```

The fetch takes about 30 seconds: 17 steps, about 2 MB each. All steps
come from a single WM-6 run, the latest complete one per
`run_information`. That keeps the window from straddling two runs, since
WM-6 updates hourly.

## Data source: reading members out of the archive

The gridded endpoint doesn't serve member fields as a per-variable subset.
`variable=all` + `as_url=true` returns a presigned URL to that forecast
hour's full zarr zip, which is several GB. `members/pressure_msl` inside
it is one ~170 MB zarr v3 shard, `128 x 720 x 1440`, with
`sharding_indexed` 128 x 45 x 45 inner chunks (11.25 deg tiles).
`fetch_member_mslp()`:

1. reads the zip's central directory with `remotezip`, and checks that the
   shard entry is STORED (uncompressed), so byte offsets inside it can be
   addressed;
2. range-reads the shard index off the end of the entry (one
   `(offset, nbytes)` pair per inner chunk, plus a crc32c);
3. range-reads just the six tiles that overlap the map, and decodes each
   one with `numcodecs.Blosc`.

The member grid uses the file's own 0.25 deg `latitude`/`longitude` arrays.
Latitude runs 90 → -89.75. Longitude runs 0 → 179.75, then -180 → -0.25,
so it's compared mod 360. These arrays are read from the file rather than
assumed. As a check, the mean of the 128 members matched
`ensemble_mean/pressure_msl` to 0.003 hPa.

`--file` snapshots store MSLP as int16 hundredths of a hPa above 900 hPa
(~30 MB). They're gitignored.

## Method

**Seed.** The track starts at the deepest ensemble-mean MSLP inside
`SEED_BOX` at `--start`, unless `--seed` is given. Each member starts
from its own nearest closed center within 400 km of that point.

**Tracking** (`track_member()`). Each member's field gets a light Gaussian
smoothing. A *closed center* is a local minimum over +/-0.75 deg that sits
at least 0.5 hPa below the ~6 deg mean around it. Each step takes the
center nearest a first guess (the last position plus the last step's
motion) within 300 km. It deliberately doesn't take the deepest nearby
minimum, because that jumps tracks onto the parent low to the north.

**Landfall.** Landfall is the first crossing of the *outer coast* line,
with the time interpolated along the 3-hour step. A low that loses its
closed center within 50 km of the coast counts as landfall at the
nearest coast point, because it's filling as it comes ashore. The outer
coast (`build_outer_coast()`) is built by scanning each latitude from the
west for the first land, then taking a running westernmost value and a
running mean. This closes off the Strait of Juan de Fuca, Grays Harbor,
and the Columbia mouth. Without it, a low entering the strait would
"land" near Seattle, and Puget Sound would light up on the probability
band.

**Clustering** (`cluster_landfalls()`). Clusters are drawn only when
landfall latitude is genuinely bimodal. A 2-component Gaussian mixture has
to beat a single Gaussian by at least 10 BIC, with its components
separated by Ashman's D >= 2 and the smaller one holding at least 15% of
landfalling members. Otherwise the map shows one mean track. For the
2026-09-23 22z run the test failed (BIC gain -14, D 1.0), so it's a
single mean track. The spread is one broad mode, not two scenarios.

**Mean track** (`mean_track()`). This is the mean member position at each
step, until the mean position itself crosses the coast. After a member
comes ashore, it keeps moving along its last step's motion. That stops
the mean from stalling or lurching as the first members stop at the
coast, which would put a kink in the mean track.

**Smoothing.** Member tracks get 1-2-1 smoothing of their interior points,
with the start and landfall points fixed. This removes the grid-cell
zig-zags that come from finding centers on the 0.25 deg grid.

## Files

- `build_map.py`: fetch, tracking, and rendering. The domain, tracker
  thresholds, color table, and callout towns are all constants near the
  top.
- `requirements.txt` / `setup.sh`: same dependencies as
  `../tpw-wm6-ensemble-map/`, plus `numcodecs` (already a zarr
  dependency), which is used directly for the Blosc decode.

The basemap layers come from [`../maps/`](../maps/). The logo and the
Baloo 2 font for the "L" come from [`../assets/`](../assets/). Output PNGs
and snapshots are written to `output/`.
