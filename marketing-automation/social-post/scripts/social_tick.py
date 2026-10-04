#!/usr/bin/env python3
"""
social_tick.py — single dispatcher that runs every 15 min and posts whatever is due.

Replaces the legacy "generate 41 cron jobs per month" approach which suffered from
GitHub Actions cron queueing delays (3+ hours). Single-cron workflows are reliable
because they don't compete with stacked triggers in the same repo.

Logic per tick:
  1. Load both planner sheets (Instagram_Facebook, LinkedIn)
  2. For each row where PostStatus ∈ {Creative Locked, GH Actions Generated} AND
     scheduled (PostDate + PostTime IST) <= now AND scheduled > now - 6h (grace):
       - Call existing post_instagram.py / post_linkedin.py entry point
       - That entry point updates PostStatus → Posted / Failed
  3. Print a summary. Exit 0 always (per-post failures are reported in planner,
     not as workflow failures, so one bad post never blocks the rest).

Idempotency:
- Primary defense: PostStatus in the planner. Already-Posted rows are skipped.
- BACKUP defense: assets/_posted-log.csv — a separate append-only log committed
  by the per-platform posters IMMEDIATELY after a successful API call. Even if
  the planner status update fails to commit (push race condition, etc.), the
  posted-log catches duplicate attempts because it's checked first.
"""

import argparse
import csv
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl
import pytz
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
POSTED_LOG = PROJECT_ROOT / "assets" / "_posted-log.csv"
IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.utc

GRACE_HOURS = 6  # don't fire posts more than 6h late (likely an old missed run)
ELIGIBLE_STATUSES = {"Creative Locked", "GH Actions Generated"}


