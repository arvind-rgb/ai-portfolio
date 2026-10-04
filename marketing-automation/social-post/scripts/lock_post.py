#!/usr/bin/env python3
"""
lock_post.py — atomic gate for marking a post as "Creative Locked".

Why: a post marked "Creative Locked" without its asset being on Cloudinary
will silently fail at posting time on the GH Actions runner. This script
makes the lock + asset deploy a single transaction:

  1. Read the planner row for the given PostID
  2. Resolve every PostOutput file path (handles comma-separated carousels
     and laptop-absolute → repo-relative normalization)
  3. Verify each file exists locally
  4. Upload to Cloudinary (idempotent — skips already-synced files)
  5. ONLY THEN update PostStatus to "Creative Locked"

If any step fails, status stays where it was — never leaves an undeployed
"locked" post in the planner.

Usage:
  python3 _skills/social-post/scripts/lock_post.py --post-id IG-004
  python3 _skills/social-post/scripts/lock_post.py --post-id LI-005 --sheet LinkedIn
  python3 _skills/social-post/scripts/lock_post.py --post-id IG-004 --dry-run

By default scans both sheets to find the PostID. Use --sheet to disambiguate.
"""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLANNER = PROJECT_ROOT / "content-planner" / "bhookle-content-calendar-2026-08.xlsx"
MANIFEST = PROJECT_ROOT / "assets" / "_cloudinary-manifest.json"


