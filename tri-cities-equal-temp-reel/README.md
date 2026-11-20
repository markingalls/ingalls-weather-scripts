# Tri-Cities Equal-Temperature Reel

Renders a vertical (1080x2340, 9:19.5) MP4 for Facebook/Instagram Reels: a
"year clock" pie (12 month wedges sized by day count, January at 12
o'clock, running clockwise) while a temperature sweeps from the year's
coldest normal to its warmest and back, twice (loops seamlessly). At each step, every part of the year whose
**normal daily average temperature** is within ±0.5°F of the current
temperature lights up in that temperature's color -- so the two mirror
stretches of the year that share a normal (e.g. **Apr 1–7 ≈ Oct 20–22**
at 50°F) light up together, with their date ranges spelled out under the
big temperature readout.

Inspired by the "Periods of equal UK mean temperature" graphic
(r/dataisbeautiful, @neilrkaye), rebuilt for KPSC in Ingalls Weather
styling.

## Files

- `fetch_normals.py` -- pulls NCEI 1991-2020 **daily normals** from ACIS
  (`normal: "1"`) and writes `normals.json` (365 days, plus annual mean).
  No API key. Only needs re-running if you change station or element.
- `build_reel.py` -- renders `normals.json` into
  `tri_cities_equal_temp_reel.mp4` (~45 s, H.264, yuv420p, 30 fps, faststart --
  uploads directly to FB/IG). `--still TEMP_F` renders a single PNG frame
  instead (layout preview / cover image).
- `requirements.txt` / `setup.sh` -- Python deps, ffmpeg, Poppins fonts.

## Usage

```bash
bash setup.sh                       # first time / fresh environment only
python3 fetch_normals.py            # KPSC daily-average normals
python3 build_reel.py               # -> tri_cities_equal_temp_reel.mp4 (~45 s)

python3 build_reel.py --still 50    # -> tri_cities_equal_temp_reel.png
python3 build_reel.py --cycles 1    # one up/down round trip (~22 s)
python3 build_reel.py --sweep-seconds 15 --hold-seconds 2

# Variants: highs or lows instead of daily average
python3 fetch_normals.py --element maxt
python3 fetch_normals.py --element mint
```

## Notes

- **Why NCEI normals, not raw-data percentiles** (unlike
  `tri-cities-temp-chart`): KPSC's raw daily record is missing 1991-1997,
  and a per-day average of ~23 raw years is noisy enough that the "same
  temperature" periods fragment into speckle. NCEI's normals are
  smoothed and gap-filled, so each temperature maps to clean arcs.
- **Colors** use the Ingalls Weather temperature color table, copied
  verbatim from `columbia-basin-temps/build_map.py` (fixed Kelvin
  anchors), so a shade means the same absolute temperature here as on the
  maps. The colorbar under the readout shows the bar range (rounded
  outward to 5°F), a box marking the current ±0.5°F band, and a line at
  the annual mean.
- **Smooth motion**: normals are linearly interpolated between day
  centers at 24 sub-steps per day, and lit runs are drawn as single
  wedges, so slices grow/shrink sub-day between frames without seams.
  The sweep uses cosine easing (slower near the coldest/warmest, where
  the lit arc widens fast), with a hold at each end.
- **Canvas size**: 1080x2340 matches modern phone screens (9:19.5), so the
  reel fills the screen instead of letterboxing as a 9:16 video does. The
  layout is designed on a 1080x1920 block, centered and scaled to 80% of
  the canvas width (`CONTENT_SCALE` / `X()` / `Y()` in `build_reel.py`),
  so there's plain background on all four sides -- keeping content clear
  of IG/FB's side buttons, top bar and captions. Scaling is done through
  DPI, so the content's proportions never change.
