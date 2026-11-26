# Low-Tracking Radar Loop

An animated NEXRAD reflectivity loop on a satellite basemap where the
**camera follows a surface low** instead of the low sliding across a fixed
map -- built for a coastal low making landfall on the Washington/Oregon
coast, from KLGX (Langley Hill, WA) by default. Output is a 1080x1920
(9:16) MP4 for a Facebook Reel, full-bleed with no margin, plus a PNG of
the final frame to use as the reel's cover.

The low's center is tracked hour to hour in HRRR sea-level pressure
analyses; the camera rides a smoothed version of that track, centered
50 km north of the low (`CAMERA_NORTH_KM`) so the frame favors the
Washington coast and Puget Sound over open ocean. There's no marker on
the low itself -- the circulation in the radar is the point.

It also does **storm-scale loops** that follow a single cell along a
fixed track (`--waypoints`), in reflectivity or base velocity, with NWS
warning polygons drawn only while they were valid -- e.g. the
2026-11-26 tornado-warned cell from Shelton to North Bend
([`events/2026-11-26_katx_tornado_warning.sh`](events/2026-11-26_katx_tornado_warning.sh)).

## Files

- `build_loop.py` -- lists the radar's Level II volumes for the window,
  tracks the low in HRRR MSLP, fetches the radar volumes and satellite
  tiles, and renders/encodes the reel. Processed sweeps, HRRR fields, and
  tiles are cached under `output/cache/`, so re-renders (e.g. to tweak
  styling) don't re-fetch anything.
- `rotation_track.py` -- follows a velocity couplet through the
  lowest-tilt sweeps from a rough first-guess path and prints a
  `--waypoints` string for a storm-following loop.
- `events/` -- the exact command (with its waypoints) for each storm
  loop made, so it can be re-rendered or used as a template.
- `requirements.txt` / `setup.sh` -- Python dependencies (all pip, no
  apt: pygrib's wheels bundle eccodes, and imageio-ffmpeg ships its own
  ffmpeg) plus the Poppins font.

Uses `../assets/ingalls_weather_logo.png` (top-right badge -- the PNG's
pale-green square background is keyed to the emblem's cream and placed
on an anti-aliased cream disc with a white ring, since a plain circular
crop of the square shows the emblem's flat edges).

## Usage

```bash
bash setup.sh                     # first time / fresh environment only
python3 build_loop.py             # today (local midnight Pacific -> now), KLGX
python3 build_loop.py --start 2026-09-25T06:00 --end 2026-09-25T16:00   # UTC
python3 build_loop.py --site KRTX --title "Low Moves Inland"
python3 build_loop.py --seed 45.0,-126.1   # first-guess low position, if the
                                           # default pick grabs the wrong low
```

Storm-scale loop following a cell (see `events/` for a real one):

```bash
# 1. Waypoints: seed with a rough path (e.g. the warning's location +
#    motion extrapolated back), check the log, trim bad detections.
python3 rotation_track.py --site KATX --start 2026-11-26T17:20Z \
    --end 2026-11-26T20:40Z \
    --guess "2026-11-26T17:36Z,47.133,-123.399;2026-11-26T19:52Z,47.503,-122.024"
# 2. Render, once per product.
python3 build_loop.py --site KATX --product vel --sails --waypoints "..." \
    --start ... --end ... --view-km 100 --north-km 0 --towns puget \
    --warnings TO --title "Tornado-Warned Storm"
```

Storm-scale options: `--waypoints "ISO,lat,lon;..."` (follow a fixed,
spline-smoothed track instead of tracking a low in HRRR; extrapolated
past its ends), `--product ref|vel`, `--sails` (every lowest-tilt cut,
not just the first in each volume -- ~2 min updates instead of ~5),
`--warnings TO[,SV,...]`, `--towns coast|puget`, `--highways`
(motorways/trunks from `../maps/`, colored like the Columbia Basin maps),
`--minutes-per-sec X` (constant playback pace -- see "The loop"), `--storm-motion
FROM/KT` (storm-relative velocity; only helps when the storm moves
along the radar beam -- see below).

Other knobs: `--view-km` (frame width in ground km, default 265),
`--north-km` (camera offset north of the low, default 50; negative is
south),
`--fps` (30), `--frames-per-scan` (4 -- how many output frames each radar
scan is on screen), `--hold` (seconds to hold the final frame, 2),
`--max-frames N` (debug: only the last N scans).

Output lands in `output/<site>_<ref|vel|srv>_loop_<YYYYMMDD_HHMM>.mp4` and
`..._cover.png`, named for the last scan's UTC time.

## Methodology

### Radar

- Level II volumes from the Unidata/AWS open-data bucket
  (`unidata-nexrad-level2`), read with MetPy's `Level2File`. Only the
  lowest tilt is kept (~0.3 deg at KLGX, which scans below 0.5 deg for
  coastal coverage; 0.5 deg elsewhere), super-res 0.5 deg x 250 m.
  Reflectivity comes from the surveillance cut (it carries CC), velocity
  from the Doppler cut. By default only the first lowest-tilt cut per
  volume is used; `--sails` uses every one (SAILS/MRLE repeat it two or
  three times a volume), each a frame stamped with its own start time.
- **Non-meteorological echo** (sea clutter, AP, birds) is dropped where
  correlation coefficient is under 0.85. CC is averaged over a 3-radial x
  7-gate window first: per-gate CC is noisy in light rain, and masking on
  it raw punched pinholes all through real echo, which read as speckle.
  Gates past CC's shorter recorded range are kept.
- A **speckle filter** then drops any gate with fewer than 4 of its 8
  neighbors carrying echo, and everything under 12 dBZ is hidden.
- The palette is a TV-style continuous ramp (greens to 26 dBZ, yellow
  from 30); weak echoes fade in
  semi-transparent so they don't wall off the imagery underneath.
- **Velocity** is shown in kt, raw (not dealiased) -- fine as long as the
  storm's velocities stay under the Nyquist (25 m/s / 49 kt for KATX's
  VCP 212 on 2026-11-26; the couplet there peaked under 30 kt). The
  palette has a narrow gray band at zero and turns clearly red right
  away, because a weak couplet embedded in inbound flow is green next to
  a few kt outbound -- with a wide gray band it read only as "less
  green". Only the speckle filter applies (no CC in the Doppler cut).
