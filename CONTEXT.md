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
- `crop_hd.py` — **separate** tool: extract a full-resolution HD crop centered on a
  lon/lat from a downloaded `.tif`. Stdlib only, but shells out to GDAL
  (`gdal_translate`/`gdalinfo`) — needs GDAL on PATH (OSGeo4W Shell).
  - `--latlon "LAT,LON"` (paste from Google Maps/QGIS) or `--center LON LAT` (GIS order).
  - `--size W H` (default 1920x1080), `--scale S` (1=native detail, >1=zoom out),
    `--format jpg|png`, `--quality`, `-o`.
  - At native scale (~0.35 m/px) a 1920x1080 crop ≈ 680 m x 380 m on the ground.
- `requirements.txt` — shapely.
- `README.md` — full docs incl. flag table, pairing-CSV columns, and crop_hd usage.

Design decisions (per user):
- **No parallel downloads** (serial, one file at a time).
- **No auto-skip of large scenes** — all selected scenes download in full.
- **No pair-driven download** — user is downloading everything; `--pairs` is a
  standalone reference table only.
- Pairing uses **true polygon intersection** (shapely) in a **local equal-area
  projection (km)** for accurate %/area.

## Status / where we left off

- Tooling complete and tested against the live bucket (list, phase filter, pairs CSV,
  resumable download, and `crop_hd.py` HD crops all verified).
- **Smallest pre scene downloaded and size-verified:**
  `venezuela/B130001101BE2A00.{tif,jpg,json}` (.tif ≈ 2.8 GB, 33430 x 32222 px).
- QGIS + GDAL (OSGeo4W) installed; the COG opens fine in QGIS. `crop_hd.py` tested on
  this scene — produces sharp neighborhood-scale HD crops.

## Dataset note (changed since start)
- Counts are discovered live. As of 2026-06-30 the Venezuela event had grown to
  **49 scenes / ~365 GB** (was 35 / 260 GB) — more **post** scenes; pre still 10.
  Re-run `--list` for current numbers; full download should use `--limit 49` (or higher).
- The `.tif`s are **BigTIFF COGs (~1 gigapixel)** — Windows Photos CANNOT open them.
  Use QGIS for the full file, `crop_hd.py` for HD close-ups, or the bundled `.jpg`.

## Next steps (likely)

1. On the other machine: `pip install -r requirements.txt` (+ have QGIS/OSGeo4W for GDAL).
2. Run `python download_vantor_event.py --pairs` to generate
   `Venezuela-Earthquake-Jun-2026_pairs.csv`.
3. Run the full download: `python download_vantor_event.py --limit 49 -o ./venezuela`
   (resumable — safe to re-run if interrupted). Budget ~365 GB of disk.
4. Use `crop_hd.py` (from the OSGeo4W Shell) to make HD crops of areas of interest.
5. (Optional, not built) Batch crop mode (CSV of name,lat,lon → many crops); add
   `eo:cloud_cover` columns to the pairing CSV; clip/align matched pre/post COGs.

## Quick reference

```bash
pip install -r requirements.txt
python download_vantor_event.py --list                 # inventory + phase + date
python download_vantor_event.py --phase pre --list     # pre scenes only
python download_vantor_event.py --pairs                # overlap table CSV
python download_vantor_event.py --limit 35 -o ./venezuela   # download all (~260 GB)
```
