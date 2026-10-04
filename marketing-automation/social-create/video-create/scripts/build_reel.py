#!/usr/bin/env python3
"""Build the final reel from a raw clip: scale to 1080x1920, burn a PIL text overlay,
append the Bhookle end card. Encodes the learnings (L8: dims/fps/audio normalize;
L1-L3: text composited not baked; logo bottom bar).

design.json schema:
{
  "hero": [["Her haleem takes", 72, "white"], ["6 hours.", 72, "white"]],
  "h2": "Order from Chef D. Sample",
  "cta": "Download the Bhookle app",
  "badge": "Rath Yatra 2026"     # optional
}

Usage:
  build_reel.py --raw raw.mp4 --post IG-010 --design design.json --out final.mp4
"""
import argparse, json, os, subprocess, tempfile
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
ENDCARD = os.path.join(ROOT, "_templates/Video/bhookle-end-card.mp4")
LOGO = os.path.join(ROOT, "_templates/Logo/bhookle-logo-orange-small.png")
W, H = 1080, 1920
PURPLE = (112, 48, 160); ORANGE = (255, 140, 0)
COLORS = {"white": (255, 255, 255), "orange": ORANGE, "cream": (240, 220, 180), "gold": (255, 190, 90)}


def F(sz):
    return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", sz)


def make_overlay(design, path):
    assert "bhookleeats" not in json.dumps(design).lower(), "URL found in design — banned (L5)"
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(c)
    MX, barH = 60, 110
    hero = design.get("hero", [])
    hero_h = sum(int(s * 1.18) for _, s, _ in hero)
    h2 = design.get("h2"); h2f = F(44)
    bb = d.textbbox((0, 0), h2 or "", font=h2f); h2h = (bb[3] - bb[1]) + 28 if h2 else 0
    total = hero_h + (36 + h2h if h2 else 0)
    top = (H - barH - 80) - total
    gs = max(0, top - 140)
    for y in range(gs, H):
        a = int(235 * ((y - gs) / (H - gs)) ** 0.55)
        d.rectangle([0, y, W, y + 1], fill=(8, 4, 16, a))
    y = top
    for text, sz, col in hero:
        d.text((MX, y), text, font=F(sz), fill=COLORS.get(col, (255, 255, 255)) + (255,))
        y += int(sz * 1.18)
    if h2:
        ly = y + 36
        d.rounded_rectangle([MX, ly, MX + (bb[2] - bb[0]) + 44, ly + h2h], radius=10, fill=ORANGE + (255,))
        d.text((MX + 22, ly + 14 - bb[1]), h2, font=h2f, fill=(255, 255, 255, 255))
    # CTA bar + logo right-aligned (L2)
    d.rectangle([0, H - barH, W, H], fill=PURPLE + (255,))
    cta = design.get("cta", "Download the Bhookle app")
    cf = F(48); cb = d.textbbox((0, 0), cta, font=cf)
    d.text((MX, H - barH + (barH - (cb[3] - cb[1])) // 2 - cb[1]), cta, font=cf, fill=(255, 255, 255, 255))
    if os.path.exists(LOGO):
        lg = Image.open(LOGO).convert("RGBA"); r = 70 / lg.width
        lg = lg.resize((70, int(lg.height * r)), Image.LANCZOS)
        c.paste(lg, (W - 70 - 40, H - barH + (barH - lg.height) // 2), lg)
    if design.get("badge"):
        bf = F(28); bt = design["badge"]; bbb = d.textbbox((0, 0), bt, font=bf)
        bw, bh = bbb[2] - bbb[0], bbb[3] - bbb[1]
        bx2 = W - 28; bx1 = bx2 - bw - 36
        d.rounded_rectangle([bx1, 28, bx2, 28 + bh + 20], radius=8, fill=ORANGE + (235,))
        d.text((bx1 + 18, 28 + 10 - bbb[1]), bt, font=bf, fill=(255, 255, 255, 255))
    c.save(path, "PNG")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--post", required=True)
    ap.add_argument("--design", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    design = json.load(open(a.design))

    tmp = tempfile.mkdtemp()
    ov = os.path.join(tmp, "ov.png"); make_overlay(design, ov)
    body = os.path.join(tmp, "body.mp4"); endn = os.path.join(tmp, "end.mp4")

    # L8: scale to 1080x1920, overlay, normalize fps=24 + AAC 44.1k. Quoted maps (L11).
    subprocess.run(["ffmpeg", "-y", "-i", a.raw, "-i", ov, "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v0];"
        "[v0][1:v]overlay=0:0,fps=24[v]",
        "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", body], check=True, timeout=180)

    subprocess.run(["ffmpeg", "-y", "-i", ENDCARD, "-f", "lavfi", "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100", "-map", "0:v", "-map", "1:a",
        "-shortest", "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", endn],
        check=True, timeout=120)

    cat = os.path.join(tmp, "c.txt")
    open(cat, "w").write(f"file '{body}'\nfile '{endn}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cat,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", "-c:a", "aac", "-ar", "44100",
        a.out], check=True, timeout=180)
    print(f"REEL_OK {a.out}")


if __name__ == "__main__":
    main()
