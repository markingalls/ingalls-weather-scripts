# Puget Sound Tornado Warnings Map

A one-off styled map of every Tornado Warning NWS Seattle (SEW) has issued
since 1998, drawn as the warnings' storm-based polygons over western
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
python3 fetch_warnings.py     # pull every SEW TO.W since 1998
python3 build_map.py          # render puget_sound_tornado_warnings.png
```

## Notes

- **Source**: api.weather.gov doesn't serve historical warnings, so this
  uses IEM's VTEC archive, the standard public record of NWS warnings.
  IEM's King County (WAC033) record goes back to 1988, and the 26 Nov 2026
  warning is the only tornado warning in it. IEM lists no SEW tornado
  warnings at all from 1998 to 2013, so all 14 on the map are from 2014
  or later, and all of them have storm-based polygons.
  `fetch_warnings.py` falls back to county geometry for any warning that
  has no polygon stored (pre-2007 county-based warnings), but none of
  these needed it.
- **Highlight**: `build_map.py` highlights the most recent warning day by
  Pacific-time date (official NWS Tornado Warning red, white halo).
  Everything earlier is drawn in a muted red underneath it.
- **Labels**: one date label per warning day (with a count when there was
  more than one warning that day), placed by hand in `LABEL_POS` with a
  leader line to the nearest edge of that day's polygons. The Grays
  Harbor days overlap heavily, so if you add a day or change the extent,
  re-check the label placement.
