#!/usr/bin/env python3
"""
post_instagram.py — Instagram Graph API poster for Bhookle.

ARCHITECTURE: GitHub Actions calls this script at each post's scheduled time.
Within a single job: upload assets → create container → publish immediately.
DO NOT use publish_at — Meta silently ignores it and containers expire in 24h.

Two entry points:
  1. CLI: python3 post_instagram.py --post-id IG-001 --planner <path>
     (called by GitHub Actions cron)
  2. Import: schedule_instagram_post(...) — DEPRECATED, kept for backward compat
     (do NOT use for production scheduling — containers expire)
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz
import requests

IG_API_BASE = "https://graph.facebook.com/v21.0"
IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc

IG_CAROUSEL_MAX = 10  # Instagram hard limit
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = [2, 5, 10]  # seconds between attempts


def _cloudinary_url_for(repo_relative_path: str, force_image_format: str = None) -> str:
    """
    Derive the Cloudinary URL for an asset path. Handles both repo-relative
    ('assets/social/2026-06/IG-005.mp4') and laptop-absolute paths.

    For videos: serves the original file as-is.
    For images: if force_image_format='jpg', Cloudinary transcodes on the fly
    (so we can serve PNG sources as JPG without re-uploading).

    Returns "" if asset not under assets/ or CLOUDINARY_CLOUD_NAME not set.
    Instagram fetches these URLs directly — no public-host detour needed.
    """
    cloud = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
    if not cloud:
        return ""
    from pathlib import Path as _P
    # Strip laptop-absolute prefix if present
    s = str(repo_relative_path)
    marker = "/bhookle-marketing/"
    idx = s.find(marker)
    if idx >= 0:
        s = s[idx + len(marker):]
    if not s.startswith("assets/"):
        return ""
    p = _P(s)
    ext = p.suffix.lower()
    rtype = "video" if ext in {".mp4", ".mov"} else "image"
    rel_under_assets = p.relative_to("assets").with_suffix("")
    public_id = f"bhookle/{rel_under_assets.as_posix()}"
    transformation = f"f_{force_image_format}/" if (rtype == "image" and force_image_format) else ""
    return f"https://res.cloudinary.com/{cloud}/{rtype}/upload/{transformation}{public_id}{ext}"


def _ensure_asset_available(local_path: str) -> str:
    """
    If the local file exists, return its path unchanged.
    If missing, derive the Cloudinary URL and download to a temp file in the
    same directory (creating dirs as needed). Returns the path to a real file.
    Raises FileNotFoundError if neither the local file nor a Cloudinary copy exist.
    """
    from pathlib import Path as _P
    if not local_path:
        return local_path
    p = _P(local_path)
    if p.exists():
        return local_path
    url = _cloudinary_url_for(local_path)
    if not url:
        raise FileNotFoundError(f"Asset missing and no Cloudinary URL derivable: {local_path}")
    print(f"  ⬇  Downloading from Cloudinary: {url}")
    p.parent.mkdir(parents=True, exist_ok=True)
    import urllib.request
    try:
        urllib.request.urlretrieve(url, str(p))
    except Exception as e:
        raise FileNotFoundError(f"Cloudinary download failed for {local_path}: {e}")
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(f"Cloudinary download produced empty file: {local_path}")
    print(f"     ✓ {p.stat().st_size // 1024} KB cached at {local_path}")
    return local_path


def _normalize_asset_path(p: str) -> str:
    """
    PostOutput is often a laptop-absolute path (e.g. ~/
    bhookle-marketing/assets/social/2026-06/IG-001.mp4). That path doesn't exist
    on the GitHub Actions runner. Convert any absolute path under a
    'bhookle-marketing' segment to a path relative to the current working
    directory (which is the repo root in both contexts).

    Handles comma-separated lists for carousels.
    """
    if not p:
        return p
    parts = [seg.strip() for seg in p.split(",")]
    out = []
    for seg in parts:
        # If seg contains /bhookle-marketing/, take everything after it
        marker = "/bhookle-marketing/"
        idx = seg.find(marker)
        if idx >= 0:
            out.append(seg[idx + len(marker):])
        else:
            out.append(seg)
    return ",".join(out)


# ---------- Credential check ----------

def check_ig_credentials() -> bool:
    user_id = os.getenv("IG_USER_ID", "")
    token = os.getenv("IG_ACCESS_TOKEN", "")
    if not user_id or not token:
        print("  ✗ IG_USER_ID or IG_ACCESS_TOKEN not set in .env")
        return False
    try:
        r = requests.get(
            f"{IG_API_BASE}/{user_id}",
            params={"fields": "id,username", "access_token": token},
            timeout=10,
        )
        data = r.json()
        if "error" in data:
            print(f"  ✗ Instagram credentials invalid: {data['error'].get('message')}")
            return False
        username = data.get("username", user_id)

        # Expiry via debug_token
        d = requests.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=10,
        ).json().get("data", {})
        expires_at = d.get("expires_at", 0) or d.get("data_access_expires_at", 0)
        if expires_at:
            days_left = (expires_at - int(datetime.utcnow().timestamp())) // 86400
            if days_left < 0:
                print(f"  ✗ Instagram token EXPIRED ({-days_left}d ago) — refresh via setup.md §1")
                return False
            if days_left <= 7:
                print(f"  ⚠ Instagram token expires in {days_left}d — refresh soon")
            print(f"  ✓ Instagram connected as @{username} (token: {days_left}d left)")
        else:
            print(f"  ✓ Instagram connected as @{username}")
        return True
    except Exception as e:
        print(f"  ✗ Instagram credential check failed: {e}")
        return False


# ---------- Asset helpers ----------

def ensure_jpg(local_path: str) -> str:
    """Meta rejects PNG for IG posts. Convert PNG → JPG and return new path."""
    p = Path(local_path)
    if p.suffix.lower() in (".jpg", ".jpeg"):
        return local_path
    if p.suffix.lower() == ".png":
        jpg_path = p.with_suffix(".jpg")
        if not jpg_path.exists():
            from PIL import Image
            Image.open(p).convert("RGB").save(jpg_path, "JPEG", quality=95)
        return str(jpg_path)
    return local_path


def upload_to_public_host(local_path: str) -> str:
    """
    Upload a file to a public temp host. Tries multiple in order for resilience.
    Returns the public URL or raises RuntimeError if all hosts fail.
    """
    errors = []

    # Host 1: catbox.moe (primary — 200MB, no expiry)
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "300",
             "-F", "reqtype=fileupload",
             "-F", f"fileToUpload=@{local_path}",
             "https://catbox.moe/user/api.php"],
            capture_output=True, text=True, timeout=320,
        )
        url = r.stdout.strip()
        if url.startswith("https://"):
            return url
        errors.append(f"catbox: {r.stdout[:100]}")
    except Exception as e:
        errors.append(f"catbox: {e}")

    # Host 2: tmpfiles.org fallback
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "300",
             "-F", f"file=@{local_path}",
             "https://tmpfiles.org/api/v1/upload"],
            capture_output=True, text=True, timeout=320,
        )
        import json as _json
        resp = _json.loads(r.stdout)
        url = resp.get("data", {}).get("url", "")
        if url:
            # tmpfiles returns view URL; convert to direct download
            return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        errors.append(f"tmpfiles: {r.stdout[:100]}")
    except Exception as e:
        errors.append(f"tmpfiles: {e}")

    raise RuntimeError(f"All upload hosts failed: {' | '.join(errors)}")


def find_carousel_slides(post_id: str, asset_local_path: str) -> list:
    """
    Find all carousel slide files for a post.
    Convention: <POSTID>-slide1.{png|jpg}, <POSTID>-slide2.{png|jpg}, ...
    Dedupes JPG/PNG pairs (prefers JPG). Returns sorted by slide number.
    """
    # 1. If PostOutput is comma-separated paths, use them directly
    if asset_local_path and "," in asset_local_path:
        paths = [p.strip() for p in asset_local_path.split(",") if p.strip()]
        existing = [p for p in paths if Path(p).exists()]
        if existing:
            return existing

    # 2. Glob the directory
    asset_dir = None
    if asset_local_path and Path(asset_local_path).exists():
        asset_dir = Path(asset_local_path).parent
    elif asset_local_path:
        try_dir = Path(asset_local_path).parent
        if try_dir.exists():
            asset_dir = try_dir
    if asset_dir is None:
        # Fall back to default assets dir
        asset_dir = Path("~/bhookle-marketing/assets/social/2026-06")
        # In CI, the workspace path is different
        if not asset_dir.exists():
            asset_dir = Path("assets/social/2026-06").resolve()

    found = list(asset_dir.glob(f"{post_id}-slide*.png")) + \
            list(asset_dir.glob(f"{post_id}-slide*.jpg"))

    # Dedupe by stem, prefer JPG over PNG
    seen = set()
    unique = []
    for s in sorted(found, key=lambda p: (p.stem, 0 if p.suffix.lower() in (".jpg", ".jpeg") else 1)):
        if s.stem not in seen:
            seen.add(s.stem)
            unique.append(s)

    # Sort by slide number
    def slide_num(p):
        m = re.search(r"slide(\d+)", p.stem)
        return int(m.group(1)) if m else 999
    unique.sort(key=slide_num)
    return [str(s) for s in unique]


# ---------- Retry decorator ----------

def with_retry(fn, *args, label="op", **kwargs):
    """Retry a function up to RETRY_ATTEMPTS with exponential backoff."""
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < RETRY_ATTEMPTS - 1:
                wait = RETRY_BACKOFF[attempt]
                print(f"    ⚠ {label} attempt {attempt+1} failed: {e}; retrying in {wait}s")
                time.sleep(wait)
    raise last_exc


# ---------- Meta API calls (retried) ----------

def _meta_post(url, data):
    r = requests.post(url, data=data, timeout=120)
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"Meta: {d['error'].get('message')}")
    return d


def _meta_get(url, params):
    r = requests.get(url, params=params, timeout=30)
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"Meta: {d['error'].get('message')}")
    return d


def wait_for_container_ready(container_id: str, token: str, max_wait_sec: int = 300) -> bool:
    """Poll container until FINISHED (REELS/VIDEO need processing time)."""
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{IG_API_BASE}/{container_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=15,
            )
            status = r.json().get("status_code", "")
            if status == "FINISHED":
                return True
            if status == "ERROR":
                return False
        except Exception:
            pass
        time.sleep(10)
    return False


# ---------- Main: publish from planner row ----------

def post_now_from_planner(post_id: str, planner_path: str) -> dict:
    """
    Called by GitHub Actions cron. Loads post from Excel, uploads, publishes,
    updates status. Returns dict with success + media_id.

    Idempotent: if status is already "Posted", returns success without re-posting.
    """
    import openpyxl

    ig_user_id = os.getenv("IG_USER_ID", "")
    token = os.getenv("IG_ACCESS_TOKEN", "")
    if not ig_user_id or not token:
        return {"success": False, "error": "IG_USER_ID or IG_ACCESS_TOKEN not set"}

    planner = Path(planner_path)
    if not planner.exists():
        return {"success": False, "error": f"Planner not found: {planner_path}"}

    # Load post row
    wb = openpyxl.load_workbook(planner, read_only=True, data_only=True)
    ws = wb["Instagram_Facebook"]
    headers = [c.value for c in ws[1] if c.value]
    post = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and dict(zip(headers, row)).get("PostID") == post_id:
            post = dict(zip(headers, row))
            break
    wb.close()

    if not post:
        return {"success": False, "error": f"Post {post_id} not found in planner"}

    # IDEMPOTENCY: already posted? skip silently
    current_status = str(post.get("PostStatus", ""))
    if current_status == "Posted":
        print(f"  ⏭  {post_id} already Posted — skipping (idempotent)")
        return {"success": True, "skipped": True, "reason": "already posted"}

    # Build caption
    caption = str(post.get("PostDescription") or "").strip()
    hashtags = str(post.get("PostHashtag") or "").strip()
    if hashtags:
        caption = f"{caption}\n\n{hashtags}"
    caption = re.sub(
        r'(https?://)?bhookleeats\.com(/\S*)?',
        'Download the Bhookle app',
        caption,
        flags=re.IGNORECASE,
    )

    asset_path = _normalize_asset_path(str(post.get("PostOutput") or ""))
    # JIT-fetch from Cloudinary if local copy missing (covers GH Actions runner case
    # where assets/ is gitignored and not checked out)
    if asset_path:
        try:
            for seg in [s.strip() for s in asset_path.split(",")]:
                _ensure_asset_available(seg)
        except FileNotFoundError as e:
            print(f"  ⚠ {e}")
            # Continue — drive_url may still rescue us via the carousel/single fallback below
    drive_url = str(post.get("ExistingAssetLink") or "")
    post_format = str(post.get("PostFormat", "")).lower()

    is_reel = "reel" in post_format
    is_carousel = "carousel" in post_format
    is_video = is_reel or "video" in post_format
    is_story = "story" in post_format

    try:
        # ===== CAROUSEL =====
        if is_carousel:
            slides = find_carousel_slides(post_id, asset_path)
            if not slides:
                raise FileNotFoundError(
                    f"No carousel slides for {post_id}. Expected {post_id}-slide1..N"
                )

            # GUARDRAIL: hard cap + sanity
            if len(slides) > IG_CAROUSEL_MAX:
                raise RuntimeError(
                    f"GUARDRAIL: {post_id} has {len(slides)} slides — exceeds IG carousel max of {IG_CAROUSEL_MAX}"
                )
            print(f"  Carousel with {len(slides)} slides")

            child_ids = []
            for i, slide_path in enumerate(slides, 1):
                # Prefer Cloudinary URL directly (skips flaky public-host upload).
                # Cloudinary's f_jpg transcodes PNG→JPG on the fly.
                slide_url = _cloudinary_url_for(slide_path, force_image_format="jpg")
                if slide_url:
                    print(f"    [slide {i}/{len(slides)}] {Path(slide_path).name} → cloudinary")
                else:
                    jpg = ensure_jpg(slide_path)
                    print(f"    [slide {i}/{len(slides)}] {Path(jpg).name} → public-host fallback")
                    slide_url = with_retry(upload_to_public_host, jpg, label=f"upload slide {i}")
                cdata = with_retry(
                    _meta_post,
                    f"{IG_API_BASE}/{ig_user_id}/media",
                    {"access_token": token, "image_url": slide_url, "is_carousel_item": "true"},
                    label=f"child container {i}",
                )
                child_ids.append(cdata["id"])

            assert len(child_ids) == len(slides), \
                f"GUARDRAIL: created {len(child_ids)} children for {len(slides)} slides"

            print(f"  Creating parent CAROUSEL container...")
            pdata = with_retry(
                _meta_post,
                f"{IG_API_BASE}/{ig_user_id}/media",
                {"access_token": token, "caption": caption,
                 "media_type": "CAROUSEL", "children": ",".join(child_ids)},
                label="parent carousel",
            )
            container_id = pdata["id"]
            time.sleep(5)  # give Meta a moment

        # ===== REEL / VIDEO =====
        elif is_video:
            if not asset_path or not Path(asset_path).exists():
                raise FileNotFoundError(f"No video at {asset_path} for {post_id}")
            # Prefer Cloudinary URL directly (skips flaky public-host upload).
            video_url = _cloudinary_url_for(asset_path)
            if video_url:
                print(f"  Video URL → cloudinary: {video_url}")
            else:
                print(f"  Uploading video to public host: {Path(asset_path).name}")
                video_url = with_retry(upload_to_public_host, asset_path, label="video upload")
            media_type = "REELS" if is_reel else "VIDEO"
            cdata = with_retry(
                _meta_post,
                f"{IG_API_BASE}/{ig_user_id}/media",
                {"access_token": token, "caption": caption,
                 "media_type": media_type, "video_url": video_url},
                label="video container",
            )
            container_id = cdata["id"]
            print(f"  Waiting for Meta to process video (up to 5 min)...")
            ready = wait_for_container_ready(container_id, token)
            if not ready:
                raise RuntimeError("Video container did not reach FINISHED status in time")

        # ===== IMAGE (Static / Story) =====
        else:
            if asset_path and Path(asset_path).exists():
                # Prefer Cloudinary URL with f_jpg transcoding (PNG→JPG on the fly).
                image_url = _cloudinary_url_for(asset_path, force_image_format="jpg")
                if image_url:
                    print(f"  Image URL → cloudinary: {Path(asset_path).name}")
                else:
                    jpg = ensure_jpg(asset_path)
                    print(f"  Uploading image to public host: {Path(jpg).name}")
                    image_url = with_retry(upload_to_public_host, jpg, label="image upload")
            elif drive_url and "drive.google.com" in drive_url:
                file_id = drive_url.split("/d/")[1].split("/")[0]
                image_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            else:
                raise FileNotFoundError(f"No asset for {post_id}")

            container_params = {"access_token": token, "caption": caption,
                                "image_url": image_url, "media_type": "IMAGE"}
            if is_story:
                container_params["media_type"] = "STORIES"
            cdata = with_retry(
                _meta_post,
                f"{IG_API_BASE}/{ig_user_id}/media",
                container_params,
                label="image container",
            )
            container_id = cdata["id"]
            time.sleep(2)

        # ===== PUBLISH NOW =====
        print(f"  Publishing container {container_id}...")
        pub = with_retry(
            _meta_post,
            f"{IG_API_BASE}/{ig_user_id}/media_publish",
            {"access_token": token, "creation_id": container_id},
            label="media_publish",
        )
        media_id = pub.get("id", "")
        print(f"  ✅ Published. Media ID: {media_id}")
        result = {"success": True, "container_id": container_id, "media_id": media_id}

        # CRITICAL: do side-effects HERE (inside the function), not in main(),
        # so they fire regardless of whether we're called via CLI or imported
        # by social_tick.py. Previously these lived only in main() — that's why
        # IG posts fired by the tick worker never updated posted-log or the
        # planner, causing 4× duplicate posts.
        _record_post_success(post_id, planner_path, media_id)
        return result

    except Exception as e:
        result = {"success": False, "error": str(e)}
        _record_post_failure(post_id, planner_path, str(e))
        return result


def _record_post_success(post_id: str, planner_path: str, media_id: str):
    """Idempotency log + planner status update on successful post."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from social_tick import append_to_posted_log
        append_to_posted_log(post_id, "instagram", media_id)
        print(f"  → Appended {post_id} to posted-log.csv (idempotency)")
    except Exception as e:
        print(f"  ⚠ Could not append to posted-log: {e}")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from update_planner import update_post_status
        update_post_status(Path(planner_path), "Instagram_Facebook", post_id, "Posted")
        print(f"  → Marked {post_id} as Posted in planner")
    except Exception as e:
        print(f"  ⚠ Could not update planner status: {e}")


