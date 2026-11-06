"""
Site definitions for the snow level charts. Each site is the point the model
profile is pulled at, plus the horizontal reference lines (passes, towns, ski
areas) drawn across the chart. Elevations are in feet.

Add a new site by adding an entry here -- fetch_forecast.py and
build_chart.py both take --site <key>.
"""

SITES = {
    "snoqualmie": {
        "title": "Snoqualmie Pass",
        "lat": 47.4245,
        "lon": -121.4130,
        "refs": [
            {"label": "Pass level", "elev_ft": 3022},
        ],
    },
    "hood": {
        "title": "Mount Hood",
        # Government Camp -- the profile is a free-atmosphere sounding, so
        # anywhere on the south side of the mountain gives the same answer at
        # WM-6's ~25 km grid spacing.
        "lat": 45.3018,
        "lon": -121.7537,
        "refs": [
            {"label": "Government Camp", "elev_ft": 3980},
            {"label": "Mt. Hood Meadows base", "elev_ft": 4523},
            {"label": "Timberline Lodge", "elev_ft": 5960},
        ],
    },
}
