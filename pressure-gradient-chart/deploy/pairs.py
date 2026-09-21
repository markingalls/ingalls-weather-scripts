"""
The station pairs deployed live on images.ingallswx.com -- one gradient
chart and one obs+forecast chart per pair. publish_gradient.py and
publish_forecast_gradient.py both loop over PAIRS in a single cron-driven
run (same one-lock-many-outputs pattern as
hrrr-smoke-chart/deploy/publish_smoke.py), so adding or removing a pair
here is the only change either script needs.

Each entry is (station_a, station_b, slug). Labels aren't given
explicitly -- fetch_gradient.py/fetch_metamesh_gradient.py both default
--label-a/--label-b to the station's own bare 3-letter code when omitted,
which is exactly what every pair here wants. slug names the published
PNGs (<slug>_gradient.png / <slug>_gradient_forecast.png) and each pair's
own intermediate/lock files, so pairs never collide with each other.

All are NWS ASOS/AWOS airport stations bracketing a specific Pacific
Northwest terrain gap or valley -- confirmed live (both against
api.weather.gov and, for the forecast chart, WindBorne MetaMesh) before
adding a pair here, per pressure-gradient-chart/README.md's own notes on
verifying a new station before use.

- AST-PDX: Astoria (river mouth) to Portland -- lower Columbia River /
  coastal gradient.
- PDX-DLS: Portland to The Dalles -- western Columbia River Gorge.
- PDX-GEG: Portland to Spokane -- a long, cross-Cascades/eastern-WA span.
- PDX-HRI: Portland to Hermiston -- the original pair this project was
  built around; central Gorge / Columbia Basin entrance.
- SEA-ELN: Seattle to Ellensburg -- Snoqualmie Pass / Stampede Gap,
  the I-90 corridor gap in the central Cascades.
- HRI-ALW: Hermiston to Walla Walla -- an intra-Basin gradient around the
  Wallula Gap / lower Walla Walla valley.
"""
PAIRS = [
    ("AST", "PDX", "ast_pdx"),
    ("PDX", "DLS", "pdx_dls"),
    ("PDX", "GEG", "pdx_geg"),
    ("PDX", "HRI", "pdx_hri"),
    ("SEA", "ELN", "sea_eln"),
    ("HRI", "ALW", "hri_alw"),
]
