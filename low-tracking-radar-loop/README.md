# Low-Tracking Radar Loop

An animated NEXRAD reflectivity loop on a satellite basemap where the
**camera follows a surface low** instead of the low sliding across a fixed
map -- built for a coastal low making landfall on the Washington/Oregon
coast, from KLGX (Langley Hill, WA) by default. Output is a 1080x1920
(9:16) MP4 for a Facebook Reel, full-bleed with no margin, plus a PNG of
the final frame to use as the reel's cover.

The low's center is tracked hour to hour in HRRR sea-level pressure
analyses; the camera rides a smoothed version of that track, centered
75 km north of the low (`CAMERA_NORTH_KM`) so the frame favors the
Washington coast and Puget Sound over open ocean. There's no marker on
the low itself -- the circulation in the radar is the point. A
**LANDFALL** badge appears once the center crosses the coast.

## Files

- `build_loop.py` -- lists the radar's Level II volumes for the window,
  tracks the low in HRRR MSLP, fetches the radar volumes and satellite
  tiles, and renders/encodes the reel. Processed sweeps, HRRR fields, and
  tiles are cached under `output/cache/`, so re-renders (e.g. to tweak
  styling) don't re-fetch anything.
- `requirements.txt` / `setup.sh` -- Python dependencies (all pip, no
  apt: pygrib's wheels bundle eccodes, and imageio-ffmpeg ships its own
  ffmpeg) plus the Poppins font.

Uses `../maps/land_slim.json` (landfall detection) and
`../assets/ingalls_weather_logo.png` (top-right badge -- the PNG's
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

Other knobs: `--view-km` (frame width in ground km, default 240),
`--fps` (30), `--frames-per-scan` (4 -- how many output frames each radar
scan is on screen), `--hold` (seconds to hold the final frame, 2),
`--max-frames N` (debug: only the last N scans).

Output lands in `output/<site>_low_tracking_<YYYYMMDD_HHMM>.mp4` and
`..._cover.png`, named for the last scan's UTC time.

## Methodology

### Radar

- Level II volumes from the Unidata/AWS open-data bucket
  (`unidata-nexrad-level2`), read with MetPy's `Level2File`. Only the
  first sweep is kept -- the lowest tilt (~0.3 deg at KLGX, which scans
  below 0.5 deg for coastal coverage) super-res reflectivity, 0.5 deg x
  250 m.
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

### The loop

- Scans are kept only while the tracked low is within 330 km of the radar
  -- past that the lowest tilt overshoots most of the precip shield.
- Each scan holds for `--frames-per-scan` frames while the camera keeps
  gliding along the track between scan times, so the pan is smooth at
  30 fps even though scans come every ~5 minutes; echoes stay fixed to the
  ground and update when the next scan arrives.
- All text lives between the top 14% and bottom 35% of the frame, which
  Facebook's reel UI covers. A town label fades out only where it
  would overlap a header element (title, time, legend, credits, logo,
  landfall badge), so labels still show in the gaps between them.
  Times are local, 24-hour.
- Landfall is the first minute the smoothed track falls inside
  `land_slim.json`'s land polygons.

### Basemap

Esri World Imagery tiles at zoom 10, mosaicked once for the whole camera
path, Lanczos-resampled to the frame's pixel grid, and darkened ~20% so
the radar reads. The credit line in the header reads "Ingalls Weather ·
NEXRAD Level II · Imagery: Esri, Maxar, Earthstar Geographics".
