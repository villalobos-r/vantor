# Vantor Open Data — Venezuela Earthquake (Jun 2026) Toolkit

Tooling to browse, download, and pre/post-match high-resolution satellite imagery
from the **Vantor Open Data Program** (Vantor = the rebranded Maxar Intelligence),
focused on the **Venezuela-Earthquake-Jun-2026** event.

The data is a public, anonymous-access STAC catalog hosted on S3:
<https://vantor-opendata.s3.amazonaws.com/> — no AWS account or credentials needed.

> **License:** Imagery is **CC-BY-NC-4.0** — attribution to Vantor/Maxar required,
> **non-commercial use only**.

---

## 1. Project scope

The goal is to obtain imagery for the Venezuela earthquake of **2026-06-24** and be
able to show **the same geographic area before and after the disaster**.

The event contains **35 scenes (~260 GB)**:

- **10 `pre` scenes** — captured Nov 2025 → May 2026 (baseline, before the quake).
- **25 `post` scenes** — captured 2026-06-25 onward (after the quake).

Each scene is a trio of objects sharing one ID:

| File | What it is | Typical size |
|------|------------|--------------|
| `<SCENE_ID>.tif`  | Cloud-Optimized GeoTIFF — the actual imagery (RGB, ~0.5 m) | 2.3 – 51 GB |
| `<SCENE_ID>.jpg`  | Browse thumbnail | ~30 KB |
| `<SCENE_ID>.json` | STAC metadata: footprint, capture date, `phase` (pre/post), cloud cover, view angles | ~5–11 KB |

There is **no explicit field linking a pre scene to its post counterpart** — matching
must be done **spatially**, by overlapping the footprint polygons. The `--pairs` mode
does this and writes a CSV (see section 5).

---

## 2. Requirements & setup

- **Python 3** (standard library only for download/list).
- **shapely** — required **only** for `--pairs` (footprint overlap math).

```bash
pip install -r requirements.txt
```

---

## 3. How the script works

`download_vantor_event.py` talks to the bucket over plain HTTPS:

1. **Discovery** — lists the event's objects via the S3 REST API
   (`?list-type=2&prefix=events/<event>/`), groups them into scenes by ID, and
   records each member's size. This runs for every command, so the script always
   reflects the current bucket contents.
2. **Selection** — sorts scenes (`--order`), optionally filters by `--phase`, and
   takes the first `--limit`.
3. **Download** — streams each file in 1 MiB chunks (constant memory, even for the
   51 GB scene), printing a live percentage. Downloads are **serial** (one file at
   a time) by design.
   - **Resume-safe:** re-running the same command skips already-complete files and
     resumes a partial `.tif` via an HTTP `Range` request.
4. **Pairing (`--pairs`)** — fetches only the small `.json` metadata for every scene
   (not the `.tif`s), projects the footprint polygons to a local equal-area frame,
   computes pre↔post intersections, and writes a CSV.

> `--pairs` is **independent of downloading** — it reads metadata fresh from the
> bucket and never touches your downloaded files. Run it any time.

---

## 4. Flags reference

| Flag | Default | Description |
|------|---------|-------------|
| `--event NAME` | `Venezuela-Earthquake-Jun-2026` | Event/collection to operate on. Other events exist in the same bucket (e.g. `DRC-Ebola-May-2026`). |
| `--limit N` | `3` | Number of scenes to download. |
| `-o`, `--output DIR` | `./<event>` | Output directory. Created if missing. |
| `--order {smallest,largest,name}` | `smallest` | Which scenes to pick first. `smallest`/`largest` sort by `.tif` size; `name` sorts by scene ID. |
| `--phase {pre,post,any}` | `any` | Restrict to before-event (`pre`), after-event (`post`), or all scenes. Applies to `--list` and downloads. |
| `--skip-ext EXT` | (none) | Skip a file type, e.g. `--skip-ext tif` for metadata + thumbnails only. Repeatable. |
| `--list` | — | List matching scenes (with phase + capture date) and exit; downloads nothing. |
| `--pairs` | — | Compute the pre/post overlap table and write a CSV; downloads nothing. |
| `--pairs-out PATH` | `./<event>_pairs.csv` | Output path for the `--pairs` CSV. |
| `--min-overlap PCT` | `0` | For `--pairs`, keep only matches covering at least `PCT`% of the post scene. |
| `--no-resume` | — | Re-download partial files from scratch instead of resuming. |

