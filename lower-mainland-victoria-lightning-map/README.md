# Lower Mainland / Victoria Lightning Map (One-Off)

A one-off styled map zoomed to Whistler (N), Hope (E), Port Renfrew (W),
and Everett (S) -- covering Metro Vancouver, the Fraser Valley, southern
Vancouver Island, and the northwest Puget Sound corridor: GLM (Geostationary
Lightning Mapper) flash detections for a single full calendar day (Pacific
time), sourced from GOES-18, for Ingalls Weather's Instagram.

Unlike [`../columbia-basin-lightning-map/`](../columbia-basin-lightning-map/)
(a rolling 24-hour lookback ending "now"), this pulls one specific calendar
day in the past -- built for "yesterday's lightning," not a live snapshot.

## Files

- `fetch_lightning.py` -- pulls GLM-L2-LCFA flash detections for one full
  Pacific-time calendar day out of NOAA's public `noaa-goes18` bucket on
  AWS Open Data and writes `output/lightning_<date>.json`. Defaults to
  yesterday.
- `build_map.py` -- renders the map from `output/lightning_<date>.json`
  plus the static basemap files in `../maps/`. Writes
  `output/lower_mainland_victoria_lightning_<date>.png`.
- `requirements.txt` / `setup.sh` -- Python + system dependencies
  (cartopy needs GDAL, which only installs via apt, not pip; the Poppins
  font used for map labels isn't packaged for apt either).

Shared basemap data lives one level up in [`../maps/`](../maps/). The
Ingalls Weather logo lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

Run from inside this directory (paths to `../maps/` and `../assets/` are
relative to it):

```bash
bash setup.sh                            # first time / fresh environment only
python3 fetch_lightning.py               # pull yesterday's flashes (Pacific time)
python3 fetch_lightning.py --date 2026-08-22   # ... for a specific date
python3 build_map.py                     # render yesterday's map
python3 build_map.py --date 2026-08-22   # ... for a specific date
```

## Notes

- **Source and access**: same GLM-L2-LCFA product and AWS Open Data access
  pattern as `../columbia-basin-lightning-map/` -- see that project's
  README for background on the flash product and file layout. This
  script's only difference is that it fetches one fixed Pacific-time
  calendar day (00:00-24:00) instead of a rolling 24-hour window ending
  now.
- **Domain**: bounding box is the exact Whistler/Hope/Port Renfrew/Everett
  extremes, padded 0.5 degrees for the flash fetch (so strikes right at
  the map edge aren't dropped pre-plot) and 0.2 degrees for the rendered
  map extent.
- **Projection**: PlateCarree, not the `NearsidePerspective` used by the
  other lightning/temperature maps in this repo -- at this domain's
  tighter, more elongated shape, `NearsidePerspective`'s curved projected
  rectangle left visible blank corners; see the same tradeoff noted in
  `../dew-point-storm-map/build_map.py`.
- **Time-of-day bands**: since this covers one fixed past day rather than
  a rolling lookback, flashes are colored by local (Pacific) clock time --
  overnight/morning (pale yellow) through evening (hot pink) -- rather
  than "hours ago." Bands are drawn chronologically (earliest first) so
  later-day strikes render on top where tracks overlap.
- **Roads/counties coverage**: `../maps/` has road and county basemap data
  for WA/OR/ID only, not British Columbia, so only the Bellingham/Everett
  corner of this map shows highways and county lines. The rest of the
  domain (Metro Vancouver, the Fraser Valley, Vancouver Island) shows
  land, the Canada/US border, and the BC/WA provincial boundary only.
