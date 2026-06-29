#!/usr/bin/env python3
"""
Download imagery trios (.tif, .jpg, .json) from the Vantor Open Data Program.

Each "scene" in an event consists of three objects sharing the same ID:
    <SCENE_ID>.tif   Cloud-Optimized GeoTIFF (the imagery, 2-55 GB each)
    <SCENE_ID>.jpg   browse thumbnail
    <SCENE_ID>.json  STAC metadata (footprint, capture date, pre/post phase, ...)

The script discovers scenes live from the public S3 bucket (no AWS account or
credentials required), so it stays in sync if Vantor adds more imagery.

Data license: CC-BY-NC-4.0 (attribution required, non-commercial use only).

Examples
--------
List what's available without downloading anything:
    python download_vantor_event.py --list

Download the 3 smallest scenes (good for a quick test):
    python download_vantor_event.py --limit 3

Download 5 scenes into a specific folder, largest first:
    python download_vantor_event.py --limit 5 --order largest -o ./venezuela

Download only the metadata + thumbnails (skip the giant .tif files):
    python download_vantor_event.py --limit 10 --skip-ext tif

Build a pre/post overlap table (which before-image matches which after-image)
and write it to a CSV (requires shapely -- see requirements.txt):
    python download_vantor_event.py --pairs
    python download_vantor_event.py --pairs --min-overlap 50 --pairs-out pairs.csv

Interrupted download? Just re-run the same command -- finished files are
skipped and partial .tif files resume where they left off.
"""

import argparse
import csv
import json
import math
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict

BUCKET_URL = "https://vantor-opendata.s3.amazonaws.com"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
DEFAULT_EVENT = "Venezuela-Earthquake-Jun-2026"
TRIO = ("json", "jpg", "tif")  # download order: small metadata first, big tif last


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def list_scenes(event):
    """Return {scene_id: {ext: (key, size)}} by listing the S3 bucket prefix."""
    prefix = f"events/{event}/"
    scenes = defaultdict(dict)
    token = None
    while True:
        url = f"{BUCKET_URL}/?list-type=2&prefix={prefix}&max-keys=1000"
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token)
        with urllib.request.urlopen(url, timeout=60) as resp:
            root = ET.fromstring(resp.read())
        for c in root.findall(S3_NS + "Contents"):
            key = c.find(S3_NS + "Key").text
            size = int(c.find(S3_NS + "Size").text)
            base = key.split("/")[-1]
            if "." not in base or base == "collection.json":
                continue
            sid, ext = base.rsplit(".", 1)
            scenes[sid][ext] = (key, size)
        if root.find(S3_NS + "IsTruncated").text == "true":
            token = root.find(S3_NS + "NextContinuationToken").text
        else:
            break
    return scenes


def fetch_item(key):
    """Read a scene's STAC .json and return the full parsed dict (or None)."""
    url = f"{BUCKET_URL}/{urllib.parse.quote(key)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            return json.load(resp)
    except Exception:
        return None


def fetch_metadata(key):
    """Return (phase, datetime) for a scene. Best-effort."""
    item = fetch_item(key)
    if not item:
        return "?", "?"
    props = item.get("properties", {})
    return props.get("phase", "?"), props.get("datetime", "?")


def _local_projector(items):
    """Return a fn(lon, lat) -> (x_km, y_km) equal-area about the data's center.

    Footprints are in lon/lat degrees; computing areas directly in degrees is
    distorted. We project to kilometers about the mean latitude so overlap
    percentages and areas are geographically meaningful for this small region.
    """
    lats = [it["bbox"][1] for it in items] + [it["bbox"][3] for it in items]
    lat0 = math.radians(sum(lats) / len(lats))
    kx = 111.320 * math.cos(lat0)  # km per degree longitude at this latitude
    ky = 110.574                   # km per degree latitude
    return lambda lon, lat: (lon * kx, lat * ky)


