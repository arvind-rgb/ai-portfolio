#!/usr/bin/env python3
"""
social_post_runner.py — Generate GitHub Actions cron workflow for all Creative
Locked posts (IG + LinkedIn).

ARCHITECTURE (post 2026-05-24 refactor):
  - Does NOT post directly. Generates a single workflow YAML.
  - Each post becomes one cron job. At cron time, GH Actions runs
    post_instagram.py or post_linkedin.py, which uploads + publishes
    immediately, then commits the planner update back to the repo.
  - Computer-independent. Cloud cron runs everything.

Why this design:
  - Meta's publish_at is silently ignored for our account type
  - Pre-uploaded IG containers expire after 24h
  - LinkedIn has no native scheduling API
  → Same architectural answer for both: cron-style "publish at the right time"

Usage:
  python3 social_post_runner.py --check-env    # verify creds + tokens
  python3 social_post_runner.py --dry-run      # preview posts
  python3 social_post_runner.py                # generate workflow YAML
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

load_dotenv(PROJECT_ROOT / ".env")

from post_instagram import check_ig_credentials
from post_linkedin import check_li_credentials
from gen_github_actions import generate_combined_workflow
from update_planner import update_post_status, find_planner_file


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Preview without generating")
    p.add_argument("--check-env", action="store_true", help="Check credentials only")
    p.add_argument("--ig-only", action="store_true", help="Instagram only")
    p.add_argument("--li-only", action="store_true", help="LinkedIn only")
    return p.parse_args()


def check_environment():
    print("\n=== Environment Check ===")
    ok = True

    required = [("openpyxl", "openpyxl"), ("requests", "requests"),
                ("pytz", "pytz"), ("python-dotenv", "dotenv"), ("Pillow", "PIL")]
    for pkg_name, import_name in required:
        try:
            __import__(import_name)
            print(f"  ✓ {pkg_name}")
        except ImportError:
            print(f"  ✗ {pkg_name} — run: pip3 install {pkg_name}")
            ok = False

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        print(f"  ✓ .env found at {env_path}")
    else:
        print(f"  ✗ .env not found")
        ok = False

    ig_ok = check_ig_credentials()
    li_ok = check_li_credentials()

    planner = find_planner_file(PROJECT_ROOT)
    if planner:
        print(f"  ✓ Planner: {planner.name}")
    else:
        print("  ✗ No planner found in content-planner/")
        ok = False

    print(f"\n{'✅ All checks passed.' if ok and ig_ok and li_ok else '❌ Fix the above issues.'}")
    return ok and ig_ok and li_ok


def read_locked_posts(planner_path: Path, sheet_name: str) -> list:
    """Read rows with PostStatus in ('Creative Locked', 'Failed')."""
    wb = openpyxl.load_workbook(planner_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        return []
    ws = wb[sheet_name]
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    posts = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        data = dict(zip(headers, row))
        status = str(data.get("PostStatus", "")).strip()
        if status in ("Creative Locked", "GH Actions Generated"):
            posts.append(data)
    wb.close()
    return posts


def print_posts_table(ig_posts: list, li_posts: list):
    print(f"\n{'='*70}")
    print(f"  POSTS TO SCHEDULE ({len(ig_posts)} IG / {len(li_posts)} LinkedIn)")
    print(f"{'='*70}")
    for label, posts in (("📸 INSTAGRAM", ig_posts), ("💼 LINKEDIN", li_posts)):
        if not posts:
            continue
        print(f"\n{label}")
        print(f"  {'ID':<8} {'Date':<12} {'Time (IST)':<12} {'Format':<20} {'Name'}")
        print(f"  {'-' * 70}")
        for p in posts:
            print(f"  {str(p.get('PostID','')):<8} {str(p.get('PostDate','')):<12} "
                  f"{str(p.get('PostTime (IST)','')):<12} {str(p.get('PostFormat',''))[:18]:<20} "
                  f"{str(p.get('PostName',''))[:30]}")


def main():
    args = parse_args()

    print("\n🚀 Bhookle Social Post Runner (GH Actions mode)")
    print(f"   Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")

    if args.check_env:
        check_environment()
        return

    planner_path = find_planner_file(PROJECT_ROOT)
    if not planner_path:
        print("❌ No content planner found.")
        sys.exit(1)

    ig_posts = [] if args.li_only else read_locked_posts(planner_path, "Instagram_Facebook")
    li_posts = [] if args.ig_only else read_locked_posts(planner_path, "LinkedIn")

    if not ig_posts and not li_posts:
        print("\n✅ No Creative Locked posts to schedule.")
        return

    print_posts_table(ig_posts, li_posts)

    if args.dry_run:
        print("\n[Dry run — workflow YAML not generated. Remove --dry-run to proceed.]")
        return

    # Pre-flight credential check
    print("\n=== Pre-flight Token Check ===")
    ig_ok = True if args.li_only else check_ig_credentials()
    li_ok = True if args.ig_only else check_li_credentials()
    if not (ig_ok and li_ok):
        print("\n❌ Token check failed. Refresh per references/setup.md before proceeding.")
        sys.exit(1)

    # Determine month (for workflow filename) — use earliest scheduled date
    all_dates = [str(p.get("PostDate", "")) for p in (ig_posts + li_posts) if p.get("PostDate")]
    earliest = min(all_dates) if all_dates else datetime.now().strftime("%Y-%m-%d")
    month_str = earliest[:7]

    # Generate combined workflow
    print(f"\n📅 Generating combined GH Actions workflow for {month_str}...")
    workflow_path = generate_combined_workflow(
        ig_posts=ig_posts, li_posts=li_posts,
        project_root=PROJECT_ROOT, month_str=month_str,
        planner_path=planner_path,
    )

    # Mark all posts as "GH Actions Generated"
    for p in ig_posts:
        update_post_status(planner_path, "Instagram_Facebook",
                           str(p.get("PostID", "")), "GH Actions Generated")
    for p in li_posts:
        update_post_status(planner_path, "LinkedIn",
                           str(p.get("PostID", "")), "GH Actions Generated")

    # Write run log
    log_dir = SKILL_DIR / "output"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"runner_log_{datetime.now().strftime('%Y-%m')}.json"
    log_entry = {
        "run_date": datetime.now().isoformat(),
        "planner": str(planner_path),
        "workflow": str(workflow_path),
        "ig_count": len(ig_posts),
        "li_count": len(li_posts),
        "ig_ids": [str(p.get("PostID", "")) for p in ig_posts],
        "li_ids": [str(p.get("PostID", "")) for p in li_posts],
    }
    existing = []
    if log_path.exists():
        try:
            existing = json.load(open(log_path))
            if not isinstance(existing, list):
                existing = [existing]
        except Exception:
            existing = []
    existing.append(log_entry)
    json.dump(existing, open(log_path, "w"), indent=2, default=str)

    rel_path = workflow_path.relative_to(PROJECT_ROOT)
    print(f"\n{'='*70}")
    print(f"  ✅ Workflow generated: {rel_path}")
    print(f"     {len(ig_posts)} IG + {len(li_posts)} LinkedIn = {len(ig_posts)+len(li_posts)} jobs")
    print(f"{'='*70}")
    print(f"\n📋 NEXT STEPS — commit + push to activate cloud scheduling:")
    print(f"   cd {PROJECT_ROOT}")
    print(f"   git add {rel_path} content-planner/")
    print(f"   git commit -m 'Schedule social posts for {month_str}'")
    print(f"   git push")
    print(f"\n🔑 Required GitHub Secrets (Repo → Settings → Secrets → Actions):")
    print(f"   • IG_USER_ID = {os.getenv('IG_USER_ID', 'NOT SET')[:10]}...")
    print(f"   • IG_ACCESS_TOKEN = <60-day Meta token from .env>")
    print(f"   • LI_ACCESS_TOKEN = <60-day LinkedIn token from .env>")
    print(f"   • LI_AUTHOR_URN = {os.getenv('LI_AUTHOR_URN', 'NOT SET')}")
    print(f"\n📊 Verify after push: https://github.com/<user>/<repo>/actions")
    print(f"📝 Run log: {log_path}\n")


if __name__ == "__main__":
    main()
