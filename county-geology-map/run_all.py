"""
Batch-renders the county geology series: every county in COUNTIES, one
fetch + build each (in subprocesses, so one county's failure can't stop
the run), into series/Washington/ and series/Oregon/, plus a contact sheet
and a zip.

    python3 run_all.py                    # everything
    python3 run_all.py --only "OR:Clatsop" "WA:King"
    python3 run_all.py --skip-fetch       # re-render from data/ only
"""
import argparse
import os
import subprocess
import sys
import time
import zipfile

from PIL import Image

COUNTIES = {
    "WA": ["Adams", "Asotin", "Benton", "Chelan", "Clallam", "Clark", "Columbia", "Cowlitz",
           "Douglas", "Ferry", "Franklin", "Garfield", "Grant", "Grays Harbor", "Island",
           "Jefferson", "King", "Kitsap", "Kittitas", "Klickitat", "Lewis", "Lincoln", "Mason",
           "Okanogan", "Pacific", "Pend Oreille", "Pierce", "San Juan", "Skagit", "Skamania",
           "Snohomish", "Spokane", "Stevens", "Thurston", "Wahkiakum", "Walla Walla", "Whatcom",
           "Whitman", "Yakima"],
    "OR": ["Baker", "Benton", "Clackamas", "Clatsop", "Columbia", "Coos", "Crook", "Curry",
           "Deschutes", "Douglas", "Gilliam", "Grant", "Harney", "Hood River", "Jackson",
           "Jefferson", "Josephine", "Klamath", "Lake", "Lane", "Lincoln", "Linn", "Malheur",
           "Marion", "Morrow", "Multnomah", "Polk", "Sherman", "Tillamook", "Umatilla", "Union",
           "Wallowa", "Wasco", "Washington", "Wheeler", "Yamhill"],
}
FOLDER = {"WA": "Washington", "OR": "Oregon"}
# Hand-picked extra labels for cities just outside a county (on top of the
# automatic nearby-city labels in build_map.py).
ALSO_LABEL = {("WA", "Adams"): ["Moses Lake"]}


def out_path(state, county):
    stem = county.replace(" ", "_")
    return f"series/{FOLDER[state]}/{stem}_County_{state}_Geologic_Map.png"


def run(cmd, log):
    t = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    log.write(f"$ {' '.join(cmd)}  [{time.time() - t:.0f}s, exit {p.returncode}]\n")
    log.write(p.stdout)
    if p.returncode:
        log.write(p.stderr[-3000:])
    log.flush()
    return p.returncode == 0, p.stdout + p.stderr


def contact_sheet(paths, dest, cols=8, thumb_w=270):
    thumbs = [Image.open(p).convert("RGB").resize((thumb_w, int(thumb_w * 1.25))) for p in paths]
    rows = -(-len(thumbs) // cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * int(thumb_w * 1.25)), "white")
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * thumb_w, (i // cols) * int(thumb_w * 1.25)))
    sheet.save(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help='subset, as "ST:County"')
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--zip", default="series/Pacific_NW_County_Geologic_Maps.zip")
    args = ap.parse_args()

    jobs = [(st, c) for st in ("WA", "OR") for c in COUNTIES[st]]
    if args.only:
        wanted = {tuple(x.split(":", 1)) for x in args.only}
        jobs = [j for j in jobs if j in wanted]
    os.makedirs("series", exist_ok=True)
    done, failed = [], []
    with open("series/run_log.txt", "a") as log:
        for i, (st, county) in enumerate(jobs, 1):
            print(f"[{i}/{len(jobs)}] {county}, {st}", flush=True)
            ok = True
            if not args.skip_fetch:
                ok, out = run([sys.executable, "fetch_geology.py", "--state", st,
                               "--county", county], log)
            if ok:
                cmd = [sys.executable, "build_map.py", "--state", st, "--county", county,
                       "--out", out_path(st, county)]
                for extra in ALSO_LABEL.get((st, county), []):
                    cmd += ["--also-label", extra]
                ok, out = run(cmd, log)
            (done if ok else failed).append((st, county))
            if not ok:
                print(f"   FAILED -- see series/run_log.txt: {out.strip().splitlines()[-1][:200]}")

    paths = [out_path(st, c) for st, c in done]
    if paths:
        contact_sheet(paths, "series/contact_sheet.jpg")
    all_pngs = [out_path(st, c) for st in ("WA", "OR") for c in COUNTIES[st]
                if os.path.exists(out_path(st, c))]
    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in all_pngs:
            zf.write(p, os.path.relpath(p, "series"))
    print(f"done {len(done)}, failed {len(failed)}: {failed}")
    print(f"zip: {args.zip} ({len(all_pngs)} maps)")


if __name__ == "__main__":
    main()