def build_pairs(scenes, min_overlap):
    """Compute pre<->post footprint overlaps. Returns (rows, summary).

    Each row pairs one POST scene with one overlapping PRE scene. POST scenes
    with no qualifying PRE overlap get a single row with empty pre_* fields so
    coverage gaps stay visible in the CSV.
    """
    try:
        from shapely.geometry import shape
        from shapely.ops import transform as shp_transform
    except ImportError:
        sys.exit(
            "This needs shapely. Install it:\n"
            "    pip install -r requirements.txt   (or: pip install shapely)"
        )

    print("Reading footprints for all scenes ...")
    items = {}
    for sid in scenes:
        it = fetch_item(scenes[sid]["json"][0])
        if it and it.get("geometry"):
            items[sid] = it
    if not items:
        sys.exit("Could not read any scene geometries.")

    project = _local_projector(list(items.values()))

    def prep(sid):
        geom = shp_transform(project, shape(items[sid]["geometry"]))
        if not geom.is_valid:
            geom = geom.buffer(0)  # fix self-touching strip polygons
        return geom

    geoms = {sid: prep(sid) for sid in items}
    phase = {sid: items[sid]["properties"].get("phase", "?") for sid in items}
    when = {sid: items[sid]["properties"].get("datetime", "") for sid in items}

    def tif_gb(sid):
        return round(scenes[sid].get("tif", ("", 0))[1] / 1e9, 2)

    pre = [s for s in items if phase[s] == "pre"]
    post = [s for s in items if phase[s] == "post"]

    rows = []
    matched_post = 0
    for po in sorted(post, key=lambda s: when[s]):
        pg = geoms[po]
        po_area = pg.area
        hits = []
        for pr in pre:
            inter = pg.intersection(geoms[pr]).area
            if inter <= 0:
                continue
            pct_post = 100 * inter / po_area if po_area else 0
            if pct_post < min_overlap:
                continue
            pct_pre = 100 * inter / geoms[pr].area if geoms[pr].area else 0
            hits.append((pr, pct_post, pct_pre, inter))
        hits.sort(key=lambda x: -x[1])
        if hits:
            matched_post += 1
            for rank, (pr, pct_post, pct_pre, inter) in enumerate(hits, 1):
                rows.append(
                    {
                        "post_id": po, "post_datetime": when[po], "post_tif_gb": tif_gb(po),
                        "pre_id": pr, "pre_datetime": when[pr], "pre_tif_gb": tif_gb(pr),
                        "pct_of_post_covered": round(pct_post, 1),
                        "pct_of_pre_covered": round(pct_pre, 1),
                        "overlap_km2": round(inter, 2),
                        "rank_for_post": rank,
                        "best_match": rank == 1,
                    }
                )
        else:
            rows.append(
                {
                    "post_id": po, "post_datetime": when[po], "post_tif_gb": tif_gb(po),
                    "pre_id": "", "pre_datetime": "", "pre_tif_gb": "",
                    "pct_of_post_covered": 0, "pct_of_pre_covered": "",
                    "overlap_km2": 0, "rank_for_post": 0, "best_match": False,
                }
            )
    summary = {"pre": len(pre), "post": len(post), "matched_post": matched_post}
    return rows, summary


def _stream_once(url, dest, have, size):
    """Append one HTTP (range) response to dest. Returns new byte count on disk.

    Raises on any network error. Does NOT guarantee completeness -- the caller
    checks the size and retries, because a dropped connection ends the read loop
    with an empty chunk and no exception (this is what silently truncated files).
    """
    headers, mode = {}, "wb"
    if have > 0:
        headers["Range"] = f"bytes={have}-"
        mode = "ab"
    req = urllib.request.Request(url, headers=headers)
    done = have
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, mode) as f:
        while True:
            chunk = resp.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if size:
                pct = 100 * done / size
                sys.stdout.write(f"\r      {pct:5.1f}%  {human(done)} / {human(size)}   ")
                sys.stdout.flush()
    if size:
        sys.stdout.write("\n")
    return os.path.getsize(dest)


