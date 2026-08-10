# GLM Lightning Maps -- 5-Day Rolling Archive

A 5-day rolling archive of full-Pacific-day lightning summaries, one map
per region per day: Columbia Basin, Portland Metro, Pacific Northwest,
and BC Interior -- same domains as
[`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/)
(24h) and
[`../columbia-basin-lightning-realtime-map/`](../columbia-basin-lightning-realtime-map/)
(2h), sourced from the same GOES-18 GLM instrument.

For each region, five images are kept at all times: `<region>_lightning_
day1.png` (yesterday) through `<region>_lightning_day5.png` (5 days ago).
Each night, shortly after midnight Pacific, the previous day's data is
fetched and rendered into the Day-1 slot -- and the old Day-1 through
Day-4 images shift to Day-2 through Day-5, with whatever was in Day-5
dropped.

## Files

- `fetch_lightning.py` -- pulls a full Pacific-time calendar day of
  GLM-L2-LCFA flash detections (defaults to yesterday) out of NOAA's
  public `noaa-goes18` bucket on AWS Open Data, over a domain spanning
  all four regions, and writes `lightning_daily.json`. `--pt-date
  YYYY-MM-DD` picks a specific day instead (useful for backfilling or
  testing). See `../columbia-basin-lightning-map/README.md` for the
  fuller write-up of the data source and satellite choice.
- `build_map.py` -- same `REGIONS`-dict pattern as the other two
  lightning projects (same four regions, same basemap/roads/city-label
  handling, same border/offshore-line fixes), but each region's dict key
  is `output_base` (e.g. `"columbia_basin_lightning"`) rather than a
  fixed `output` filename -- the day-slot number isn't decided by
  `build_map.py` itself, only by `deploy/publish_daily.py`'s rotation
  logic (see below). No age bands: a full archived day has no
  meaningful "how recent" axis the way the 2h/24h maps do, so every
  flash is plotted in a single color (`FLASH_COLOR`). Title shows the
  calendar date the data covers, converted from `window_start` (a UTC
  instant) into each region's own `timezone` (default
  `America/Los_Angeles`; `bc_interior` uses `America/Vancouver`) --
  numerically identical to Pacific time for any date since 2007, so this
  doesn't change the rendered label today, but it's the correct source of
  truth per region going forward. The fetch window itself stays one
  shared UTC range across all four regions (see `fetch_lightning.py`).
- `deploy/publish_daily.py` -- cron entry point; owns the whole rotate
  -> fetch -> render -> publish sequence. See "Rotation" below for the
  mechanism and why it's safe on a first run with no prior images.
- `deploy/crontab.example` -- **hourly**, not "once right after
  midnight" -- see "Scheduling" below for why.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).
- `basemap_cache/` -- not committed, gitignored, and needs no manual setup
  -- caches the static land/countries/states/counties/roads layer per
  region as a raster PNG so a normal run doesn't re-render it from vector
  data every time (a ~45-60s cost otherwise). Self-invalidating; see
  "Basemap raster caching" under `../columbia-basin-lightning-map/README.md`
  Notes for the full write-up -- identical mechanism here.

## Rotation

`publish_daily.py`'s `rotate_region()`, run once per region before that
region's new Day-1 is rendered:

```python
for i in range(5, 1, -1):          # i = 5, 4, 3, 2 -- in that order
    src = f"{output_base}_day{i-1}.png"
    dst = f"{output_base}_day{i}.png"
    if os.path.exists(src):
        os.replace(src, dst)       # overwrites dst -- this is how the old Day-5 gets dropped
```

Processing `i` **descending** (5 before 4 before 3 before 2) is what
makes this correct: each step moves the *older* slot into the *next*
slot before that older slot's own source has been touched by an earlier
step. Do it ascending instead and Day-1's fresh-that-morning content
would already be sitting in the Day-2 slot by the time the Day-2 -> Day-3
step runs, corrupting the whole window. After the loop, the Day-1 slot is
always empty, ready for the night's fresh render.

**First run** (no `day1`-`day5` files exist yet) needs no special-casing
at all: every `if os.path.exists(src)` check is simply false, so the loop
is a no-op, and only Day-1 gets created from yesterday's data -- exactly
"pull yesterday's data only" with zero extra code.

Verified directly (not just by inspection) with synthetic marker files
standing in for each day's image, tracing exactly which marker ends up in
which slot after one rotation pass -- confirms old Day-1 -> Day-2 -> ... ->
Day-5 -> dropped, in that order, with nothing duplicated or skipped.

## Scheduling

Rather than a UTC cron time tuned to land "shortly after midnight
Pacific" (which would need DST-aware adjustment twice a year to stay
correct), `publish_daily.py` is **idempotent per Pacific calendar date**:
it records the PT date it last completed a rotation for in
`state/last_rotation_date.txt`, and no-ops immediately if today's PT date
is already marked done. `deploy/crontab.example` runs the script
**hourly** -- whichever hourly tick is the first to land after midnight
PT does that day's rotation+fetch+render (a few minutes of real work),
and every other tick that day is a near-instant no-op. This sidesteps
DST entirely: the idempotency check itself is computed in Pacific time,
not UTC, so it's correct year-round without touching the cron schedule.

A region that fails mid-run (fetch or render error) is logged and left
with its previous Day-1-through-Day-5 images untouched for that region --
but the date is still marked as handled overall, so a partial failure
doesn't cause the *other*, successful regions to re-rotate on every
remaining tick that day (which would corrupt their windows by rotating
more than once per calendar day).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                                    # first time / fresh environment only
python3 fetch_lightning.py                       # pull yesterday (PT) -- all 4 regions read this
python3 fetch_lightning.py --pt-date 2026-07-16   # ... or a specific past day
python3 build_map.py --region columbia_basin      # renders <output_base>_day1.png directly, for testing
```

For the real rotate-and-publish flow (what cron actually runs), use
`deploy/publish_daily.py` instead of calling `fetch_lightning.py`/
`build_map.py` directly -- it's the only thing that manages the 5-day
window and the WEB_ROOT-published filenames.

## Notes

- **`WEB_ROOT` publishing, not local output**: unlike the other two
  lightning projects (which write next to the repo checkout by default,
  for easy local testing), `publish_daily.py` always writes straight to
  `/var/www/images/` -- there's no meaningful "local" 5-day archive to
  keep, since the whole point is the rolling window on the live site.
  `build_map.py`'s direct CLI form still writes locally (to whatever
  `--output` you pass, defaulting to `<output_base>_day1.png`) for quick
  manual testing of a single render.
- **`state/` is gitignored**, same as every other deploy guard in this
  repo -- `run.lock`, `publish.log`, and critically
  `last_rotation_date.txt`, which is server-side runtime state, not
  source. Deleting it manually just means the next tick treats it as
  "not yet rotated today" and does one (harmless, if it's genuinely a new
  day; a real problem only if you delete it mid-day and want to avoid a
  second rotation until tomorrow).
