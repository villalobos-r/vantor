#!/usr/bin/env python3
"""
Crop a full-resolution HD image centered on a lon/lat point out of a big
(Cloud-Optimized) GeoTIFF downloaded from the Vantor Open Data Program.

The scene .tif files are ~1 gigapixel (e.g. 33430 x 32222 px at ~0.36 m/pixel),
far too large to open in a normal image viewer. This tool extracts a small
window around a coordinate you choose and writes an ordinary JPG/PNG you can
open anywhere -- a real "zoom in" at native detail, not a downsample of the
whole scene.

Requires GDAL (`gdal_translate`, `gdalinfo`) on PATH -- the same GDAL that ships
with QGIS / OSGeo4W. The easiest way is to run this from the **OSGeo4W Shell**.
On Windows it will also auto-detect a standard `C:\\OSGeo4W\\bin` install.

How the crop is sized
---------------------
You give a center coordinate and an output size in pixels (default 1920x1080).
`--scale` controls how much ground the crop covers:

    --scale 1   (default)  1 output px = 1 source px  -> maximum detail,
                           ~690 m x 390 m on the ground for a 1920x1080 crop.
    --scale 4              covers 4x more ground in each direction (downsampled).
    --scale 0.5           covers half as much (upsampled / extra zoom).

Specifying the center
---------------------
Two ways, pick whichever matches how you got the coordinate:

    --latlon "10.6115633,-66.8431920"   exactly as copied from Google Maps / QGIS
                                         (lat,lon order, comma-separated)
    --center -66.8431920 10.6115633      lon then lat, space-separated (GIS order)

Both accept full precision -- more decimals just means a more exact location.

Examples
--------
    python crop_hd.py venezuela/B130001101BE2A00.tif --latlon "10.6115633,-66.8431920"
    python crop_hd.py venezuela/B130001101BE2A00.tif --latlon "10.6115633,-66.8431920" --size 2560 1440
    python crop_hd.py venezuela/B130001101BE2A00.tif --center -66.84 10.60 --scale 4 -o wide.jpg
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys


def gdal_tool(name):
    """Find a GDAL CLI tool: PATH first, then a standard Windows OSGeo4W install."""
    found = shutil.which(name) or shutil.which(name + ".exe")
    if found:
        return found
    for d in (r"C:\OSGeo4W\bin", r"C:\OSGeo4W64\bin"):
        cand = os.path.join(d, name + ".exe")
        if os.path.exists(cand):
            return cand
    return None


def raster_info(gdalinfo, tif):
    """Return (size_x, size_y, geotransform) for a north-up raster."""
    r = subprocess.run([gdalinfo, "-json", tif], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gdalinfo failed on {tif}:\n{r.stderr.strip()}")
    d = json.loads(r.stdout)
    sx, sy = d["size"]
    gt = d["geoTransform"]  # [originX, pixelW, rotX, originY, rotY, pixelH]
    return sx, sy, gt


def main():
    p = argparse.ArgumentParser(
        description="Crop an HD image centered on lon/lat from a big GeoTIFF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("tif", help="path to a downloaded scene .tif")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--latlon", metavar='"LAT,LON"',
        help='center as copied from Google Maps/QGIS, e.g. --latlon "10.6115633,-66.8431920"',
    )
    g.add_argument(
        "--center", nargs=2, type=float, metavar=("LON", "LAT"),
        help="center as lon lat (GIS order), e.g. --center -66.8431920 10.6115633",
    )
    p.add_argument(
        "--size", nargs=2, type=int, default=(1920, 1080), metavar=("W", "H"),
        help="output image size in pixels (default: 1920 1080)",
    )
    p.add_argument(
        "--scale", type=float, default=1.0,
        help="source pixels per output pixel: 1=native detail, >1=more ground, <1=extra zoom (default: 1)",
    )
    p.add_argument("-o", "--output", default=None, help="output image path (default: <tif>_<lon>_<lat>.jpg)")
    p.add_argument("--format", choices=("jpg", "png"), default="jpg", help="output format (default: jpg)")
    p.add_argument("--quality", type=int, default=90, help="JPEG quality 1-100 (default: 90)")
    args = p.parse_args()

    if not os.path.exists(args.tif):
        sys.exit(f"File not found: {args.tif}")
    gt_tool = gdal_tool("gdal_translate")
    gi_tool = gdal_tool("gdalinfo")
    if not gt_tool or not gi_tool:
        sys.exit("GDAL not found. Run from the OSGeo4W Shell, or add GDAL to PATH.")

    if args.latlon:
        parts = args.latlon.replace(" ", "").split(",")
        if len(parts) != 2:
            sys.exit('--latlon must be "LAT,LON", e.g. --latlon "10.6115633,-66.8431920"')
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            sys.exit(f"Could not parse --latlon value: {args.latlon!r}")
    else:
        lon, lat = args.center
    out_w, out_h = args.size
    sx, sy, gt = raster_info(gi_tool, args.tif)
    origin_x, pix_w, _, origin_y, _, pix_h = gt  # pix_h is negative (north-up)

    # Map the center lon/lat to fractional pixel coordinates.
    col = (lon - origin_x) / pix_w
    row = (lat - origin_y) / pix_h
    if not (0 <= col <= sx and 0 <= row <= sy):
        print(f"WARNING: center ({lon}, {lat}) is OUTSIDE this scene's pixel grid "
              f"({sx} x {sy}). The crop may be empty/black.")
        # Raster geographic bounds, for a helpful hint:
        x0, x1 = origin_x, origin_x + sx * pix_w
        y0, y1 = origin_y, origin_y + sy * pix_h
        print(f"         scene covers lon [{min(x0,x1):.5f}, {max(x0,x1):.5f}], "
              f"lat [{min(y0,y1):.5f}, {max(y0,y1):.5f}].")

    # Source window: out_size * scale, centered on the point.
    crop_w = max(1, round(out_w * args.scale))
    crop_h = max(1, round(out_h * args.scale))
    xoff = round(col - crop_w / 2)
    yoff = round(row - crop_h / 2)

    # Clamp the window inside the raster; warn if it had to shift/shrink.
    crop_w = min(crop_w, sx)
    crop_h = min(crop_h, sy)
    cl_x = max(0, min(xoff, sx - crop_w))
    cl_y = max(0, min(yoff, sy - crop_h))
    if (cl_x, cl_y) != (xoff, yoff):
        print("NOTE: crop window reached the scene edge; it was shifted to stay inside.")
    xoff, yoff = cl_x, cl_y

    # Ground coverage, for the user's reference.
    mx = abs(pix_w) * 111320.0 * math.cos(math.radians(lat))
    my = abs(pix_h) * 110574.0
    print(f"Scene: {sx} x {sy} px, ~{mx:.2f} m/px")
    print(f"Source window: {crop_w} x {crop_h} px at offset ({xoff}, {yoff})")
    print(f"Ground coverage: ~{crop_w*mx:.0f} m x {crop_h*my:.0f} m  ->  output {out_w} x {out_h} px")

    out = args.output or (
        f"{os.path.splitext(args.tif)[0]}_{lon}_{lat}.{args.format}"
    )
    of = "JPEG" if args.format == "jpg" else "PNG"
    # Downsampling (scale>1) -> 'average'; otherwise 'cubic'. No resample when sizes match.
    resample = "average" if args.scale > 1 else "cubic"
    cmd = [
        gt_tool, "-q", "-of", of,
        "-b", "1", "-b", "2", "-b", "3",
        "-srcwin", str(xoff), str(yoff), str(crop_w), str(crop_h),
        "-outsize", str(out_w), str(out_h),
        "-r", resample,
    ]
    if of == "JPEG":
        cmd += ["-co", f"QUALITY={args.quality}"]
    cmd += [args.tif, out]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gdal_translate failed:\n{r.stderr.strip()}")
    size = os.path.getsize(out)
    print(f"Wrote {out}  ({size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
