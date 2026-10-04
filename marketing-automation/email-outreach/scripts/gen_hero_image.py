#!/usr/bin/env python3
"""
gen_hero_image.py — Generate a campaign hero image via Imagen 4 Ultra.

Usage:
  python3 gen_hero_image.py <campaign_slug> "<prompt>"
  python3 gen_hero_image.py welcome-blast "Warm Indian home kitchen, mother serving food..."

Output: email-marketing/campaigns/<slug>/hero.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent  # bhookle-marketing/
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"

MODEL = "imagen-4.0-ultra-generate-001"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate campaign hero image via Imagen 4 Ultra.")
    p.add_argument("slug", help="Campaign slug (folder name under email-marketing/campaigns/)")
    p.add_argument("prompt", help="Image generation prompt")
    p.add_argument("--aspect-ratio", default="16:9", choices=["1:1", "4:3", "16:9", "3:4", "9:16"])
    return p.parse_args()


def build_client():
    try:
        from google import genai
    except ImportError:
        sys.exit(
            "error: google-genai not installed.\n"
            "run: pip install google-genai"
        )
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("error: GEMINI_API_KEY not set. Add it to .env")
    return genai.Client(api_key=api_key)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    args = parse_args()
    out_dir = EMAIL_MARKETING / "campaigns" / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "hero.png"

    client = build_client()

    from google.genai import types

    print(f"Generating hero for '{args.slug}' with {MODEL}...", file=sys.stderr)
    response = client.models.generate_images(
        model=MODEL,
        prompt=args.prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=args.aspect_ratio,
        ),
    )

    if not response.generated_images:
        sys.exit("ERROR: No image returned. Check prompt for policy violations and retry.")

    img = response.generated_images[0]
    if hasattr(img, "image") and hasattr(img.image, "image_bytes"):
        out_path.write_bytes(img.image.image_bytes)
    elif hasattr(img, "image_bytes"):
        out_path.write_bytes(img.image_bytes)
    else:
        sys.exit("ERROR: Unexpected image response format.")

    print(f"Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
