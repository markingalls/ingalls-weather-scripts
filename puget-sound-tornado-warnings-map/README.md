# Puget Sound Tornado Warnings Map

A one-off styled map of every Tornado Warning NWS Seattle (SEW) has issued
in the polygon era (storm-based warnings, Oct 2007 on), drawn over western
Washington, with the most recent warning day highlighted. It was made for
the 26 Nov 2026 King County warning, the first tornado warning ever
issued for King County. Basemap and styling match
[`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/),
zoomed to the Puget Sound / western Washington domain.

## Files

- `fetch_warnings.py` -- pulls the SEW Tornado Warning list for each year
  from the Iowa Environmental Mesonet (IEM) VTEC archive, plus each
  warning's polygon, and writes `tornado_warnings.json`.
- `build_map.py` -- renders the map from `tornado_warnings.json` plus the
  static basemap files in `../maps/`. Writes
  `puget_sound_tornado_warnings.png`.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, apt-only; Poppins is downloaded since it isn't
  packaged for apt).

## Usage

Run from inside this directory:

```bash
bash setup.sh                 # first time / fresh environment only
python3 fetch_warnings.py     # pull every SEW TO.W since 2007
python3 build_map.py          # render puget_sound_tornado_warnings.png
```

## Notes

- **Source**: api.weather.gov doesn't serve historical warnings, so this
  uses IEM's VTEC archive, the standard public record of NWS warnings.
  IEM's King County (WAC033) record goes back to 1988, and the 26 Nov 2026
  warning is the only tornado warning in it.
- **Polygon era only**: storm-based polygon warnings became the NWS
  standard on 1 Oct 2007, so `fetch_warnings.py` starts in 2007. SEW's
  first polygon-era tornado warning was Pierce County on 11 Oct 2014.
  The earlier county-based SEW tornado warnings that IEM's text archive
  has (Douglas/S. Okanogan Co. 4 Jul 1992, NE Snohomish Co. 31 May 1997)
  are left off on purpose. `fetch_warnings.py` still falls back to county
  geometry if a warning has no stored polygon (e.g. if you run it with
  `--start-year` before 2007).
- **Highlight**: `build_map.py` highlights the most recent warning day by
  Pacific-time date (official NWS Tornado Warning red, white halo).
  Everything earlier is drawn in a muted red underneath it.
- **Labels**: one date label per warning day (with a count when there was
  more than one warning that day), placed by hand in `LABEL_POS` with a
  leader line to the nearest edge of that day's polygons. The Grays
  Harbor days overlap heavily, so if you add a day or change the extent,
  re-check the label placement.