def download(key, size, dest, resume=True, max_retries=8):
    """Download an object to dest, verifying the final size and resuming on
    truncation. Returns True on success, False if it could not be completed.

    A single HTTP stream can end early (server/connection drop) without raising,
    leaving a partial file. So we loop: stream, check the on-disk size against the
    expected size, and re-request the remaining bytes via HTTP Range until the file
    is complete or retries are exhausted.
    """
    url = f"{BUCKET_URL}/{urllib.parse.quote(key)}"
    name = os.path.basename(dest)
    have = os.path.getsize(dest) if os.path.exists(dest) else 0

    if size and have == size:
        print(f"    skip (complete)  {name}  {human(size)}")
        return True
    if size and have > size:
        print(f"    re-getting {name}: local file larger than expected, restarting")
        os.remove(dest)
        have = 0

    if not resume:
        have = 0
        if os.path.exists(dest):
            os.remove(dest)

    if have > 0:
        print(f"    resume @ {human(have)} / {human(size)}  {name}")
    else:
        print(f"    get  {name}  {human(size)}")

    attempt = 0
    while True:
        try:
            have = _stream_once(url, dest, have, size)
        except Exception as e:
            attempt += 1
            have = os.path.getsize(dest) if os.path.exists(dest) else 0
            if attempt > max_retries:
                print(f"    FAILED {name} after {max_retries} retries ({have}/{size} bytes): {e}")
                print(f"    -> re-run the same command to resume from {human(have)}.")
                return False
            print(f"    interrupted ({e}); retry {attempt}/{max_retries}, resuming @ {human(have)}")
            continue

        if not size or have == size:
            return True

        # Stream ended early with no exception -> truncated. Resume the rest.
        attempt += 1
        if attempt > max_retries:
            print(f"    FAILED {name}: stopped at {human(have)} / {human(size)} after {max_retries} retries.")
            print(f"    -> re-run the same command to resume from {human(have)}.")
            return False
        print(f"    incomplete ({human(have)} / {human(size)}); retry {attempt}/{max_retries}, resuming")


