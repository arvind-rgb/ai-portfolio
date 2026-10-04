#!/usr/bin/env python3
"""
sync_assets.py — upload local social assets to Cloudinary so GH Actions runners
can download them at post time.

Why: assets/ is gitignored (504MB+ of mp4/png). GH Actions checkout doesn't have
these files. Without this, every media post fails preflight on the runner.

Run after you create new assets:
    python3 _skills/social-post/scripts/sync_assets.py
    python3 _skills/social-post/scripts/sync_assets.py --month 2026-06
    python3 _skills/social-post/scripts/sync_assets.py --dry-run

Cloudinary "public_id" mirrors the repo path so the runner can derive the URL
from the planner's PostOutput field:
    Repo path:    assets/social/2026-06/IG-002.mp4
    Cloudinary:   bhookle/social/2026-06/IG-002    (resource_type=video)
    URL:          https://res.cloudinary.com/<cloud>/video/upload/bhookle/social/2026-06/IG-002.mp4

Idempotent: uses overwrite=False and skips files already uploaded.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSETS_ROOT = PROJECT_ROOT / "assets" / "social"
MANIFEST = PROJECT_ROOT / "assets" / "_cloudinary-manifest.json"  # tracks which files are uploaded

VIDEO_EXTS = {".mp4", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SKIP_NAMES = {".DS_Store"}
SKIP_DIRS = {"_variants", "_drafts"}  # experimental/work-in-progress, not for posting


def cloudinary_setup():
    try:
        import cloudinary
    except ImportError:
        print("❌ cloudinary package not installed. Run: pip install cloudinary")
        sys.exit(1)
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    cloud = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    key = os.environ.get("CLOUDINARY_API_KEY", "")
    secret = os.environ.get("CLOUDINARY_API_SECRET", "")
    if not (cloud and key and secret):
        print("❌ Missing CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET in .env")
        sys.exit(1)
    cloudinary.config(cloud_name=cloud, api_key=key, api_secret=secret, secure=True)
    return cloudinary


def public_id_for(local_path: Path) -> str:
    """
    Map local file path to a stable Cloudinary public_id.
    Example: assets/social/2026-06/IG-002.mp4 → bhookle/social/2026-06/IG-002
    """
    rel = local_path.relative_to(PROJECT_ROOT / "assets")
    # Drop extension — Cloudinary appends it from resource_type
    return f"bhookle/{rel.with_suffix('').as_posix()}"


def resource_type_for(ext: str) -> Optional[str]:
    ext = ext.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    return None  # skip unknown types


def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {}


def save_manifest(m: dict):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", help="Only sync assets/social/<month>/ (e.g. 2026-06)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would upload")
    parser.add_argument("--force", action="store_true", help="Re-upload even if hash unchanged")
    args = parser.parse_args()

    cloudinary = cloudinary_setup()
    from cloudinary.uploader import upload

    root = ASSETS_ROOT / args.month if args.month else ASSETS_ROOT
    if not root.is_dir():
        print(f"❌ Directory not found: {root}")
        sys.exit(1)

    manifest = load_manifest()
    files = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.name not in SKIP_NAMES
        and not any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1])
    )
    print(f"📤 Sync target: {root.relative_to(PROJECT_ROOT)}")
    print(f"   {len(files)} candidate file(s) found.\n")

    uploaded = skipped = errored = 0
    for f in files:
        ext = f.suffix.lower()
        rtype = resource_type_for(ext)
        if not rtype:
            continue  # silently skip non-media

        pid = public_id_for(f)
        key = pid  # manifest key
        h = file_hash(f)

        if not args.force and manifest.get(key, {}).get("hash") == h:
            skipped += 1
            continue

        rel = f.relative_to(PROJECT_ROOT)
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  → {rel} ({size_mb:.1f} MB) → cloudinary:{pid} [{rtype}]")
        if args.dry_run:
            uploaded += 1  # count what would upload
            continue

        try:
            res = upload(
                str(f),
                public_id=pid,
                resource_type=rtype,
                overwrite=True,
                use_filename=False,
                unique_filename=False,
            )
            manifest[key] = {
                "hash": h,
                "resource_type": rtype,
                "url": res.get("secure_url"),
                "size": f.stat().st_size,
            }
            uploaded += 1
            save_manifest(manifest)  # save after each upload for resumability
        except Exception as e:
            print(f"    ❌ failed: {e}")
            errored += 1

    print()
    print(f"📊 Summary: {uploaded} uploaded, {skipped} unchanged, {errored} errored")
    if args.dry_run:
        print("   (dry-run — no files actually uploaded)")
    if not args.dry_run:
        print(f"   Manifest saved: {MANIFEST.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