def _record_post_failure(post_id: str, planner_path: str, err: str):
    """Planner status update on failure."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from update_planner import update_post_status
        update_post_status(Path(planner_path), "Instagram_Facebook", post_id, "Failed")
        print(f"  → Marked {post_id} as Failed in planner ({err[:80]})")
    except Exception as e:
        print(f"  ⚠ Could not update planner status: {e}")


# ---------- DEPRECATED: kept for old runner backward compat ----------

def schedule_instagram_post(*args, **kwargs):
    """DEPRECATED. publish_at doesn't work; containers expire. Use post_now_from_planner via GH Actions cron."""
    return {
        "success": False,
        "error": "DEPRECATED. Use GH Actions cron + post_now_from_planner. See lessons.md.",
    }


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--planner", required=True)
    args = parser.parse_args()

    # Load .env if running locally
    try:
        from dotenv import load_dotenv
        from pathlib import Path as _P
        load_dotenv(_P(args.planner).parent.parent / ".env")
    except Exception:
        pass  # In CI, env vars come from GH Secrets directly

    print(f"=== post_instagram.py: {args.post_id} @ {datetime.utcnow().isoformat()}Z ===")

    if not check_ig_credentials():
        sys.exit(2)

    # Side effects (posted-log + planner status) now happen INSIDE
    # post_now_from_planner() via _record_post_success/_failure. No need
    # to repeat them here.
    result = post_now_from_planner(args.post_id, args.planner)

    if not result.get("success"):
        print(f"❌ FAILED: {result.get('error')}")
        sys.exit(1)
    print(f"✅ DONE")


if __name__ == "__main__":
    main()
