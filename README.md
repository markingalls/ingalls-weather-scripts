# Ingalls Weather Scripts

Scripts and tools for Ingalls Weather's forecasting, social, and mapping
workflows. Each project lives in its own directory with its own README.

## Projects

- [`columbia-basin-alerts-map/`](columbia-basin-alerts-map/) — generates a
  styled map of active NWS weather alerts across the Columbia Basin for
  Instagram.
- [`western-us-noaa-outlooks/`](western-us-noaa-outlooks/) — generates
  styled Western U.S. maps for a range of NOAA outlooks: CPC extreme heat,
  temperature, and precipitation (6–10 day, 8–14 day, week 3–4); SPC fire
  weather and severe weather; and WPC excessive rainfall.
- [`columbia-basin-temps/`](columbia-basin-temps/) — the canonical
  Columbia Basin temperature map (same domain as
  `columbia-basin-alerts-map/`): high, low, or a specific hour's temps,
  from WM-6 3km, NOAA HRRR, ECMWF IFS, or ECMWF AIFS.
- [`850-700-temp-chart/`](850-700-temp-chart/) — generates a styled
  meteogram of the WindBorne WM-6 ensemble spread for a pressure-level
  temperature at a point (defaults to KPSC / 850 mb), compared against
  long-term climatology.
- [`dew-point-storm-map/`](dew-point-storm-map/) — one-off map of today's
  maximum dew point depression across British Columbia, Washington,
  Oregon, and Idaho, with a dashed red outline where ECMWF IFS's fields
  are consistent with thunderstorms today.
- [`wildcad-fires-map/`](wildcad-fires-map/) — the canonical map of
  currently active wildfires across the same domain as
  `dew-point-storm-map/`, merged from WildCAD-E (US dispatch centers), BC
  Wildfire Service, and Alberta Wildfire.

## Shared resources

- [`maps/`](maps/) — reusable basemap data (coastlines, borders, counties,
  roads) shared across mapping scripts.
- [`assets/`](assets/) — shared brand assets (logo, etc.).
