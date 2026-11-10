# Wallowa County Earthquakes Map

A styled map of every M3.0+ earthquake on record in and around Wallowa
County, OR (Walla Walla down to Baker City / Halfway, east across Hells
Canyon to Riggins and New Meadows, ID), from the USGS ComCat catalog, for
Ingalls Weather's Instagram. The most recent quake is drawn as a red
circle with a callout; every earlier quake is gray. Circles are sized by
magnitude.

## Files

- `fetch_earthquakes.py` -- queries the USGS FDSN event service for every
  M3.0+ event in the map domain over the full period of record and writes
  `earthquakes.json`. Run this first, any time you want the map to
  reflect the latest catalog.
- `build_map.py` -- renders the map using `earthquakes.json` plus the
  static basemap files in `../maps/`. Writes `wallowa_earthquakes.png`.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip).

Shared basemap data lives one level up in [`../maps/`](../maps/). The
Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).
The Poppins fonts are installed by
[`../columbia-basin-alerts-map/setup.sh`](../columbia-basin-alerts-map/setup.sh).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                                  # first time / fresh environment only
python3 fetch_earthquakes.py                   # highlight the most recent M3+ quake
python3 fetch_earthquakes.py --event-id uw714136981   # ... or a specific USGS event
python3 build_map.py                           # render wallowa_earthquakes.png
```

## Notes

- **Source**: USGS ComCat via the FDSN Event Web Service
  (`earthquake.usgs.gov/fdsnws/event/1/query`) -- public, no API key.
  The query starts in 1900, so it returns everything ComCat holds for the
  domain; here the record starts with the 1936 M6.0 near Milton-Freewater
  / Walla Walla.
- **Catalog completeness**: before regional networks came online in the
  1970s, ComCat is far from complete below ~M4 in this area, so the gap
  between 1936 and 1971 is a detection gap, not a quiet period.
- **Domain**: `LON_MIN/LON_MAX/LAT_MIN/LAT_MAX` in `fetch_earthquakes.py`
  match `EXTENT` in `build_map.py` -- change both together. Wallowa County
  itself is tinted and outlined (FIPS 41063).
- **Highlight**: defaults to the most recent event in the catalog, which
  is what you want the morning after a quake. Use `--event-id` (the id at
  the end of the event's USGS URL) to highlight an older one.
- **Sizing**: marker diameter is linear in magnitude (M3 ~7pt to M6
  ~37pt). Magnitude is already logarithmic, so scaling circle area by
  energy would make the 1936 M6 swallow the map.
