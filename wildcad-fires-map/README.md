# Current Wildfires Map

The canonical map of currently active wildfires across the same domain as
[`../dew-point-storm-map/`](../dew-point-storm-map/) (Prince George BC to
Winnemucca NV, Bella Coola BC to Yellowstone WY), merged from four
government sources since none of them alone covers the whole domain:
WildCAD-E (US dispatch centers), CAL FIRE (via NIFC WFIGS, for the strip
of northern California the domain dips into), BC Wildfire Service, and
Alberta Wildfire. Markers are sized (log scale, no name labels) by
acreage and colored gray if contained ("Being Held" or better, >75% for
CA), else red if first reported within the last 24 hours, else orange.
Fires over 25,000 acres get a dashed black outline ring, over 100,000
acres a solid one. Small (<10ac) or stale (90+ days no update) contained
fires, small *and* stale (28+ days) existing fires, and any existing
fire stale 60+ days regardless of size, are dropped after merging to
cut clutter -- see "Decluttering" below -- except new fires, which are
always shown regardless of size or staleness.

A second product, `--new-only`, renders from the same fetch but keeps
only fires first reported within the last 24 hours (`NEW_FIRE_HOURS` in
`build_map.py`) -- "what's new" rather than "everything active." A new
fire already reported contained still draws gray, not red (containment
still wins over age in `fire_color()`), so that legend entry stays; the
"Existing" (orange) entry is dropped since it structurally can't appear
in a set already filtered to age <= 24h.

## Files

- `build_map.py` -- queries every WildCAD-E dispatch center whose area
  overlaps the map domain plus the CAL FIRE/WFIGS, BC, and Alberta
  wildfire feature services, filters each to active wildfires, merges and
  dedups them, and renders the map -- `build_map(fires, fetched_at,
  output_path, new_only=False)`. Also saves a `.json` snapshot of the
  fetched/filtered fire list to `output/` each run, so `--file` can
  re-render without re-fetching. `--new-only` renders the "what's new"
  companion product instead of the standard map (see above).
- `deploy/publish_wildfires.py` -- cron entry point. Fetches once,
  renders and atomically publishes both products (`wildcad_fires.png`,
  `wildcad_new_fires.png`) from that single fetch. One product failing
  doesn't stop the other, same pattern as every other publish script in
  this repo.
- `deploy/crontab.example` -- every 3 hours at :59 Pacific time (02:59,
  05:59, 08:59, ... 23:59 America/Los_Angeles, via a `CRON_TZ` line --
  every other project in this repo schedules in UTC instead) -- both
  products share this cadence so they're never showing two different
  fetches side by side.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, apt-only). `setup.sh` also installs the Poppins font used
  for map labels, since it isn't packaged for apt.
- `basemap_cache/` -- not committed, gitignored, and needs no manual setup
  -- caches the land/state-line/country-line layer as a single raster PNG
  so a normal run doesn't re-render it from vector data every time.
  Self-invalidating; see
  `../columbia-basin-lightning-map/README.md`'s "Basemap raster caching"
  Notes entry for the full write-up -- same mechanism here, just a single
  fixed extent (no REGIONS dict) so there's one cache entry, and captured
  transparent (rather than opaque) so the ocean-colored `ax.patch` still
  shows through at sea, same as the live vector-drawn version did.

Shared basemap data lives one level up in [`../maps/`](../maps/):
`land_slim.json`, `states_lakes_slim.json`, `admin0_boundary_lines.json`.

The Ingalls Weather logo (bottom-left on the map) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                                    # first time / fresh environment only
python3 build_map.py                             # current active wildfires
python3 build_map.py --new-only                  # fires first reported in the last 24h only
python3 build_map.py --lookback-days 120         # widen the WildCAD-E query window
python3 build_map.py --file output/snapshot_....json  # re-render, no fetch
python3 build_map.py --file output/snapshot_....json --new-only  # same, new-only product
```

## Data sources and methodology

### US -- WildCAD-E

WildCAD-E's public web app (wildwebe.net) is a React SPA that calls
`https://snknmqmon6.execute-api.us-west-2.amazonaws.com/centers/<DC>/incidents?fromDate=...&toDate=...`
for each dispatch center. There's no published API doc -- this was found
by inspecting the app's JS bundle. It's unauthenticated and returns JSON.