def _git_dirty_warning():
    """Loud warning if planner / log / manifest have uncommitted changes.

    The 2026-06-06 incident: local planner edits weren't pushed → cron tick on
    GH Actions read stale state → duplicate IG-006 post. This check is a final
    safety net AT END of lock_post so the user is reminded to commit+push.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain",
             "content-planner", "assets/_posted-log.csv", "assets/_cloudinary-manifest.json"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return
    if not out:
        return
    print()
    print("⚠️  UNCOMMITTED CHANGES detected in planner/log/manifest:")
    for line in out.splitlines():
        print(f"     {line}")
    print()
    print("   The GH Actions cron tick (every 15 min) only sees what's PUSHED to GitHub.")
    print("   If you don't commit + push now, the next tick will use stale state.")
    print()
    print("   Run:")
    print("     git pull --rebase")
    print("     git add content-planner/*.xlsx assets/_posted-log.csv assets/_cloudinary-manifest.json")
    print('     git commit -m "lock <POSTID>"')
    print("     git push")
    print()


def normalize(p: str) -> str:
    """Strip /…/bhookle-marketing/ prefix; return repo-relative path."""
    marker = "/bhookle-marketing/"
    idx = p.find(marker)
    return p[idx + len(marker):] if idx >= 0 else p


def resolve_assets(post_output: str) -> list:
    """Return list of repo-relative paths from a comma-separated PostOutput cell."""
    if not post_output:
        return []
    return [normalize(seg.strip()) for seg in post_output.split(",") if seg.strip()]


def find_post(planner, post_id: str, sheet_hint: str = ""):
    """Locate the row for post_id across sheets. Returns (sheet, row_dict)."""
    import openpyxl
    wb = openpyxl.load_workbook(planner, data_only=True)
    sheets = [sheet_hint] if sheet_hint else ["Instagram_Facebook", "LinkedIn"]
    for sheet_name in sheets:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        headers = [c.value for c in ws[1]]
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            d = dict(zip(headers, row))
            if str(d.get("PostID", "")).strip() == post_id:
                wb.close()
                return sheet_name, d, row_idx
    wb.close()
    return None, None, None


def sync_specific_files(file_paths: list, dry_run: bool = False) -> tuple:
    """Sync just these files to Cloudinary. Returns (ok: bool, uploaded: list, errored: list)."""
    sys.path.insert(0, str(Path(__file__).parent))
    from sync_assets import (
        cloudinary_setup, public_id_for, resource_type_for, file_hash,
        load_manifest, save_manifest,
    )

    cloudinary = cloudinary_setup()
    from cloudinary.uploader import upload

    manifest = load_manifest()
    uploaded, skipped, errored = [], [], []

    for rel in file_paths:
        f = PROJECT_ROOT / rel
        if not f.exists():
            errored.append(f"{rel} — file does not exist locally")
            continue
        ext = f.suffix.lower()
        rtype = resource_type_for(ext)
        if not rtype:
            errored.append(f"{rel} — unsupported file type ({ext})")
            continue

        pid = public_id_for(f)
        h = file_hash(f)

        if manifest.get(pid, {}).get("hash") == h:
            skipped.append(rel)
            continue

        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  ⬆  Uploading {rel} ({size_mb:.1f} MB) → cloudinary:{pid}")
        if dry_run:
            uploaded.append(rel)
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
            manifest[pid] = {
                "hash": h,
                "resource_type": rtype,
                "url": res.get("secure_url"),
                "size": f.stat().st_size,
            }
            save_manifest(manifest)
            uploaded.append(rel)
        except Exception as e:
            errored.append(f"{rel} — upload failed: {e}")

    return (len(errored) == 0), uploaded, skipped, errored


def update_status(planner: Path, sheet: str, post_id: str, status: str):
    import openpyxl
    wb = openpyxl.load_workbook(planner)
    ws = wb[sheet]
    headers = [c.value for c in ws[1]]
    pid_col = headers.index("PostID") + 1
    status_col = headers.index("PostStatus") + 1
    for row_num in range(2, ws.max_row + 1):
        if str(ws.cell(row=row_num, column=pid_col).value or "").strip() == post_id:
            ws.cell(row=row_num, column=status_col).value = status
            wb.save(planner)
            wb.close()
            return True
    wb.close()
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-id", required=True, help="e.g. IG-004 or LI-005")
    parser.add_argument("--planner", default=str(DEFAULT_PLANNER))
    parser.add_argument("--sheet", default="", help="Instagram_Facebook | LinkedIn (auto if omitted)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip Cloudinary sync — only use if the asset doesn't need posting "
             "(e.g. text-only LinkedIn). NEVER use to bypass a real failure.",
    )
    args = parser.parse_args()

    planner = Path(args.planner)
    if not planner.exists():
        print(f"❌ Planner not found: {planner}")
        sys.exit(1)

    print(f"🔒 Locking {args.post_id} in {planner.name}")
    sheet, post, row_idx = find_post(planner, args.post_id, args.sheet)
    if not post:
        print(f"❌ Post {args.post_id} not found in any sheet")
        sys.exit(1)

    current_status = str(post.get("PostStatus", "") or "").strip()
    print(f"   Sheet:  {sheet} (row {row_idx})")
    print(f"   Status: {current_status} → Creative Locked")

    # Content gate: never lock captions carrying draft placeholders or banned
    # vocabulary — the 15-min tick publishes unattended, so this is the last
    # human-free checkpoint before 23.5K followers see bracket text.
    import re
    caption_text = " ".join(
        str(post.get(f) or "") for f in ("PostHook", "PostDescription", "PostName")
    )
    placeholder = re.search(r"\[(VERIFY|FILL|ADD|WRITE|TBD|CONFIRM|INSERT)", caption_text, re.I)
    banned = re.search(
        r"restaurant-style|bhookleeats\.com|https?://|\byummy\b|\btasty\b|\bdelicious\b",
        caption_text, re.I,
    )
    if placeholder or banned:
        kind = "draft placeholder" if placeholder else "banned vocabulary"
        offender = (placeholder or banned).group(0)
        print(f"\n❌ Content gate: {kind} found in caption: '{offender}'")
        print(f"   Fix the planner text, then re-run. Status NOT updated.")
        sys.exit(1)

    # Resolve assets
    post_output = str(post.get("PostOutput", "") or "")
    post_format = str(post.get("PostFormat", "") or "").lower()
    is_li_text_only = sheet == "LinkedIn" and "text" in post_format and "image" not in post_format

    if is_li_text_only:
        print(f"   Format: {post_format} (no asset required — LinkedIn text-only)")
        if not args.dry_run:
            update_status(planner, sheet, args.post_id, "Creative Locked")
            print(f"✅ {args.post_id} marked Creative Locked (no assets to sync)")
        return

    assets = resolve_assets(post_output)
    if not assets:
        if post.get("ExistingAssetLink"):
            print(f"   Assets: no PostOutput but ExistingAssetLink set ({str(post.get('ExistingAssetLink'))[:60]})")
            print(f"   Skipping Cloudinary sync — runner will fetch from Drive at post time.")
            if not args.dry_run:
                update_status(planner, sheet, args.post_id, "Creative Locked")
                print(f"✅ {args.post_id} marked Creative Locked")
            return
        print(f"❌ {args.post_id} has no PostOutput and no ExistingAssetLink — cannot lock")
        sys.exit(1)

    print(f"   Assets: {len(assets)} file(s)")
    for a in assets:
        exists = (PROJECT_ROOT / a).exists()
        print(f"      {'✓' if exists else '✗'} {a}")

    # Dimension gate: IG assets must be vertical — reels 1080x1920, statics/carousels 1080x1350
    if sheet == "Instagram_Facebook":
        bad_dims = []
        for a in assets:
            f = PROJECT_ROOT / a
            if not f.exists():
                continue
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                    capture_output=True, text=True, timeout=30).stdout.strip()
                w, h = (int(x) for x in probe.split(",")[:2])
            except Exception:
                continue
            expect = (1080, 1920) if f.suffix.lower() in (".mp4", ".mov") else (1080, 1350)
            if (w, h) != expect:
                bad_dims.append(f"{a}: {w}x{h} (expected {expect[0]}x{expect[1]})")
        if bad_dims:
            print(f"\n❌ Dimension gate: assets are not Instagram-vertical:")
            for b in bad_dims:
                print(f"   • {b}")
            print(f"   Status NOT updated. Fix dimensions and re-run.")
            sys.exit(1)

    # Sync to Cloudinary
    print(f"\n📤 Syncing to Cloudinary...")
    ok, uploaded, skipped, errored = sync_specific_files(assets, dry_run=args.dry_run)
    if errored:
        print(f"\n❌ Sync errors:")
        for e in errored:
            print(f"   • {e}")
        print(f"\n   Status NOT updated. Fix the errors above and re-run.")
        sys.exit(1)
    print(f"   {len(uploaded)} uploaded, {len(skipped)} already synced")

    if args.dry_run:
        print(f"\n   (dry-run — planner not updated)")
        return

    if update_status(planner, sheet, args.post_id, "Creative Locked"):
        print(f"\n✅ {args.post_id} fully locked: assets synced + status updated")
    else:
        print(f"\n❌ Failed to update planner status (assets WERE synced)")
        sys.exit(1)

    _git_dirty_warning()


if __name__ == "__main__":
    main()
