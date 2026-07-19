# Tropical Storm Elida Moisture Surge → Pacific Northwest Map (one-off)

A one-off styled map tracking the moisture plume moving north out of
(post-)Tropical Storm Elida -- currently churning in the open eastern
Pacific, ~985 mi west of southern Baja California -- toward the Pacific
Northwest: WM-6's (WindBorne WeatherMesh-6) ensemble chance of total
precipitable water (TPW) exceeding 1 inch, taken as the max across every
forecast step over the next 10 days -- so each pixel shows the best chance
of the plume passing over that spot at any point in the window, not just
on one particular day. Elida itself is forecast to weaken to a remnant low
and dissipate within a few days (NHC, 200 AM PDT Jul 19 2026 advisory);
this map tracks where its moisture ends up, not the storm's own track.

## Usage

```bash
bash setup.sh                      # first time / fresh environment only
export WB_API_KEY=...              # https://app.windbornesystems.com/api_tokens

python3 build_map.py                              # latest run, 10-day max, 1in threshold
python3 build_map.py --max-hour 168 --step-hours 3   # 7-day window, finer time sampling
python3 build_map.py --threshold-in 0.75             # different TPW threshold
```

Output PNG lands in `output/elida_moisture_pnw.png`. Every live fetch also
auto-saves the raw probability grid to `output/elida_moisture_snapshot_<init>.npz`
-- pass that to `--file` to re-render (different threshold, style tweaks,
etc.) without re-fetching WM-6.

## Files

- `build_map.py` -- fetches WM-6's gridded TPW mean/std at every
  `--step-hours`-spaced forecast hour out to `--max-hour`, converts each
  step to an exceedance probability, takes the max across all steps, and
  renders the map. Map domain, city labels, Elida's marked position, and
  color ramp are all defined near the top -- edit directly to adjust (in
  particular, `ELIDA_LON`/`ELIDA_LAT`/`ELIDA_LABEL` are a snapshot of the
  NHC advisory at the time this was written, not live-updating).
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/):
`admin1_boundary_lines.json` / `admin0_boundary_lines.json` (state/province
and international borders) and `land_slim.json` (coastline). The Ingalls
Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Notes

- **Why a Gaussian estimate, not a raw ensemble-member count.** WM-6's
  gridded API exposes true per-grid-point ensemble stats (128 raw members,
  or counts exceeding fixed thresholds) for several variables -- but
  `total_column_water_vapour` isn't one of them; the API's `variables`
  endpoint lists it as carrying only calibrated mean + standard deviation,
  no percentiles/members/thresholds. So "chance of TPW > 1 inch" here is
  computed analytically via `scipy.stats.norm.sf()`, assuming a normal
  distribution around that mean/std. Both moments are genuinely
  ensemble-calibrated, so this is a real probability estimate -- just not
  a literal "N of 128 members exceeded it" count, which the API doesn't
  expose for this variable. If WindBorne adds member-level or
  threshold-probability output for TPW, swap this for a direct count.
- **Map domain** (`LON_MIN`/`LAT_MIN`/etc.) runs from Elida's current
  position in the open Pacific (with a comfortable margin south/west) up
  through the CA/NV/OR coastal and Great Basin corridor into the Pacific
  Northwest -- a fixed box matching *today's* storm position, not detected
  live each run. Re-running this script later (once Elida has moved, or
  for a different storm) means updating `LON_MIN`/`LAT_MIN`/`ELIDA_LON`/
  `ELIDA_LAT` to match.
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
- **Color ramp** is tan (0%, dry) -> green -> blue (100%, saturated) --
  `PROB_COLOR_STOPS` in `build_map.py`.
- **API response shape uncertainty.** WindBorne's docs describe
  `include_distribution=true` as adding "mean, std, ... where applicable"
  but don't publish the exact zarr key layout for those stats, and no
  code sample in their docs demonstrates it. `extract_stat()` searches the
  returned zarr store's full tree for arrays named like "mean"/"std"
  rather than assuming a fixed path, and exits with the whole tree printed
  if it can't find exactly one of each -- so if WindBorne's actual layout
  doesn't match that guess, the fix is a one-line update to
  `extract_stat()`'s keyword lookup, not a silent wrong answer. This
  hasn't been exercised against a live API key; the fetch/crop/probability
  math and the zarr-tree search were unit-tested against synthetic data,
  and the render path was smoke-tested end to end via `--file` with a
  synthetic snapshot, but the real `total_column_water_vapour` +
  `include_distribution` response has not been.
- **zarr version.** zarr's `ZipStore` takes a real file path in zarr v3 but
  accepted an in-memory buffer in v2 -- `fetch_all()` writes each
  downloaded `.zarr.zip` to a temp file before opening it so this works
  either way, since `requirements.txt` doesn't pin a zarr major version.
- **Canvas** is a taller portrait (10x14in) than the rest of this repo's
  maps (10x8.9in) -- Elida's current position to the PNW is a much more
  north-south-elongated domain than the other, more regionally-compact
  maps here, so the shared square-ish canvas left large empty margins on
  either side.
- Fetching the full 10-day window at the default 6-hour step is 41
  requests (one small single-variable grid each, and larger than the
  CONUS-cropped versions of this script since no `domain` filter is
  applied); `--step-hours 3` doubles that for finer time resolution,
  `--step-hours 12` halves it.