- **Storm-relative velocity** (`--storm-motion`) subtracts the storm's
  motion along each radial. It only matters when the storm moves along
  the beam: on 2026-11-26 the cell moved ENE, almost across KATX's beam,
  so only ~3 of its 24 kt projected and SRV looked the same as base
  velocity.
- Radar is resampled (nearest gate) onto the frame's pixel grid. Ground
  range is treated as slant range -- at the lowest tilt the difference is
  under a kilometer even at 460 km.

### Tracking the low

- HRRR hourly analyses (f00) of MSLP (MAPS reduction, `MSLMA`) from
  `noaa-hrrr-bdp-pds`, fetching just that one GRIB message by byte range
  from the `.idx`. Hours past the newest posted analysis are filled from
  that run's f01/f02, so the loop reaches the newest radar scan (the
  analysis for the top of the hour posts ~50 min later).
- Each field is Gaussian-smoothed (~12 km) before searching -- raw 3 km
  MSLP is noisy, especially the terrain-reduced values over land after
  landfall -- then the minimum is found within 120 km of a persistence
  guess (last position + last hour's motion). The first hour searches
  within 600 km of the radar (or around `--seed`). The center is refined
  to a weighted centroid of the lowest ~0.3 hPa. Central pressure (the
  raw field's minimum within 25 km) is logged, not drawn.
- The camera follows cubic smoothing splines of lat/lon through the
  hourly centers, so it never jitters hour to hour.

### Following a storm cell

- `--waypoints` replaces the HRRR tracker with the same smoothing
  spline through hand-given points (extrapolated linearly past the
  ends), and drops the 330 km range filter.
- `rotation_track.py` finds those points: for each lowest-tilt velocity
  sweep it computes azimuthal shear across ~1 deg (two super-res
  radials), smooths it, and takes the strongest |shear| within 15 km of
  the first-guess path. Detections under 5e-3 /s are skipped as
  background. Max reflectivity was tried first and is useless inside a
  band of cells -- it hops between neighbors.

### Warnings

- `--warnings` pulls storm-based warning polygons from the IEM archive
  (`mesonet.agron.iastate.edu/geojson/sbw.geojson`) for the loop's time
  span, keeps those within radar range, and shows each one only while
  the displayed scan time is inside its `polygon_begin`..`polygon_end`
  -- so a warning cut back by a follow-up statement shows each polygon
  version only for its own span. Tornado red, severe yellow, flash
  flood green, special marine orange; drawn under the town labels.

### The loop

- Scans are kept only while the tracked low is within 330 km of the radar
  -- past that the lowest tilt overshoots most of the precip shield.
- By default each scan holds for `--frames-per-scan` frames while the
  camera keeps gliding along the track between scan times, so the pan is smooth at
  30 fps even though scans come every ~5 minutes; echoes stay fixed to the
  ground and update when the next scan arrives. That makes the pace
  uneven wherever scan spacing changes -- with `--sails`, KATX went from
  one lowest-tilt cut per ~5 min to one per ~1.8 min mid-event, so the
  early part played ~3x faster. `--minutes-per-sec` instead advances
  real time by the same amount every frame and holds each scan until
  the next one starts (13.4 for 2026-11-26: the warning-period pace).
- All text lives between the top 14% and bottom 35% of the frame, which
  Facebook's reel UI covers. A town label fades out only where it
  would overlap a header element (title, time, legend, credits, logo),
  so labels still show in the gaps between them.
  Times are local, 24-hour.

### Basemap

Esri World Imagery tiles, mosaicked once for the whole camera path at
the coarsest zoom (10 or finer) whose pixels are at most ~0.75 of an
output pixel -- zoom 10 at the 265 km synoptic view, 11 at storm scale -- Lanczos-resampled to the frame's pixel grid, and darkened ~20% so
the radar reads. The credit line in the header reads "Ingalls Weather ·
NEXRAD Level II · Imagery: Esri, Maxar, Earthstar Geographics".
