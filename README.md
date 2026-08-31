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
- [`columbia-basin-lightning-map/`](columbia-basin-lightning-map/) — the
  canonical Columbia Basin lightning map (same domain as
  `columbia-basin-alerts-map/`): the last 24 hours of GLM flash detections,
  sourced from GOES-18.
- [`columbia-basin-lightning-realtime-map/`](columbia-basin-lightning-realtime-map/)
  — real-time companion to `columbia-basin-lightning-map/`: the last 2
  hours of GLM flash detections, with finer 0-30/30-60/60-120 minute
  recency bands for watching an active storm right now.
- [`dew-point-storm-map/`](dew-point-storm-map/) — one-off map of today's
  maximum dew point depression across British Columbia, Washington,
  Oregon, and Idaho, with a dashed red outline where ECMWF IFS's fields
  are consistent with thunderstorms today.
- [`wildcad-fires-map/`](wildcad-fires-map/) — the canonical map of
  currently active wildfires across the same domain as
  `dew-point-storm-map/`, merged from WildCAD-E (US dispatch centers),
  CAL FIRE (via NIFC WFIGS), BC Wildfire Service, and Alberta Wildfire.
- [`hrrr-smoke-chart/`](hrrr-smoke-chart/) — generates styled meteograms of
  NOAA HRRR smoke (near-surface as AQI or raw µg/m³, or vertically
  integrated) for one or more points over a full 48-hour HRRR cycle
  (defaults to Kennewick, WA and Hermiston, OR).
- [`tri-cities-7day-forecast/`](tri-cities-7day-forecast/) — generates a
  TV-style 7-day forecast graphic for the Tri-Cities: day-of-week, high/low
  temps, and a daytime-condition icon per day, from the NWS forecast.
- [`tri-cities-temp-chart/`](tri-cities-temp-chart/) — generates a styled
  14-day chart of Tri-Cities daily high temperature: 7 days observed
  (xmACIS) and 7 days forecast (WindBorne MetaMesh), against 1991-2020
  daily climatology (percentile shading and normal from xmACIS; record
  highs pooled across Tri-Cities-area stations).
- [`tempest-temp-chart/`](tempest-temp-chart/) — generates a styled
  same-day temperature chart from a personal WeatherFlow Tempest station:
  a single air-temperature line across the full 24-hour local calendar
  day, with the most recent observation marked and labeled.
- [`tpw-wm6-ensemble-map/`](tpw-wm6-ensemble-map/) — one-off map of total
  precipitable water for a single valid time, from the WindBorne
  WeatherMesh-6 global ensemble mean, spanning Hawaii to the northwest
  corner of Saskatchewan.

## Shared resources

- [`maps/`](maps/) — reusable basemap data (coastlines, borders, counties,
  roads) shared across mapping scripts.
- [`assets/`](assets/) — shared brand assets (logo, etc.).