- **Longitude sign bug (theirs, worked around here)**: the API returns
  longitude as a bare positive magnitude (e.g. `"120.297895"` for a fire in
  Chelan County, WA, which is actually -120.297895). Every dispatch center
  queried here is west of the prime meridian, so `build_map.py` negates
  longitude unconditionally -- safe for this domain, would need revisiting
  for an eastern-hemisphere or Alaska/Hawaii extension.
- **Which dispatch centers**: every one whose area of responsibility falls
  inside or close to the map domain -- all of WA/OR/ID (each state fits
  entirely inside the domain), western/central Montana, northern Nevada,
  northern Utah, and NW Wyoming (see `DISPATCH_CENTERS` for the full list
  and per-state reasoning). Centers overlapping the domain only partially
  are queried anyway; results get filtered to the exact `LON_MIN`/`MAX`/
  `LAT_MIN`/`MAX` box regardless, so over-including a center costs nothing.
- **"Currently active" is inferred, not an explicit flag.** A fire counts
  if `type == "Wildfire"` (excluding Smoke Check, False Alarm, Debris
  Fire, Vehicle Fire, Structure Fire, Prescribed Fire, etc.) and its
  `fire_status.control` timestamp is null. WildCAD's `out` timestamp
  turns out to be essentially never populated -- even fires
  contained/controlled weeks ago usually still show `"out": null` -- so
  it's useless as an activity filter. `control` (not yet declared
  controlled) is the more reliable signal that suppression is still
  ongoing.
- **`--lookback-days`** (default 90, matching `STALE_CONTAINED_DAYS` --
  see "Decluttering" below) sets how far back each center is queried for
  incidents. This has to be at least as wide as the longest staleness
  threshold the decluttering filters use, or a real, large, still-active
  fire can be silently missed at the *fetch* stage -- before those filters
  (the right place to drop stale/small ones) ever get a chance to run.
  Confirmed live: at the previous default of 30 days, several genuinely
  active fires reported 30-40+ days ago were missing from the map
  entirely -- an 8,069-acre uncontrolled fire near Starbuck, WA
  ("Tucannon Mutual Aid", reported 2026-06-16) among them -- not because
  they'd dropped out of WildCAD or gotten controlled, but because the API
  was never even asked for records that old.

### British Columbia -- BC Wildfire Service

Found via its ArcGIS Hub listing ("Fire Locations - Current"):
`https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/BCWS_ActiveFires_PublicView/FeatureServer/0`.
Every fire this season is a point in this layer, active or not, each with
an explicit `FIRE_STATUS` (`Out`, `Out of Control`, `Being Held`, `Under
Control`, `Fire of Note`). "Currently active" here means `FIRE_STATUS !=
"Out"` -- a looser definition than WildCAD's "not yet controlled", because
BC's status model doesn't map cleanly onto WildCAD's and BC's own `Out` is
a clean, explicit signal that WildCAD's field of the same name isn't. Size
(`CURRENT_SIZE`) is in hectares, converted to acres (`x2.47105`) for a
consistent legend with the US side.

### Alberta -- Alberta Wildfire

Found via the public Experience Builder wildfire-status app's embedded
data sources ("wildfire_location_active"):
`https://services.arcgis.com/Eb8P5h4CJk8utIBz/arcgis/rest/services/wildfire_location_active/FeatureServer/0`.
This layer is already curated to active fires only (its name says so, and
querying it shows no `Out`-equivalent status among its handful of current
records), so no extra activity filtering is applied. Size
(`AREA_ESTIMATE`) is in hectares, converted the same way as BC's. It also
exposes no true ignition/discovery date field -- `FIRE_STATUS_DATE` (last
status change) is used as the age proxy instead (see "Age coloring"
below), a known imperfection.

### California -- via NIFC WFIGS