def main():
    p = argparse.ArgumentParser(
        description="Download .tif/.jpg/.json trios from a Vantor Open Data event.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--event", default=DEFAULT_EVENT, help=f"event name (default: {DEFAULT_EVENT})")
    p.add_argument("--limit", type=int, default=3, help="number of scenes to download (default: 3)")
    p.add_argument("-o", "--output", default=None, help="output directory (default: ./<event>)")
    p.add_argument(
        "--order",
        choices=("smallest", "largest", "name"),
        default="smallest",
        help="which scenes to pick first (default: smallest .tif first)",
    )
    p.add_argument(
        "--skip-ext",
        action="append",
        default=[],
        metavar="EXT",
        help="extension to skip, e.g. --skip-ext tif (repeatable)",
    )
    p.add_argument(
        "--phase",
        choices=("pre", "post", "any"),
        default="any",
        help="only consider pre, post, or all scenes (default: any)",
    )
    p.add_argument("--list", action="store_true", help="just list scenes, download nothing")
    p.add_argument(
        "--pairs",
        action="store_true",
        help="compute pre/post footprint overlaps and write a CSV (downloads nothing)",
    )
    p.add_argument("--pairs-out", default=None, help="CSV path for --pairs (default: <event>_pairs.csv)")
    p.add_argument(
        "--min-overlap",
        type=float,
        default=0.0,
        metavar="PCT",
        help="for --pairs, keep matches covering at least PCT%% of the post scene (default: 0)",
    )
    p.add_argument("--no-resume", action="store_true", help="re-download partial files instead of resuming")
    args = p.parse_args()

    print(f"Discovering scenes for event: {args.event} ...")
    scenes = list_scenes(args.event)
    if not scenes:
        sys.exit(f"No scenes found. Check the event name. See {BUCKET_URL}/events/catalog.json")

    def tif_size(sid):
        return scenes[sid].get("tif", ("", 0))[1]

    ids = list(scenes)
    if args.order == "smallest":
        ids.sort(key=tif_size)
    elif args.order == "largest":
        ids.sort(key=tif_size, reverse=True)
    else:
        ids.sort()

    total = sum(tif_size(s) for s in scenes)
    print(f"Found {len(scenes)} scenes, {human(total)} total (.tif).\n")

    if args.phase != "any" and not args.pairs:
        print(f"Filtering to phase = {args.phase} ...")
        ids = [sid for sid in ids if fetch_metadata(scenes[sid]["json"][0])[0] == args.phase]
        print(f"{len(ids)} scene(s) match phase = {args.phase}.\n")
        if not ids:
            sys.exit(f"No scenes with phase = {args.phase}.")

    if args.pairs:
        rows, summary = build_pairs(scenes, args.min_overlap)
        out = args.pairs_out or f"{args.event}_pairs.csv"
        fields = [
            "post_id", "post_datetime", "post_tif_gb",
            "pre_id", "pre_datetime", "pre_tif_gb",
            "pct_of_post_covered", "pct_of_pre_covered", "overlap_km2",
            "rank_for_post", "best_match",
        ]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        gaps = summary["post"] - summary["matched_post"]
        print(
            f"\n{summary['pre']} pre, {summary['post']} post scenes. "
            f"{summary['matched_post']} post scenes have a matching pre scene; "
            f"{gaps} have no pre coverage"
            + (f" at >={args.min_overlap:g}% overlap" if args.min_overlap else "")
            + "."
        )
        print(f"Wrote {len(rows)} pairing rows -> {os.path.abspath(out)}")
        print("Columns: post_*, pre_*, pct_of_post_covered (key for 'same area'),")
        print("         pct_of_pre_covered, overlap_km2, rank_for_post, best_match.")
        return

    if args.list:
        print("Reading per-scene metadata (phase / capture date) ...\n")
        print(f"  {'SCENE ID':<18} {'PHASE':<5} {'TIF SIZE':>9}   CAPTURE DATE (UTC)")
        print(f"  {'-'*18} {'-'*5} {'-'*9}   {'-'*19}")
        phase_count = defaultdict(int)
        for sid in ids:
            phase, dt = fetch_metadata(scenes[sid]["json"][0])
            phase_count[phase] += 1
            print(f"  {sid:<18} {phase:<5} {human(tif_size(sid)):>9}   {dt}")
        breakdown = ", ".join(f"{n} {ph}" for ph, n in sorted(phase_count.items()))
        print(f"\n{len(ids)} scenes ({breakdown}). Total if you take all: {human(total)}.")
        print("Use --limit N to download (smallest .tif first; --order to change).")
        return

    selected = ids[: args.limit]
    sel_bytes = sum(
        sz for sid in selected for ext, (_, sz) in scenes[sid].items() if ext not in args.skip_ext
    )
    outdir = args.output or os.path.join(".", args.event)
    os.makedirs(outdir, exist_ok=True)

    print(f"Downloading {len(selected)} scene(s) -> {os.path.abspath(outdir)}")
    print(f"Approx. download size: {human(sel_bytes)}")
    if args.skip_ext:
        print(f"Skipping extensions: {', '.join(args.skip_ext)}")
    print()

    failed = []
    for i, sid in enumerate(selected, 1):
        print(f"[{i}/{len(selected)}] scene {sid}")
        for ext in TRIO:
            if ext in args.skip_ext or ext not in scenes[sid]:
                continue
            key, size = scenes[sid][ext]
            dest = os.path.join(outdir, os.path.basename(key))
            ok = download(key, size, dest, resume=not args.no_resume)
            if not ok:
                failed.append(os.path.basename(key))
        print()

    if failed:
        print(f"INCOMPLETE: {len(failed)} file(s) did not finish: {', '.join(failed)}")
        print("Re-run the exact same command to resume the unfinished files.")
        print("Reminder: data is CC-BY-NC-4.0 -- attribute Vantor/Maxar, non-commercial use only.")
        sys.exit(1)

    print("Done -- all selected files downloaded and size-verified.")
    print("Reminder: data is CC-BY-NC-4.0 -- attribute Vantor/Maxar, non-commercial use only.")


if __name__ == "__main__":
    main()
