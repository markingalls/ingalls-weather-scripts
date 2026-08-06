#!/usr/bin/env python3
"""
Parses new lines from nginx's images.ingallswx.com access log, folds them
into a small SQLite hit-count database (one row per day per image path),
and renders the /stats/ dashboard HTML from that database. Meant to be run
frequently by cron (see deploy/crontab.example) -- both steps are cheap
(incremental log read, a handful of SQL aggregates over a tiny table), so
there's no need to split "record hits" and "render dashboard" into
separate cron entries the way the image-generating projects split fetch
from publish.

Rotation-safe: tracks (inode, byte offset) in state/cursor.json rather
than just a byte offset, so a logrotate rotation (new inode) or an
in-place truncation (same inode, smaller size) both correctly restart
from the top of whatever file is current instead of silently going blind
or double-counting. The raw log itself doesn't need to be kept forever --
once a line's been folded into the SQLite database the count is
permanent, independent of whatever retention logrotate is configured
with.

No third-party dependencies -- sqlite3 and everything else used here is
stdlib.
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
CURSOR_FILE = os.path.join(STATE_DIR, "cursor.json")
DB_FILE = os.path.join(STATE_DIR, "hits.sqlite3")

LOG_PATH = "/var/log/nginx/images-access.log"
WEB_ROOT = "/var/www/images"
STATS_DIR = os.path.join(WEB_ROOT, "stats")

# nginx's stock "combined" log format:
#   $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
LOG_LINE_RE = re.compile(
    r'^(?P<addr>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) \S+" (?P<status>\d+) (?P<bytes>\d+) '
    r'"(?P<referer>[^"]*)" "(?P<agent>[^"]*)"'
)

# Only successful, real image responses count as a "hit" -- 200 is a fresh
# fetch, 304 is a conditional-GET revalidation (very common given this
# origin's Cache-Control: no-cache, and just as much a real "someone
# loaded this image" event as a 200 is). Anything else (404s, redirects,
# 5xx) is noise, not a view.
COUNTABLE_STATUSES = {"200", "304"}

# Ordered prefix/regex -> category. First match wins; extend this as new
# products get added rather than leaving them bucketed under "Other".
CATEGORY_PATTERNS = [
    (re.compile(r"^(tricities|hermiston|portland)_forecast\.png$"), "7-Day Forecasts"),
    (re.compile(r"^850mb_"), "850mb Temp Charts"),
    (re.compile(r"^western_us_spc_"), "SPC Outlooks"),
    (re.compile(r"^western_us_(temp|precip)_"), "CPC Outlooks"),
    (re.compile(r"^western_us_drought_monitor\.png$"), "Drought Monitor"),
    (re.compile(r"^western_us_wpc_precip\.png$"), "WPC Excessive Rainfall"),
    (re.compile(r"^western_us_extreme_heat_hazard\.png$"), "CPC Extreme Heat"),
]


def categorize(filename):
    for pattern, category in CATEGORY_PATTERNS:
        if pattern.match(filename):
            return category
    return "Other"


def load_cursor():
    if not os.path.exists(CURSOR_FILE):
        return None
    with open(CURSOR_FILE) as f:
        return json.load(f)


def save_cursor(inode, offset):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CURSOR_FILE, "w") as f:
        json.dump({"inode": inode, "offset": offset}, f)


def init_db(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS daily_hits ("
        "  date TEXT NOT NULL,"       # YYYY-MM-DD, UTC
        "  path TEXT NOT NULL,"       # e.g. western_us_spc_severe.png
        "  category TEXT NOT NULL,"
        "  hits INTEGER NOT NULL,"
        "  PRIMARY KEY (date, path)"
        ")"
    )
    conn.commit()


def parse_nginx_time(time_local):
    # e.g. "05/Aug/2026:19:31:59 +0000" -- always includes an explicit
    # offset, so this converts to a real UTC date regardless of whatever
    # timezone the server itself happens to be configured with.
    dt = datetime.strptime(time_local, "%d/%b/%Y:%H:%M:%S %z")
    return dt.astimezone(timezone.utc)


def read_new_lines():
    """Returns (lines, new_inode, new_offset). Rotation-safe: if the log's
    inode has changed (logrotate) or its size has shrunk below the stored
    offset (in-place truncation), starts over from the top of the current
    file instead of erroring or silently missing everything."""
    if not os.path.exists(LOG_PATH):
        return [], None, 0

    st = os.stat(LOG_PATH)
    cursor = load_cursor()
    offset = 0
    if cursor and cursor.get("inode") == st.st_ino and cursor.get("offset", 0) <= st.st_size:
        offset = cursor["offset"]

    with open(LOG_PATH, "r", errors="replace") as f:
        f.seek(offset)
        lines = f.readlines()
        new_offset = f.tell()

    return lines, st.st_ino, new_offset


def fold_lines(conn, lines):
    counts = {}  # (date, path) -> hits
    for line in lines:
        m = LOG_LINE_RE.match(line)
        if not m:
            continue
        if m.group("method") != "GET" or m.group("status") not in COUNTABLE_STATUSES:
            continue
        path = m.group("path").split("?", 1)[0].lstrip("/")
        if not path.endswith(".png") or path.startswith(".tmp_"):
            continue
        try:
            date = parse_nginx_time(m.group("time")).strftime("%Y-%m-%d")
        except ValueError:
            continue
        counts[(date, path)] = counts.get((date, path), 0) + 1

    for (date, path), hits in counts.items():
        conn.execute(
            "INSERT INTO daily_hits (date, path, category, hits) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(date, path) DO UPDATE SET hits = hits + excluded.hits",
            (date, path, categorize(path), hits),
        )
    conn.commit()
    return len(counts)


def query_scope(conn, date_filter_sql, date_filter_args):
    total = conn.execute(
        f"SELECT COALESCE(SUM(hits), 0) FROM daily_hits WHERE {date_filter_sql}", date_filter_args
    ).fetchone()[0]
    by_category = conn.execute(
        f"SELECT category, SUM(hits) AS h FROM daily_hits WHERE {date_filter_sql} "
        f"GROUP BY category ORDER BY h DESC", date_filter_args
    ).fetchall()
    by_path = conn.execute(
        f"SELECT path, category, SUM(hits) AS h FROM daily_hits WHERE {date_filter_sql} "
        f"GROUP BY path ORDER BY h DESC", date_filter_args
    ).fetchall()
    return {"total": total, "by_category": by_category, "by_path": by_path}


def build_report(conn):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    this_month = now.strftime("%Y-%m")
    this_year = now.strftime("%Y")
    return {
        "today": query_scope(conn, "date = ?", (today,)),
        "month": query_scope(conn, "substr(date, 1, 7) = ?", (this_month,)),
        "year": query_scope(conn, "substr(date, 1, 4) = ?", (this_year,)),
        "all": query_scope(conn, "1 = 1", ()),
        "generated_at": now,
        "earliest_date": conn.execute("SELECT MIN(date) FROM daily_hits").fetchone()[0],
    }


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_table(rows, columns):
    if not rows:
        return "<p class='empty'>No hits recorded yet for this period.</p>"
    head = "".join(f"<th>{esc(c)}</th>" for c in columns)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_scope_section(scope_id, label, scope, active):
    cat_table = render_table(scope["by_category"], ["Category", "Hits"])
    path_table = render_table(scope["by_path"], ["Image", "Category", "Hits"])
    display = "block" if active else "none"
    return f"""
    <section id="scope-{scope_id}" class="scope" style="display:{display}">
      <div class="total">{scope['total']:,} <span>total hits &mdash; {esc(label)}</span></div>
      <div class="tables">
        <div class="table-block">
          <h3>By category</h3>
          {cat_table}
        </div>
        <div class="table-block">
          <h3>By image</h3>
          {path_table}
        </div>
      </div>
    </section>
    """


def render_dashboard(report):
    earliest = report["earliest_date"] or "no data yet"
    generated = report["generated_at"].strftime("%Y-%m-%d %H:%M UTC")
    tabs = ["today", "month", "year", "all"]
    labels = {"today": "Today", "month": "This Month", "year": "This Year", "all": "All-Time"}

    nav = "".join(
        f'<button class="tab-btn{" active" if t == "today" else ""}" '
        f'onclick="showScope(\'{t}\')" id="btn-{t}">{labels[t]}</button>'
        for t in tabs
    )
    sections = "".join(
        render_scope_section(t, labels[t], report[t], active=(t == "today"))
        for t in tabs
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="robots" content="noindex, nofollow">
<title>Image Hit Stats — Ingalls Weather</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; background: #f7f6f2;
          color: #2b2a26; margin: 0; padding: 32px 24px 64px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .meta {{ color: #5a584f; font-size: 13px; margin-bottom: 24px; }}
  .tabs {{ margin-bottom: 20px; }}
  .tab-btn {{ background: white; border: 1px solid #ccc9bd; border-radius: 6px;
              padding: 8px 16px; margin-right: 8px; cursor: pointer; font-size: 14px; }}
  .tab-btn.active {{ background: #2b2a26; color: white; border-color: #2b2a26; }}
  .total {{ font-size: 40px; font-weight: 700; margin: 8px 0 24px; }}
  .total span {{ font-size: 14px; font-weight: 400; color: #5a584f; }}
  .tables {{ display: flex; gap: 32px; flex-wrap: wrap; }}
  .table-block {{ flex: 1; min-width: 320px; }}
  h3 {{ font-size: 15px; margin: 0 0 8px; color: #5a584f; }}
  table {{ border-collapse: collapse; width: 100%; background: white; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e3db; font-size: 14px; }}
  th {{ background: #efeee7; font-weight: 600; }}
  .empty {{ color: #8a887e; font-style: italic; }}
</style>
</head>
<body>
<h1>Image Hit Stats</h1>
<div class="meta">Generated {esc(generated)} &middot; recording since {esc(earliest)}</div>
<div class="tabs">{nav}</div>
{sections}
<script>
function showScope(id) {{
  document.querySelectorAll('.scope').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('scope-' + id).style.display = 'block';
  document.getElementById('btn-' + id).classList.add('active');
}}
</script>
</body>
</html>
"""


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(STATS_DIR, exist_ok=True)

    lines, inode, offset = read_new_lines()
    conn = sqlite3.connect(DB_FILE)
    init_db(conn)

    n_new = fold_lines(conn, lines) if lines else 0
    if inode is not None:
        save_cursor(inode, offset)

    report = build_report(conn)
    html = render_dashboard(report)

    tmp_path = os.path.join(STATS_DIR, ".tmp_index.html")
    final_path = os.path.join(STATS_DIR, "index.html")
    with open(tmp_path, "w") as f:
        f.write(html)
    os.replace(tmp_path, final_path)

    print(f"Folded {len(lines)} new log line(s) ({n_new} date/path pairs updated). "
          f"Dashboard rendered to {final_path}. All-time total: {report['all']['total']:,} hits.")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
