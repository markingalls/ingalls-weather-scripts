# Where the cron schedule in crontab.example comes from

Each product group's refresh cadence matches NOAA's own real issuance
schedule for that product, not a blind fixed interval. Sourced directly
from NOAA/SPC/CPC's own pages (checked live, not from memory):

- **SPC Day 1** (categorical, wind probability, hail probability): issued
  5x/day at 0600Z, 1300Z, 1630Z, 2000Z, 0100Z, per
  `origin-west-www-spc.woc.noaa.gov/misc/about.php`. Confirmed the wind/hail
  probability layers update on this same schedule (not less often) by
  checking a live `day1otlk_wind.kmz`'s `ISSUE_ISO` timestamp against the
  outlook page's stated issuance time for the same cycle.
- **SPC Day 2** (categorical, wind, hail): issued 2x/day, ~0600-0700Z and
  1730Z, same source.
- **SPC Day 3** (categorical only -- SPC doesn't publish separate Day 3
  wind/hail products, only a combined all-hazard "Probabilistic" outlook):
  issued 2x/day, ~0730-0830Z and 1930Z, same source.
- **SPC Fire Weather** (Day 1 and Day 2): both issued once together at
  ~2:00am CST/CDT (~0700-0800Z depending on daylight saving), per
  `origin-west-www-spc.woc.noaa.gov/misc/about.php`; Day 1 gets a separate
  update by 1700Z, Day 2 by 2000Z.
- **CPC 6-10 Day and 8-14 Day** (temp + precip): issued daily between
  3-4pm Eastern, per `cpc.ncep.noaa.gov/products/predictions/610day/` and
  `.../814day/`. Scheduled at 2100Z, which covers 3-4pm Eastern under
  both EST and EDT with margin.
- **CPC Week 3-4** (temp + precip): issued Fridays between 3-4pm Eastern,
  per `cpc.ncep.noaa.gov/products/predictions/WK34/`. Same 2100Z time,
  Fridays only.
- **U.S. Drought Monitor**: released Thursdays (long-standing NDMC
  practice; data valid as of the preceding Tuesday). Scheduled 1400Z,
  which covers the commonly-cited ~8:30am Eastern release under both EST
  and EDT with margin -- worth double-checking against actual observed
  publish times after this has run for a couple of weeks, since I
  couldn't find an explicit UTC issuance time on NDMC's own site to
  confirm precisely.

All times in crontab.example add roughly 10-15 minutes of buffer past
the stated issuance time, so the fetch isn't racing the file actually
landing on NOAA's server.