WildCAD-E is a Pacific Northwest interagency dispatch system and doesn't
cover California, but the map domain's southern edge (`LAT_MIN` 39.7)
dips into the northernmost strip of it (Redding / Shasta-Trinity-Siskiyou-
Modoc). CAL FIRE's own site (fire.ca.gov) returned "Access Denied" to
unauthenticated requests when this was built, so this pulls from NIFC's
nationwide WFIGS "Incident Locations Current" feature service instead --
the same IRWIN-backed incident data CAL FIRE's own map draws from:
`https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0`.
It's nationwide, so it's queried with `where=POOState='US-CA'` -- every
other state in the domain is already covered by WildCAD-E, and pulling
this layer unscoped would just duplicate those fires under a different
ID. Already pre-filtered to current/active incidents (every CA record's
`FireOutDateTime` is null here, same unreliable-as-a-filter behavior as
WildCAD's own `out` field, so it isn't used as one). Size
(`IncidentSize`) is already in acres. Unlike the other three sources,
this one actually publishes a real percent-contained figure
(`PercentContained`), so CA's gray/contained threshold is a literal
`>75%` (`CALFIRE_CONTAINED_PCT`), not a status-category proxy.

### Merging

All four sources are fetched into one dict keyed by a source-prefixed ID
(`WC:<inc_num>`, `CA:<irwin_id>`, `BC:<fire_id>`, `AB:<fire_number>`) so
they can't collide with each other, then flattened.

### Decluttering

`is_visible()` drops fires after merging, before rendering -- purely to
cut clutter, not because a dropped fire isn't "real". "Last update" per
source, since only CA exposes a genuine one:

