#!/usr/bin/env python3
"""
stamp_logo.py — Composite Bhookle logo onto a campaign hero image.

Stamps the official logo-full-orange.png onto the top-left of the hero image
with a semi-transparent dark scrim behind it for contrast. Output replaces
hero.png so the email has no separate header section — logo is baked in.

Usage:
  python3 stamp_logo.py <campaign_slug>
  python3 stamp_logo.py cold-start-first-order
"""

from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image, ImageDraw

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"
LOGO_SRC = SCRIPT_DIR.parent / "templates" / "logo-full-orange.png"

# Logo width as fraction of hero width — reads well at 600px email width
LOGO_WIDTH_RATIO = 0.32   # ~192px on a 600px-wide hero
PADDING = 20              # px from top-left corner
SCRIM_PADDING = 12        # extra space around logo inside the scrim
SCRIM_ALPHA = 160         # 0-255 — 160 = ~63% opaque dark scrim for clear contrast
SCRIM_RADIUS = 12         # rounded corners on scrim


def round_rect_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (size[0] - 1, size[1] - 1)], radius=radius, fill=255)
    return mask


def stamp_logo(slug: str) -> Path:
    campaign_dir = EMAIL_MARKETING / "campaigns" / slug
    hero_path = campaign_dir / "hero.png"
    out_path = campaign_dir / "hero.png"  # overwrite in place

    if not hero_path.is_file():
        sys.exit(f"error: hero.png not found at {hero_path}")
    if not LOGO_SRC.is_file():
        sys.exit(f"error: logo not found at {LOGO_SRC}")

    hero = Image.open(hero_path).convert("RGBA")
    logo_src = Image.open(LOGO_SRC).convert("RGBA")

    # Resize logo proportionally
    logo_w = int(hero.width * LOGO_WIDTH_RATIO)
    ratio = logo_w / logo_src.width
    logo_h = int(logo_src.height * ratio)
    logo = logo_src.resize((logo_w, logo_h), Image.LANCZOS)

    # Build scrim (dark rounded rect behind logo)
    scrim_w = logo_w + SCRIM_PADDING * 2
    scrim_h = logo_h + SCRIM_PADDING * 2
    scrim = Image.new("RGBA", (scrim_w, scrim_h), (0, 0, 0, 0))
    scrim_fill = Image.new("RGBA", (scrim_w, scrim_h), (0, 0, 0, SCRIM_ALPHA))
    mask = round_rect_mask((scrim_w, scrim_h), SCRIM_RADIUS)
    scrim.paste(scrim_fill, mask=mask)

    # Composite scrim then logo onto hero
    sx = PADDING
    sy = PADDING
    hero.paste(scrim, (sx, sy), scrim)
    hero.paste(logo, (sx + SCRIM_PADDING, sy + SCRIM_PADDING), logo)

    # Save as PNG (preserves quality; email clients handle fine)
    out = hero.convert("RGB")
    out.save(out_path, "PNG", optimize=True)
    print(f"Stamped logo onto {out_path}")
    return out_path


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 stamp_logo.py <campaign_slug>")
    stamp_logo(sys.argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
