# Pacific Northwest Average First Freeze Map

A styled climatology map covering the same BC/WA/OR/ID (+ slivers of
NV/MT/WY) domain as [`../dew-point-storm-map/`](../dew-point-storm-map/):
each GHCN-Daily station's 1991-2020 average date its daily low
temperature first drops to ≤32°F (0°C) after July 1, plotted as a
cool-to-warm colored dot (purple/blue in August through orange/red in
December) at that station's own location — no interpolation or shading
between stations, just the stations themselves. Unlike the rest of this
repo's maps, there's no live model or observation fetch here — this is a
climatology, rebuilt only when you want a fresher 30-year window or
denser station coverage.

## Files

- `fetch_climatology.py` — discovers GHCN-Daily stations inside the domain
  bbox, pulls each one's daily TMIN for 1991-2020 from NOAA's Access Data
  Service, and writes `climatology.json`: per station, the mean/median day
  (as an offset from July 1, plus a formatted date) its first qualifying
  freeze occurred each year, and how many of the 30 years actually
  qualified.
- `build_map.py` — plots `climatology.json`'s stations as colored dots at
  their own locations and renders the map.
- `requirements.txt` / `setup.sh` — Python + system dependencies (cartopy
  needs GDAL, apt-only). `setup.sh` also installs the Poppins font used
  for map labels, since it isn't packaged for apt.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`land_slim.json`, `states_lakes_slim.json`, `admin1_boundary_lines.json`,
`admin0_boundary_lines.json` — already clipped to US/Canada/Mexico,
including British Columbia.

The Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                              # first time / fresh environment only
python3 fetch_climatology.py               # writes climatology.json (~2-4 min)
python3 build_map.py                       # reads climatology.json, renders the map
python3 fetch_climatology.py --min-years 25  # stricter per-station completeness
python3 build_map.py --climatology data.json --out output/custom_name.png
```

`fetch_climatology.py` only needs re-running if you want to refresh the
climatology period or change the completeness threshold — it has nothing
to do with a specific forecast run, so a saved `climatology.json` is good
to re-render from indefinitely.

## Why GHCN-Daily instead of a gridded product, and why not ACIS

There's no single ready-made gridded "first freeze" product that spans
both the US and Canada: PRISM, NOAA's nClimGrid-Daily normals, and NCEI's
own published Freeze/Frost Normals table are all CONUS-only, and this
domain is half British Columbia. NASA/ORNL's Daymet *does* grid daily
Tmin at 1km across all of North America (US, Canada, Mexico in one file),
which would fill in the gaps between stations with real terrain-resolved
data instead of leaving them blank — but as of this writing Daymet's
data-serving backend has moved behind NASA's Earthdata Login (a free
account + token, not a paid one, but still something this script can't
provision on its own), so it was set aside in favor of a source with no
auth step at all.

[`../tri-cities-temp-chart/`](../tri-cities-temp-chart/)'s climatology
uses ACIS (the backend behind xmacis.rcc-acis.org), but ACIS's station
coverage into BC is thin/uncertain, whereas GHCN-Daily — NOAA's global
daily archive — ingests Environment and Climate Change Canada's own
station reports alongside NOAA's, so the same query against the same
backend picks up both sides of the border (confirmed by inspecting the
returned station IDs: both `US*` and `CA*` prefixes come back from a
single request to NCEI's Access Data Service).

## Methodology notes

- **Station discovery**: GHCN-Daily's published `ghcnd-stations.txt` /
  `ghcnd-inventory.txt` metadata files, filtered to stations inside the
  domain bbox whose TMIN inventory span plausibly overlaps 1991-2020
  (firstyear ≤1995, lastyear ≥2018 — a loose prefilter; a station's real
  completeness is checked against its actual fetched daily values, not
  just this inventory range, since the range doesn't guarantee no gaps
  within it). Around 1,400 candidate stations fall in this domain.
- **Daily readings** come from NCEI's Access Data Service
  (`dataset=daily-summaries`), batched ~50 station IDs per request
  (confirmed via manual testing that comma-separated station IDs in one
  request return each station's own rows correctly) rather than one
  request per station, to keep total request count reasonable. The
  service's date range is a single continuous span, so requesting "just
  July-December, every year" isn't directly expressible — the fetch
  spans the full `1991-07-01`..`2020-12-31` continuous range (pulling in
  each year's January-June too, discarded client-side) rather than
  issuing one request per year, trading roughly 2x bandwidth for far
  fewer HTTP requests. Readings are requested pre-converted to whole °F
  (`units=standard`) directly from the service, so no unit-conversion
  step happens client-side.
- **Per station, per year**: the first date on or after July 1 whose TMIN
  reading is ≤32°F, expressed as an offset in days from that year's July
  1 (0-183) rather than an absolute day-of-year — this sidesteps the
  leap-year day-of-year misalignment (Dec 31 is day 366 in a leap year,
  365 otherwise) that would otherwise skew an average taken across leap
  and non-leap years.
- A station is kept only if at least `--min-years` (default 20) of the 30
  candidate years produced a qualifying freeze date — some low-elevation
  or coastal stations don't freeze at all in some years, and any station
  can have data gaps. Both mean and median day-offset are recorded;
  `build_map.py` plots the mean.
- **No interpolation**: `build_map.py` plots each station's own
  mean-offset value as a colored dot at that station's lon/lat — nothing
  is resampled onto a regular grid or shaded between stations. This is a
  deliberate departure from how the other maps in this repo (e.g.
  [`../dew-point-storm-map/`](../dew-point-storm-map/)) fill their whole
  domain with `scipy.interpolate.griddata`: a dense model grid is fair to
  interpolate across, but station coverage here is uneven enough, and
  elevation-driven enough, that a smoothed fill would visually claim more
  than the data supports (see the next bullet).
- **This is a set of station points, not a terrain-resolved grid** —
  treat it as a regional overview, not a precise local forecast.
  Elevation is the single biggest driver of frost timing in this domain
  (a few hundred feet of elevation gain can shift the real average date
  by a week or more), and station density thins out considerably away
  from valleys, airports, and populated areas — especially in interior BC
  and the Cascade/Rocky Mountain high country. Plotting only the actual
  station dots (each with a white halo for legibility against both the
  land fill and the color table's darker shades), rather than an
  interpolated surface, keeps the map honest about where the data is and
  isn't.
- **Color table** runs cool-to-warm as a stand-in for early-to-late:
  purple/blue (August, high mountain interior) through green/yellow
  (September-October) to orange/red (November-December, milder
  low-elevation and coastal areas), fixed day-offset control points in
  `DATE_COLOR_TABLE_OFFSET` (not rescaled per map, so a given shade
  always means the same calendar window across runs).
- Uses `PlateCarree`, same domain/figure geometry/aspect-ratio reasoning
  as [`../dew-point-storm-map/`](../dew-point-storm-map/) — see that
  project's README for why `NearsidePerspective` doesn't fit this bbox
  well.
- No lakes are shaded — `load_states()` drops lake features from the
  states/provinces dataset entirely (not just leaving them unfilled) so
  they don't get drawn as a false state/province border either.
