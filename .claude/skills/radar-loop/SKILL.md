---
name: radar-loop
description: Make an Ingalls Weather storm-following radar loop reel (1080x1920 MP4 for Facebook Reels) with low-tracking-radar-loop/build_loop.py. Use when asked for an animated radar loop, a radar reel, or a loop that follows a low / storm center, from KLGX or any other NEXRAD site.
---

# Storm-following radar loop reel

The tool is `low-tracking-radar-loop/build_loop.py`; its README has the
full methodology. This file is the working recipe and the house style
agreed with the user, so a new loop matches the previous ones without
re-deriving decisions.

## House style (already the script's defaults -- don't change unasked)

- 1080x1920, full-bleed, no margin. 30 fps, 4 frames per scan, 2 s hold
  on the last frame. Camera glides between scans along a smoothed track.
- Esri World Imagery satellite basemap, darkened ~20%.
- Camera centered **50 km north** of the low (`--north-km`), view
  **265 km** wide (`--view-km`). The user tuned these by eye: 300/100 ->
  240/75 -> 265/50.
- **No marker on the low** -- no L, no pressure label, no track trail --
  and **no landfall badge**. The circulation in the radar is the point.
- Reflectivity palette: greens through 26 dBZ, **yellow starts at 30**,
  then orange/red/magenta; color bar ticks 20/30/40/50/60.
- Timestamp in local time, **24-hour** ("Fri Sep 25 · 07:42 PDT").
- Credit line: **"Ingalls Weather · NEXRAD Level II · Imagery: Esri,
  Maxar, Earthstar Geographics"** -- Ingalls Weather first, no HRRR
  listed.
- Logo top-right as a small round cream badge (`logo_badge()`); don't
  go back to a plain circular crop -- the emblem's flat edges show.
- Text stays out of the top 14% / bottom 35% (Facebook reel UI). Town
  labels fade only where they'd overlap a header element.

## Recipe

1. `cd low-tracking-radar-loop && bash setup.sh` in a fresh container.
2. Pick the site and window. Default is today, local midnight -> now.
   `--start/--end` are ISO times, UTC unless an offset is given. Scans
   are auto-trimmed to while the low is within 330 km of the radar.
3. Set `--title` to fit the event (default "Low Pressure Makes
   Landfall").
4. **Towns:** `TOWNS` in `build_loop.py` is tuned for the WA/OR coast
   and Puget Sound. For another site or region, add or remove entries,
   as `(name, lat, lon, "left"|"right")`. The side is where the label
   sits; use "left" when the label would run off the frame edge or into
   a neighbor.
5. Preview cheaply before the full render. Everything is cached under
   `output/cache/`, so re-runs don't re-download:
   `python3 build_loop.py --start <t> --max-frames 1 --frames-per-scan 1 --hold 0`
   then read `output/*_cover.png`. To check motion, render a short
   stretch and pull frames with the ffmpeg from
   `imageio_ffmpeg.get_ffmpeg_exe()`.
6. Full render: about 8 minutes for ~100 scans on 4 cores. Run it in
   the background.
7. Check a few frames across the loop (start/middle/end) before
   sending. The track log prints each hour's center and pressure; if it
   latches onto the wrong low, rerun with `--seed LAT,LON`.
8. Send the MP4 and `_cover.png`. Outputs are gitignored -- commit only
   code/README changes.

## Gotchas

- **Upload limit ~30 MB.** Encoding is CRF 23; a busier or tighter view
  can still exceed it. Re-encode at a higher CRF (e.g. 25) with
  libx264 rather than shrinking the frame.
- **HRRR latency:** the analysis for the top of an hour posts about
  50 min later. Until then the script fills from the previous run's
  f01/f02. Rerun later if the user wants analysis-only positions.
- **Stopping a render:** use `pkill -f "^python3 build_loop.py"`. A bare
  `pkill -f build_loop.py` also matches (and kills) the shell running
  the pkill.
- The lowest tilt is filtered for sea clutter and speckle (smoothed CC
  < 0.85, fewer than 4 of 8 neighbors). If a new site shows speckle or
  pinholes, tune `RHO_MIN`, `RHO_WINDOW` and `SPECKLE_MIN_NEIGHBORS`
  rather than raising the dBZ floor.
- Reusing the tool for a non-low feature (a squall line, a front) would
  need a different tracker than `track_low()`. The camera just follows
  whatever `SmoothTrack` it's given.