def load_posted_ids() -> set:
    """Return set of PostIDs already posted, per assets/_posted-log.csv."""
    if not POSTED_LOG.is_file():
        return set()
    ids = set()
    with open(POSTED_LOG, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = (row.get("post_id") or "").strip()
            if pid:
                ids.add(pid)
    return ids


def append_to_posted_log(post_id: str, platform: str, remote_id: str):
    """
    Append a row to assets/_posted-log.csv immediately after a successful API call.
    Idempotency safety net for the planner-status-commit race condition.
    """
    POSTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    is_new = not POSTED_LOG.is_file()
    with open(POSTED_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["post_id", "platform", "remote_id", "posted_at_utc"])
        w.writerow([post_id, platform, remote_id, datetime.now(UTC).isoformat()])


def parse_scheduled_ist(date_val, time_val) -> "datetime | None":
    """Parse PostDate + PostTime (IST) into a UTC-aware datetime."""
    if not date_val or not time_val:
        return None
    # PostDate can be a datetime, date, or string
    if isinstance(date_val, datetime):
        date_part = date_val.date()
    elif hasattr(date_val, "year"):
        date_part = date_val
    else:
        try:
            date_part = datetime.strptime(str(date_val).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    # PostTime can be a time object, datetime, or string like "11:00 AM"
    if hasattr(time_val, "hour") and hasattr(time_val, "minute"):
        hour, minute = time_val.hour, time_val.minute
    else:
        t = str(time_val).strip().upper().replace(".", ":")
        try:
            parsed = datetime.strptime(t, "%I:%M %p")
        except ValueError:
            try:
                parsed = datetime.strptime(t, "%H:%M")
            except ValueError:
                return None
        hour, minute = parsed.hour, parsed.minute

    naive = datetime(date_part.year, date_part.month, date_part.day, hour, minute)
    return IST.localize(naive).astimezone(UTC)


def collect_due_posts(planner_path: Path, now_utc: datetime) -> list:
    """Return list of {sheet, post_id, scheduled_utc, name} for posts that should fire now."""
    wb = openpyxl.load_workbook(planner_path, read_only=True, data_only=True)
    due = []
    cutoff = now_utc - timedelta(hours=GRACE_HOURS)

    for sheet_name in ("Instagram_Facebook", "LinkedIn"):
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        for row in ws.iter_rows(min_row=2, values_only=True):
            d = dict(zip(headers, row))
            post_id = str(d.get("PostID", "") or "").strip()
            status = str(d.get("PostStatus", "") or "").strip()
            if not post_id or status not in ELIGIBLE_STATUSES:
                continue
            scheduled = parse_scheduled_ist(d.get("PostDate"), d.get("PostTime (IST)"))
            if not scheduled:
                continue
            if cutoff <= scheduled <= now_utc:
                due.append({
                    "sheet": sheet_name,
                    "post_id": post_id,
                    "scheduled_utc": scheduled,
                    "name": str(d.get("PostName", "") or ""),
                    "post_output": str(d.get("PostOutput", "") or ""),
                    "post_format": str(d.get("PostFormat", "") or ""),
                    "existing_asset_link": str(d.get("ExistingAssetLink", "") or ""),
                })
    wb.close()
    return due


def _normalize_path(p: str) -> str:
    """Mirror of post_instagram._normalize_asset_path — strips laptop prefix."""
    if not p:
        return p
    marker = "/bhookle-marketing/"
    out = []
    for seg in [s.strip() for s in p.split(",")]:
        idx = seg.find(marker)
        out.append(seg[idx + len(marker):] if idx >= 0 else seg)
    return ",".join(out)


def preflight_check(item: dict) -> tuple:
    """
    Validate that everything needed to post actually exists, BEFORE we hit any API.
    Returns (ok: bool, reason: str).

    Catches the common failure modes that wasted yesterday's runs:
      - PostOutput points at a file that doesn't exist on this filesystem
      - Non-text post format with no asset path at all
    """
    sheet = item["sheet"]
    post_id = item["post_id"]
    raw_output = item.get("post_output", "")
    post_format = (item.get("post_format") or "").lower()
    drive_link = item.get("existing_asset_link", "")

    # LinkedIn text-only posts don't need an asset
    is_li_text_only = (sheet == "LinkedIn" and "text" in post_format and "image" not in post_format)
    if is_li_text_only:
        return True, "ok (text-only LinkedIn post)"

    normalized = _normalize_path(raw_output)
    if not normalized:
        # Allow fallback to Drive link (post_instagram.py downloads from it)
        if drive_link:
            return True, "ok (no PostOutput but ExistingAssetLink present)"
        return False, f"no PostOutput path set in planner for {post_id} ({sheet}, format={post_format})"

    # Check each path. For missing ones, try JIT-fetching from Cloudinary before failing.
    sys.path.insert(0, str(Path(__file__).parent))
    from post_instagram import _ensure_asset_available
    missing = []
    fetched = []
    for seg in [s.strip() for s in normalized.split(",") if s.strip()]:
        if Path(seg).exists():
            continue
        try:
            _ensure_asset_available(seg)
            fetched.append(seg)
        except FileNotFoundError:
            missing.append(seg)
    if missing:
        if drive_link:
            return True, f"ok (local missing but ExistingAssetLink available: {drive_link[:60]})"
        return False, f"asset file(s) not found locally or on Cloudinary: {missing}"
    if fetched:
        return True, f"ok (fetched {len(fetched)} file(s) from Cloudinary)"
    return True, f"ok ({normalized})"


def mark_failed_in_planner(planner_path: Path, sheet: str, post_id: str, reason: str):
    """Mark a post Failed with a reason — used when preflight blocks a fire."""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from update_planner import update_post_status
        # Truncate reason for the status cell so the planner stays readable
        update_post_status(planner_path, sheet, post_id, "Failed")
        print(f"     → marked {post_id} as Failed in planner ({reason[:80]})")
    except Exception as e:
        print(f"     ⚠ failed to update planner status for {post_id}: {e}")


def fire_post(item: dict, planner_path: Path) -> bool:
    """Invoke the right poster for this item. Returns True on success."""
    sys.path.insert(0, str(Path(__file__).parent))
    sheet = item["sheet"]
    post_id = item["post_id"]
    try:
        if sheet == "Instagram_Facebook":
            from post_instagram import post_now_from_planner
            result = post_now_from_planner(post_id, str(planner_path))
            # post_now_from_planner already updates status + prints
            return bool(result and result.get("success"))
        elif sheet == "LinkedIn":
            from post_linkedin import post_from_planner
            post_from_planner(post_id, str(planner_path))  # raises SystemExit on failure
            return True
    except SystemExit as e:
        return e.code == 0
    except Exception as e:
        print(f"  ❌ {post_id} crashed: {e}")
        traceback.print_exc()
        return False
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--planner",
        default="content-planner/bhookle-content-calendar-2026-06.xlsx",
        help="Path to the active planner xlsx",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would fire without actually posting",
    )
    args = parser.parse_args()

    load_dotenv()
    planner_path = Path(args.planner)
    if not planner_path.exists():
        print(f"❌ Planner not found: {planner_path}")
        sys.exit(1)

    now_utc = datetime.now(UTC)
    now_ist = now_utc.astimezone(IST)
    print(f"⏰ Tick at {now_ist.strftime('%Y-%m-%d %H:%M IST')} ({now_utc.strftime('%H:%M UTC')})")
    print(f"   Planner: {planner_path}")

    due = collect_due_posts(planner_path, now_utc)
    # Filter out anything already in the posted-log (defense against planner
    # status updates that failed to commit)
    posted_ids = load_posted_ids()
    if posted_ids:
        before = len(due)
        due = [d for d in due if d["post_id"] not in posted_ids]
        skipped_dup = before - len(due)
        if skipped_dup:
            print(f"   ⏭  Skipped {skipped_dup} post(s) already in posted-log (idempotency)")
    if not due:
        print("   Nothing due. Exiting.")
        return

    print(f"   {len(due)} post(s) due to fire:")
    for item in due:
        sched_ist = item["scheduled_utc"].astimezone(IST).strftime("%H:%M IST")
        print(f"     • [{item['sheet'][:2]}] {item['post_id']} scheduled {sched_ist} — {item['name'][:60]}")

    if args.dry_run:
        print("\n   (dry-run — not posting)")
        return

    succeeded, failed, skipped = 0, 0, 0
    for item in due:
        print(f"\n→ Firing {item['post_id']} ({item['sheet']})...")
        # Preflight: catch missing-asset failures BEFORE we call the API
        ok, reason = preflight_check(item)
        print(f"  preflight: {reason}")
        if not ok:
            skipped += 1
            mark_failed_in_planner(planner_path, item["sheet"], item["post_id"], reason)
            print(f"  ⏭  {item['post_id']} SKIPPED — {reason}")
            continue
        ok = fire_post(item, planner_path)
        if ok:
            succeeded += 1
            print(f"  ✅ {item['post_id']} posted")
        else:
            failed += 1
            print(f"  ❌ {item['post_id']} failed (status marked in planner)")

    print(f"\n📊 Tick summary: {succeeded} posted, {failed} failed, {skipped} preflight-skipped, {len(due)} total")


if __name__ == "__main__":
    main()
