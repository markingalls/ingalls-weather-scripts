# High Surf vs. Coastal Flood Explainer

A static informational graphic for Ingalls Weather's Instagram explaining
the difference between NWS **High Surf** and **Coastal Flood** alerts: what
causes each, the threat, who's at risk, what to do, and which alert levels
exist for each. Same canvas footprint, palette, fonts, card style, and
logo/title placement as `tri-cities-7day-forecast/`.

## Files

- `build_graphic.py` — renders `high_surf_vs_coastal_flood.png`. No data
  fetch: all copy lives in `COLUMNS` and `FOOTER_TEXT` near the top — edit
  directly to adjust wording.
- `requirements.txt` / `setup.sh` — Python dependencies and the Poppins font.

## Usage

```bash
bash setup.sh          # first time / fresh environment only
python3 build_graphic.py
```

## Notes

- **Alert chips use the official NWS hazard colors**, the same values as
  `NWS_COLORS` in `columbia-basin-alerts-map/build_map.py`. High Surf
  Warning and Coastal Flood Warning share the same official color (Forest
  Green), so they look identical on the chips — that's NWS's choice, not a
  mistake here. Chip text flips between dark ink and white by luminance
  (`text_color_for()`), since Coastal Flood Advisory's lawn green is too
  bright for white text.
- **High surf has no watch product** — NWS only issues High Surf Advisories
  and Warnings — which the graphic calls out next to its chips.
- **Thresholds aren't shown** because they're set locally by each NWS
  office (breaker heights for surf; water level above a tide gauge datum for
  coastal flooding), so no single set of numbers is right everywhere. The
  footer says so.
- Body text rows are laid out by measuring each rendered block's height
  (rather than a fixed per-line height), so copy edits that change line
  counts reflow without overlapping.
