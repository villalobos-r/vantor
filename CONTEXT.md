# Working Context — Vantor Venezuela Earthquake extraction

Notes for resuming this task on another machine. For full usage see `README.md`.

## Goal

Extract satellite imagery for the **Venezuela earthquake of 2026-06-24** from the
Vantor Open Data Program and be able to show **the same area before (pre) and after
(post)** the disaster. Eventually: **download all 35 scenes (~260 GB)**.

## Data source

- Bucket: <https://vantor-opendata.s3.amazonaws.com/> (public, no credentials).
- STAC catalog. Root: `events/catalog.json`.
- Event of interest: `events/Venezuela-Earthquake-Jun-2026/`.
- License: **CC-BY-NC-4.0** (attribution, non-commercial).

## Key facts established

- Event = **35 scenes, ~260 GB** of `.tif`. Each scene = trio `.tif` + `.jpg` + `.json`.
- Split: **10 pre** (Nov 2025 – May 2026) and **25 post** (from 2026-06-25).
- `.tif` sizes range **2.3 GB → 51 GB**. Largest single file is the 51 GB pre
  baseline `10400100B979DD00`.
- Smallest **pre** scene = `B130001101BE2A00` (~2.8 GB).
- Smallest scene overall = `B110001100BB2210` (2.3 GB, **post**).
- **No explicit pre/post pairing field exists.** Matching is spatial, via footprint
  polygon overlap. Pairing is **many-to-many**, and (with true-polygon geometry)
  **11 of 25 post scenes have no pre overlap at all** — expected coverage gaps.

## Tooling built (in this repo)

- `download_vantor_event.py` — discover / list / download / pair. Stdlib only,
  except `--pairs` needs shapely.
- `requirements.txt` — shapely.
- `README.md` — full docs incl. flag table and pairing-CSV column reference.

Design decisions (per user):
- **No parallel downloads** (serial, one file at a time).
- **No auto-skip of large scenes** — all selected scenes download in full.
- **No pair-driven download** — user is downloading everything; `--pairs` is a
  standalone reference table only.
- Pairing uses **true polygon intersection** (shapely) in a **local equal-area
  projection (km)** for accurate %/area.

## Status / where we left off

- Tooling complete and tested (list, phase filter, pairs CSV, resumable download all
  verified against the live bucket).
- User was **downloading the smallest pre scene trip** as a first real test:
  `python download_vantor_event.py --phase pre --order smallest --limit 1 -o ./venezuela`
  → expected file: `venezuela/B130001101BE2A00.{tif,jpg,json}` (~2.8 GB).

## Next steps (likely)

1. On the other machine: `pip install -r requirements.txt`.
2. Run `python download_vantor_event.py --pairs` to generate
   `Venezuela-Earthquake-Jun-2026_pairs.csv`.
3. Run the full download: `python download_vantor_event.py --limit 35 -o ./venezuela`
   (resumable — safe to re-run if interrupted). Budget ~260 GB of disk.
4. (Optional, not yet built) Add `eo:cloud_cover` columns to the pairing CSV; build a
   clip/reproject step to align matched pre/post COGs for true side-by-side display.

## Quick reference

```bash
pip install -r requirements.txt
python download_vantor_event.py --list                 # inventory + phase + date
python download_vantor_event.py --phase pre --list     # pre scenes only
python download_vantor_event.py --pairs                # overlap table CSV
python download_vantor_event.py --limit 35 -o ./venezuela   # download all (~260 GB)
```