- WildCAD: the `fire_status.contain` timestamp if contained, else age.
- BC: `IGNITION_DATE` -- there's no per-fire edit/status-date field in
  the public layer, so this falls back to age, a known imperfection (it
  doesn't move when status actually changes).
- Alberta: `FIRE_STATUS_DATE` -- already a last-status-change field, so
  no extra imprecision beyond what it already has as the age proxy.
- CA: `ModifiedOnDateTime_dt`, a real last-modified field.

The rule differs by category:

- A **contained** (gray) fire is dropped if its last update is more than
  `STALE_CONTAINED_DAYS` (90) old, *or* if it's under `MIN_VISIBLE_ACRES`
  (10 acres) -- either alone is enough, any size. It's not still being
  worked and its own record hasn't moved either, or it's too small to
  read as more than a dot at this map's scale.
- An **existing** (orange) fire is dropped if it's under
  `MIN_VISIBLE_ACRES` *and* stale by `STALE_EXISTING_SMALL_DAYS` (28)
  -- both together -- *or* if it's stale by `STALE_EXISTING_ANY_DAYS`
  (60) regardless of size. A small fire that's still getting fresh
  updates stays visible; it only drops once it goes quiet too. A large
  one is never dropped just for being under `STALE_EXISTING_SMALL_DAYS`
  old -- see below for why -- only once it clears the much longer
  `STALE_EXISTING_ANY_DAYS` backstop.

`STALE_EXISTING_SMALL_DAYS` is shorter than `STALE_CONTAINED_DAYS` on
purpose: an existing fire gone quiet for a few weeks is more likely just
under-reported (still burning, no update filed) than actually done, so
it's dropped sooner if it's also small; a contained fire gone quiet is a
much stronger done-with-it signal, so it gets more benefit of the doubt
before being dropped outright, regardless of size. `STALE_EXISTING_ANY_DAYS`
is deliberately much longer than that, not shorter than
`STALE_CONTAINED_DAYS` -- for 3 of the 4 sources, "last update" on a
non-contained fire is really just time-since-first-reported (see above),
so a large fire still uncontained after a few weeks is often exactly the
one most worth keeping visible, not hiding; this only exists as a
backstop for a record that's stopped getting touched at all, and only
kicks in once that's been true a while. Note this only fires past
`--lookback-days` (default 90) worth of WildCAD history, since a fire
older than that is never fetched in the first place -- see
`--lookback-days` above; a fire genuinely uncontrolled for 60-90 days is
rare but real (e.g. a large fire burning most of a season), so this is
an active filter, not just a theoretical backstop.

**New fires are exempt from all of it** -- a fire reported in the last
`NEW_FIRE_HOURS` is always shown, any size, any staleness. The exemption
follows the same contained-wins-over-new priority `fire_color()` uses for
coloring (see below), so a fire's visibility and its display color never
disagree: a fire that's both contained and technically <24h old is
filtered as contained, since it would render gray, not red, either way.
Missing acreage or last-update data never triggers either filter -- same
"unknown doesn't mean drop it" bias used throughout this file (e.g. age
coloring below).

### Rendering

- **Marker sizing**: area (not radius) scales log-scale with acres, since
  fire size spans several orders of magnitude (0.1 to 10,000+ acres) in
  the combined dataset -- `marker_size_pts2()`.
- **Containment coloring (checked first, wins over age)**: gray if a fire
  is contained -- "Being Held" or better (or, for CA, actually >75%
  contained). **WildCAD/BC/Alberta don't publish an actual
  percent-contained figure** -- confirmed directly against their live
  APIs, not assumed -- so those three use a status-category proxy, not a
  literal percentage threshold:
  - WildCAD: `fire_status.contain` timestamp is set. Its `control`
    timestamp (fully controlled) is never set on any fire shown here,
    since WildCAD fires marked controlled are filtered out entirely as no
    longer active (see "Currently active" above) -- so "contain" is as
    far up the containment ladder as a WildCAD fire in this dataset gets.
  - BC / Alberta: `FIRE_STATUS` in `CONTAINED_STATUSES`
    (`"Being Held"`, `"Under Control"`).
  - CA: `PercentContained > CALFIRE_CONTAINED_PCT` (75) -- a real number,
    unlike the other three, since WFIGS actually publishes one. Missing
    percent reads as not-contained, the same safer-default-on-missing-data
    rule used everywhere else here.
- **Draw order**: markers are drawn red on top of orange on top of gray,
  so in a dense, overlapping cluster the most operationally urgent fires
  (new, uncontained) are never hidden underneath older or contained ones.
  All markers share one `zorder`, so this is controlled by sorting the
  fire list itself before the draw loop (ascending by color priority,
  gray/orange/red), not by giving each color a different `zorder` --
  within each color tier, acreage (descending) is still the tiebreaker,
  same as before, so a small fire isn't buried under a same-colored large
  one nearby either.
- **Large-fire outline rings**: a fire over `LARGE_FIRE_ACRES` (25,000)
  gets a dashed black ring traced around its own marker, and one over
  `MEGA_FIRE_ACRES` (100,000) gets a solid black ring instead -- drawn on
  top of every fire's own color-coded marker at the same size, so a truly
  major fire stands out regardless of what color its age/containment
  status happens to give it. Explained in its own legend row (dashed vs.
  solid ring swatches, via a small `HandlerCircle` legend handler, since
  a plain `Line2D` marker handle can't render a dashed edge).
- **Age coloring**: red if a fire was first reported within
  `NEW_FIRE_HOURS` (24 by default) and isn't contained, orange otherwise
  -- including any fire whose age can't be determined, a safer default
  than implying "new" on missing data (in practice this never happens:
  every source currently supplies *some* date field). Each source's
  notion of "first reported" differs in reliability:
  - WildCAD: the incident's initial-report timestamp. It's naive (no UTC
    offset) and dispatch centers log in local time, not UTC -- treated as
    UTC here, so up to ~7 hours off depending on the center's time zone.
  - BC: `IGNITION_DATE`, a real Esri epoch-ms field -- exact.
  - Alberta: no true ignition field exists in the public service, so
    `FIRE_STATUS_DATE` (last status change) stands in. For a genuinely new
    fire this is usually close to its actual start (the first status is
    set on initial report); for an old fire that just had a status
    change, it can understate age and wrongly read as "new."
  - CA: `FireDiscoveryDateTime`, a real Esri epoch-ms field -- exact.
- **No name labels.** With 300+ active fires typically on the map at once,
  no label-density threshold reads as anything but clutter -- size/color
  plus the legends carry the useful signal instead.
- **Ocean** is shaded a flat pastel blue (`ax.patch`, since land geometries
  are drawn on top and don't cover water) rather than left the neutral
  basemap tone the rest of this repo's scripts use, since there's no
  temperature/index raster here competing for attention underneath it.