### Common commands

```bash
# Inventory all scenes with phase + capture date
python download_vantor_event.py --list

# List only the before-event scenes
python download_vantor_event.py --phase pre --list

# Download the smallest pre scene (full trio)
python download_vantor_event.py --phase pre --order smallest --limit 1 -o ./venezuela

# Download EVERYTHING (35 scenes, ~260 GB, serial, full trios)
python download_vantor_event.py --limit 35 -o ./venezuela

# Metadata + thumbnails only (no giant .tif files)
python download_vantor_event.py --limit 35 --skip-ext tif -o ./venezuela

# Build the pre/post pairing table
python download_vantor_event.py --pairs

# Pairing table, strong matches only (>=50% of post footprint covered)
python download_vantor_event.py --pairs --min-overlap 50
```

---

## 5. The pairing table (CSV) — column reference

`--pairs` writes one row per **post ↔ pre footprint overlap**. A post scene that
overlaps several pre scenes produces several rows (ranked). A post scene with **no**
pre overlap gets a single row with the `pre_*` fields left blank, so coverage gaps
stay visible.

Overlap geometry uses **true polygon intersection** (via shapely), with footprints
projected from lon/lat degrees into a **local equal-area frame (km)** about the
event's center — so percentages and areas are geographically accurate, not distorted
by latitude.

| Column | Meaning |
|--------|---------|
| `post_id` | Scene ID of the **after-disaster** (post) image. |
| `post_datetime` | Capture timestamp (UTC) of the post scene. |
| `post_tif_gb` | Size of the post `.tif` in GB. |
| `pre_id` | Scene ID of the matched **before-disaster** (pre) image. **Blank** if the post scene has no pre overlap. |
| `pre_datetime` | Capture timestamp (UTC) of the pre scene. |
| `pre_tif_gb` | Size of the pre `.tif` in GB. |
| `pct_of_post_covered` | **% of the post footprint that the pre scene covers.** This is the key metric for "same area before/after" — higher means more of the after-image has a matching before-image. |
| `pct_of_pre_covered` | % of the pre footprint that falls inside the post scene (the reverse direction; useful when a large pre baseline covers many small post scenes). |
| `overlap_km2` | Actual overlapping area in square kilometers. |
| `rank_for_post` | Ranking of this pre match for the given post scene: `1` = best (largest `pct_of_post_covered`), `2`, `3`, … . `0` for a no-match row. |
| `best_match` | `True` for the top (`rank_for_post = 1`) pre match per post scene; `False` otherwise. |

### Using the table

- For a quick one-pre-per-post shortlist, filter `best_match = True`.
- For stricter quality, sort by `pct_of_post_covered` descending and keep what clears
  your threshold (or pre-trim with `--min-overlap`).
- **Caveats:**
  - Overlapping footprints tell you *which files to pair*; a true side-by-side still
    requires clipping/reprojecting both COGs to a common grid.
  - High overlap does not guarantee the area is cloud-free — check `eo:cloud_cover`
    in each scene's `.json` if that matters.

---

## 6. Files in this repo

| File | Purpose |
|------|---------|
| `download_vantor_event.py` | The browse / download / pairing tool. |
| `requirements.txt` | Python dependencies (shapely, for `--pairs`). |
| `README.md` | This file. |
| `CONTEXT.md` | Working notes / state for resuming the task on another machine. |
