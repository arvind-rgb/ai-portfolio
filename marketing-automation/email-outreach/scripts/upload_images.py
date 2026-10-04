#!/usr/bin/env python3
"""
upload_images.py — Upload campaign images to Cloudinary, write image-urls.json.

Run once per campaign after images are generated. dispatch_batch.py reads
image-urls.json to replace relative src paths with public CDN URLs.

Usage:
  python3 upload_images.py <slug>
  python3 upload_images.py cold-start-first-order
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SKIP_FILES = {"logo-full-orange.png"}  # already on brand assets, skip re-upload


def cloudinary_upload(img_path: Path, cloud_name: str, api_key: str, api_secret: str) -> str:
    """Upload image to Cloudinary, return secure_url."""
    timestamp = str(int(time.time()))
    public_id = f"bhookle/email/{img_path.parent.name}/{img_path.stem}"

    # Generate signature — Cloudinary: SHA1(sorted_params + api_secret)
    params = f"public_id={public_id}&timestamp={timestamp}{api_secret}"
    sig = hashlib.sha1(params.encode()).hexdigest()

    # Build multipart form data manually
    boundary = "----BhookleUpload"
    fields = {
        "api_key": api_key,
        "timestamp": timestamp,
        "public_id": public_id,
        "signature": sig,
    }

    body_parts = []
    for k, v in fields.items():
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}".encode()
        )
    # File part
    mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{img_path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        + img_path.read_bytes()
    )
    body_parts.append(f"--{boundary}--".encode())
    body = b"\r\n".join(body_parts)

    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "bhookle-email-outreach/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        return result["secure_url"]


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    if len(sys.argv) < 2:
        sys.exit("Usage: python3 upload_images.py <campaign_slug>")

    slug = sys.argv[1]
    campaign_dir = EMAIL_MARKETING / "campaigns" / slug
    if not campaign_dir.is_dir():
        sys.exit(f"error: campaign not found: {campaign_dir}")

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    api_key    = os.environ.get("CLOUDINARY_API_KEY", "")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET", "")
    if not all([cloud_name, api_key, api_secret]):
        sys.exit("error: CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET not set in .env")

    urls_path = campaign_dir / "image-urls.json"
    existing = json.loads(urls_path.read_text()) if urls_path.is_file() else {}

    print(f"\n=== Cloudinary Upload: {slug} ===")
    images = [f for f in campaign_dir.iterdir()
              if f.suffix.lower() in IMAGE_EXTS and f.name not in SKIP_FILES]

    for img in sorted(images):
        if img.name in existing:
            print(f"  {img.name}: already uploaded → {existing[img.name]}")
            continue
        print(f"  {img.name}: uploading...", end=" ", flush=True)
        try:
            url = cloudinary_upload(img, cloud_name, api_key, api_secret)
            existing[img.name] = url
            print(f"✓ {url}")
        except Exception as e:
            print(f"ERROR: {e}")

    urls_path.write_text(json.dumps(existing, indent=2))
    print(f"\nSaved: {urls_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
