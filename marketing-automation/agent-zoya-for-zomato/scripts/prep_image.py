#!/usr/bin/env python3
"""Prepare a generated cover image for Zomato upload.

    python prep_image.py raw.png [-o Chef_Zomato_Cover.jpg] [--width 1600]

Crops to exact 16:9, resizes, flattens any alpha channel, and strips every metadata block —
EXIF, XMP, ICC, IPTC and C2PA AI-provenance tags. Generated PNGs arrive around 10 MB with
provenance attached; output lands near 450 KB with none.
"""
import argparse, os, sys
from PIL import Image

MARKERS = {0xE0: "APP0/JFIF", 0xE1: "APP1/EXIF-XMP", 0xE2: "APP2/ICC",
           0xEB: "APP11/C2PA", 0xED: "APP13/IPTC", 0xEE: "APP14/Adobe", 0xFE: "COM"}
DIRTY = ("EXIF", "ICC", "IPTC", "C2PA", "Adobe", "COM")
NEEDLES = [b"xmpmeta", b"Exif", b"c2pa", b"jumbf", b"ICC_PROFILE",
           b"trainedAlgorithmicMedia", b"Photoshop"]


def audit(path):
    d = open(path, "rb").read()
    i, segs = 2, []
    while i < len(d) - 1:
        if d[i] != 0xFF:
            break
        m = d[i + 1]
        if m == 0xDA:
            break
        segs.append(MARKERS.get(m, hex(m)))
        i += 2 + int.from_bytes(d[i + 2:i + 4], "big")
    bad = [s for s in segs if any(k in s for k in DIRTY)]
    found = [n.decode() for n in NEEDLES if n in d]
    return segs, bad, found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("-o", "--out")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=88)
    a = ap.parse_args()

    out = a.out or os.path.splitext(os.path.basename(a.image))[0] + "_Zomato_Cover.jpg"
    im = Image.open(a.image)
    W, H = im.size
    src_mb = os.path.getsize(a.image) / 1048576
    print(f"source {W}x{H} {im.mode} {im.format}  {src_mb:.2f} MB  aspect {W/H:.4f}")
    if im.info:
        print("  metadata present:", ", ".join(k for k in im.info if k != "dpi") or "none")

    target = 16 / 9
    if W / H > target:
        nw = int(round(H * target)); off = (W - nw) // 2
        im = im.crop((off, 0, off + nw, H))
        print(f"  cropped {W-nw}px of width ({off}px each side) for exact 16:9")
    elif W / H < target:
        nh = int(round(W / target)); off = (H - nh) // 2
        im = im.crop((0, off, W, off + nh))
        print(f"  cropped {H-nh}px of height for exact 16:9")

    if im.mode != "RGB":
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
            print("  flattened alpha onto white")
        else:
            im = im.convert("RGB")

    size = (a.width, int(round(a.width * 9 / 16)))
    resized = im.resize(size, Image.LANCZOS)
    # Copy pixels into a blank image so nothing rides along from the source.
    clean = Image.new("RGB", size)
    clean.paste(resized)
    clean.save(out, "JPEG", quality=a.quality, optimize=True, progressive=True,
               exif=b"", icc_profile=None)

    b = os.path.getsize(out)
    segs, bad, found = audit(out)
    print(f"\nwrote {out}")
    print(f"  {size[0]}x{size[1]}  {b/1024:.0f} KB ({b/1048576:.3f} MB)")
    print(f"  under 5 MB: {b < 5*1024*1024}   meets 1200x500: {size[0] >= 1200 and size[1] >= 500}")
    print(f"  segments: {segs}")
    print(f"  metadata blocks: {bad or 'none'}")
    print(f"  provenance strings: {found or 'none'}")
    if bad or found:
        print("\nSomething survived the strip — do not upload until this is clean.", file=sys.stderr)
        sys.exit(1)
    print("\nClean. Check it against the compliance list in references/hero-image.md before uploading —")
    print("in particular that no dish is cropped at the frame edge, which Zomato rejects.")


if __name__ == "__main__":
    main()
