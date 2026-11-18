# Ingalls Weather Scripts — standing preferences

- **Always use 24-hour time** (e.g. `07:45`, `19:00`) everywhere: map and
  chart titles/subtitles, labels, axis ticks, captions, console output and
  replies. Never use am/pm unless the request explicitly asks for it.
  Older scripts in this repo may still print 12-hour times; switch them to
  24-hour when touching them.

## Default map labeling: a value at a location

Whenever a map shows a value at a named place (temperature, snowfall,
wind, rain total, ...), label it this way unless asked otherwise. The
reference implementation is the `# Labels --` block in
`blue-mountains-downslope-map/build_map.py`; copy it rather than
re-deriving it.

- **No dot or marker.** The place name is centered (`ha="center"`,
  `va="center"`) on the geographic point itself.
- **Name:** Poppins SemiBold, 12.5 pt, white, 0.9 pt black outline
  (`pe.withStroke(linewidth=0.9, foreground=(0, 0, 0, 0.85))`), written
  as `f" {name} "` on a black rounded box at 50% opacity:
  `bbox=dict(boxstyle="round,pad=0.04,rounding_size=0.25",
  facecolor="black", alpha=0.50, edgecolor="none")`. The tiny pad keeps the
  box short; the spaces around the name give the side padding.
- **Value:** centered just above the name (`ha="center"`, `va="bottom"`,
  offset up 7 pt with `offset_copy(..., y=7.0, units="points")`), Poppins
  Bold, 20 pt, white, thicker 2.2 pt black outline
  (`foreground=(0, 0, 0, 0.9)`), no box. Keep it short (`43°`, `58"`).
- **When there's no value** (e.g. no snow), show the name only, with no
  number.
- **Fewer, well-spaced labels.** Pick places so no box or number
  overlaps another; drop places that crowd a neighbor and say which were
  dropped. Where a label must stay but crowds something, nudge the whole
  label (name and value together) a few points up or down.
- **Clustered towns get one label.** For example, the Tri-Cities is one
  "Tri-Cities" label at the centroid of Kennewick, Pasco and Richland,
  showing the average of the three.
- **Sample the value** from the nearest native model/analysis grid point,
  not the resampled display raster.
- Fonts come from `/usr/share/fonts/truetype/google-fonts/`
  (`Poppins-SemiBold.ttf`, `Poppins-Bold.ttf`); a project's `setup.sh`
  should download them from google/fonts if missing.
