# Tropical Storm Elida Moisture Surge → Pacific Northwest Map (one-off)

A one-off styled map tracking the moisture plume moving north out of
(post-)Tropical Storm Elida -- currently churning in the open eastern
Pacific, ~985 mi west of southern Baja California -- toward the Pacific
Northwest: WM-6's (WindBorne WeatherMesh-6) ensemble-mean total
precipitable water (TPW), taken as the max across every forecast step over
the next 10 days -- so each pixel shows the single highest TPW value
forecast to pass over that spot at any point in the window, in inches, not
just on one particular day. Elida itself is forecast to weaken to a
remnant low and dissipate within a few days (NHC, 200 AM PDT Jul 19 2026
advisory); this map tracks where its moisture ends up, not the storm's own
track.

This plots the actual forecast quantity (peak ensemble-mean TPW) rather
than a derived exceedance probability. An earlier version computed "chance
of TPW > 1 inch" via a Gaussian estimate from WM-6's mean/std (that
variable has no raw-member or threshold-probability output via the API) --
dropped in favor of just showing the forecast value itself.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export WB_API_KEY=...              # https://app.windbornesystems.com/api_tokens

python3 build_map.py                                 # latest run, 10-day peak TPW, daily steps
python3 build_map.py --max-hour 168 --step-hours 12   # 7-day window, twice-daily sampling
```

Output PNG lands in `output/elida_moisture_pnw.png`. Every live fetch also
auto-saves the raw grid to `output/elida_moisture_snapshot_<init>.npz` --
pass that to `--file` to re-render (style tweaks, etc.) without re-fetching
WM-6.

## Files

- `build_map.py` -- fetches WM-6's gridded ensemble-mean TPW at every
  `--step-hours`-spaced forecast hour out to `--max-hour`, takes the max
  across all steps, and renders the map. Map domain, city labels, Elida's
  marked position, and color ramp are all defined near the top -- edit
  directly to adjust (in particular, `ELIDA_LON`/`ELIDA_LAT`/`ELIDA_LABEL`
  are a snapshot of the NHC advisory at the time this was written, not
  live-updating).
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`admin1_boundary_lines.json` / `admin0_boundary_lines.json` (state/province
and international borders) and `land_slim.json` (coastline). The Ingalls
Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- **Map domain** (`LON_MIN`/`LAT_MIN`/etc.) is zoomed out to show Elida's
  current position in the open Pacific with real geographic context, up
  through the CA/NV/OR coastal and Great Basin corridor into the Pacific
  Northwest -- a fixed box matching *today's* storm position, not detected
  live each run. Re-running this script later (once Elida has moved, or
  for a different storm) means updating `LON_MIN`/`LAT_MIN`/`ELIDA_LON`/
  `ELIDA_LAT` to match. It's noticeably wider (east-west) than this repo's
  other, more regionally-compact maps -- that's deliberate: the
  storm-to-PNW domain is far more north-south elongated than
  columbia-basin-temps/western-us-noaa-outlooks' domains, and the extra
  longitude is what lets it fill the same 10x8.9in canvas as every other
  map here without heavy letterboxing on the sides.
- **No `domain=conus` crop.** The gridded endpoint's `domain` param
  (regional crop, default `"conus"`) is documented for the regional-native
  products (wm6-3km, hrrr); this script deliberately leaves it unset for
  wm-6's own global grid rather than assume a server-side "conus" crop
  reaches as far southwest as Elida's actual position (21.4N 125.2W, well
  south of a strict CONUS bounding box) -- risking the storm itself
  silently getting cropped out. `fetch_all()` prints the actual lat/lon
  extent the API returns on first fetch, with a warning if it doesn't
  reach the map's SW corner (in which case that corner is nearest-neighbor
  extrapolated in the render, not real model data -- watch the console
  output on first run).
- **Color ramp** is a fixed absolute TPW scale (`TPW_VMIN_IN`/`TPW_VMAX_IN`
  = 0-3in), tan (dry) -> green -> blue (saturated) -- `TPW_COLOR_STOPS` in
  `build_map.py`. Fixed rather than rescaled per run, same spirit as the
  temperature color table in `columbia-basin-temps/build_map.py`, so a
  given shade always means the same TPW value across every map this script
  renders. The colorbar itself only draws the slice of that table actually
  visible in the current frame.
- **`fetch_deterministic_field()`** reads WM-6's plain gridded response
  (no `include_distribution`) via the path WindBorne's own docs show in a
  code example -- `g["deterministic"][variable]` -- with a fallback that
  searches the whole zarr tree by variable name and prints the structure
  if that path doesn't exist, rather than silently mis-reading. This is a
  much more solidly-documented code path than the earlier
  `include_distribution=true` version used (WindBorne doesn't publish the
  exact zarr layout for the distribution stats, only prose describing what
  fields it adds).
- **zarr version.** zarr's `ZipStore` takes a real file path in zarr v3 but
  accepted an in-memory buffer in v2 -- `fetch_all()` writes each
  downloaded `.zarr.zip` to a temp file before opening it so this works
  either way, since `requirements.txt` doesn't pin a zarr major version.
- **Every fetch downloads ~1.9 GB, confirmed against the live API.**
  WM-6's gridded endpoint rejects `variable=total_column_water_vapour` for
  *every* forecast hour of the current run with "Variable filtering is not
  available for archived forecasts" -- not just hours whose valid time has
  already passed, which is what that error message implies. The only way
  to pull any data at all is `variable=all`, which returns the complete
  global grid with all 163 `deterministic` variables (plus ensemble
  percentiles/members/etc.) at 0.25 deg resolution, ~1.9 GB per forecast
  hour, instead of the small single-variable slice this script was
  originally written assuming. At good bandwidth that's ~20-30s/fetch; it
  was considerably slower (and appeared to hang) the one time this was
  tried as a backgrounded process, possibly rate-limiting on sustained
  long-lived connections -- foreground runs so far have been reliable.
  Because of this, `--step-hours` now defaults to 24 (11 fetches, one/day)
  rather than a finer native-cadence sampling; the first real run used
  `--step-hours 48` (6 fetches, ~6.5 min total) to keep it well within a
  single command's timeout. Finer sampling directly multiplies both fetch
  count and total download time -- `--step-hours 12` is ~22 fetches
  (~40+ GB, several minutes to run).
- Verified against the live API on 2026-07-19 (WM-6 run initialized 14z):
  `fetch_deterministic_field()`'s `g["deterministic"][variable]` path is
  correct, coordinates come back as 1D global arrays (lat -89.75..90,
  lon -180..179.75, 0.25 deg), and the whole pipeline renders a real map
  end to end.
