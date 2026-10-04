#!/usr/bin/env python3
"""
ingest_audience.py — Stage 2: validate audience CSV and build send-plan.json.

Usage:
  python3 ingest_audience.py <slug> <csv_path> [--start-date YYYY-MM-DD] [--dry-run]

Output:
  email-marketing/campaigns/<slug>/audience.csv   (cleaned)
  email-marketing/campaigns/<slug>/send-plan.json (batched ≤90/day)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"

BATCH_SIZE = 90
DAILY_CAP = 100
MONTHLY_CAP = 3000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Permanent test seeds — always prepended to batch 1 of every campaign
SEEDS_FILE = SCRIPT_DIR.parent / "references" / "test-seeds.json"


def load_seeds() -> list[dict]:
    if SEEDS_FILE.is_file():
        return json.loads(SEEDS_FILE.read_text()).get("seeds", [])
    return []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest audience CSV for a campaign.")
    p.add_argument("slug", help="Campaign slug")
    p.add_argument("csv_path", help="Path to audience CSV (must have name and email columns)")
    p.add_argument("--start-date", default=str(date.today()), help="First send date YYYY-MM-DD (default: today)")
    p.add_argument("--dry-run", action="store_true", help="Preview plan without writing files")
    return p.parse_args()


def load_csv(csv_path: str) -> tuple[list[dict], list[str]]:
    """Load CSV, return (valid_rows, errors). Accepts name/email columns in any case."""
    path = Path(csv_path).expanduser().resolve()
    if not path.is_file():
        sys.exit(f"error: file not found: {csv_path}")

    valid, errors = [], []
    seen_emails: set[str] = set()

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.lower().strip() for h in (reader.fieldnames or [])]

        # Accept exact "name"/"email" or prefixed variants like "user_name"/"user_email"
        name_col = next((h for h in reader.fieldnames or [] if h.lower().strip() in ("name", "user_name", "full_name", "first_name")), None)
        email_col = next((h for h in reader.fieldnames or [] if h.lower().strip() in ("email", "user_email", "email_address")), None)

        if not email_col:
            sys.exit(f"error: no 'email' column found. Headers: {reader.fieldnames}")
        if not name_col:
            print("warning: no 'name' column — names will be empty", file=sys.stderr)

        for i, row in enumerate(reader, start=2):
            email = (row.get(email_col) or "").strip().lower()
            name = (row.get(name_col) or "").strip() if name_col else ""

            if not email:
                errors.append(f"row {i}: empty email")
                continue
            if not EMAIL_RE.match(email):
                errors.append(f"row {i}: invalid email '{email}'")
                continue
            if email in seen_emails:
                errors.append(f"row {i}: duplicate '{email}'")
                continue

            seen_emails.add(email)
            valid.append({"name": name, "email": email})

    return valid, errors


def current_monthly_planned(exclude_slug: str) -> int:
    """Count emails planned this calendar month across all other campaigns."""
    today = date.today()
    month_prefix = today.strftime("%Y-%m")
    total = 0
    for plan_file in EMAIL_MARKETING.glob("campaigns/*/send-plan.json"):
        slug = plan_file.parent.name
        if slug == exclude_slug:
            continue
        try:
            plan = json.loads(plan_file.read_text())
            for day_str, emails in plan.get("batches", {}).items():
                if day_str.startswith(month_prefix):
                    total += len(emails)
        except (json.JSONDecodeError, KeyError):
            pass
    return total


def build_send_plan(slug: str, recipients: list[dict], start_date: date, seeds: list[dict] | None = None) -> dict:
    seed_emails = [s["email"] for s in (seeds or [])]

    batches: dict[str, list[str]] = {}
    current = start_date
    for i in range(0, len(recipients), BATCH_SIZE):
        batch = [r["email"] for r in recipients[i : i + BATCH_SIZE]]
        day_str = current.strftime("%Y-%m-%d")
        # Prepend seeds to batch 1 only (deduped)
        if i == 0:
            batch = seed_emails + [e for e in batch if e not in seed_emails]
        batches[day_str] = batch
        current += timedelta(days=1)
    return {
        "campaign": slug,
        "total": len(recipients),
        "seeds": seed_emails,
        "batch_size": BATCH_SIZE,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": (current - timedelta(days=1)).strftime("%Y-%m-%d"),
        "batches": batches,
    }


def check_daily_collision(plan: dict, slug: str) -> list[str]:
    """Return list of dates where planned + existing exceeds 100."""
    warnings = []
    for day_str, emails in plan["batches"].items():
        day_total = len(emails)
        # Count other campaigns' planned sends on this date
        for plan_file in EMAIL_MARKETING.glob("campaigns/*/send-plan.json"):
            if plan_file.parent.name == slug:
                continue
            try:
                other = json.loads(plan_file.read_text())
                day_total += len(other.get("batches", {}).get(day_str, []))
            except (json.JSONDecodeError, KeyError):
                pass
        if day_total > DAILY_CAP:
            warnings.append(f"  {day_str}: {day_total} planned (cap {DAILY_CAP}) — collision with another campaign")
    return warnings


def main() -> int:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date)
    slug = args.slug

    campaign_dir = EMAIL_MARKETING / "campaigns" / slug
    if not campaign_dir.is_dir():
        sys.exit(f"error: campaign folder not found: {campaign_dir}\nRun Stage 1 first to create the campaign.")

    print(f"\n=== Audience Ingest: {slug} ===")

    # Load + validate
    valid, errors = load_csv(args.csv_path)

    print(f"\nCSV validation:")
    print(f"  Valid records  : {len(valid)}")
    print(f"  Skipped (errors): {len(errors)}")
    if errors:
        for e in errors[:10]:
            print(f"    {e}")
        if len(errors) > 10:
            print(f"    ... ({len(errors) - 10} more)")

    if not valid:
        sys.exit("error: no valid recipients found.")

    # Monthly quota check
    already_planned = current_monthly_planned(exclude_slug=slug)
    month = start_date.strftime("%B %Y")
    projected = already_planned + len(valid)
    print(f"\nMonthly quota ({month}):")
    print(f"  Already planned by other campaigns: {already_planned}")
    print(f"  This campaign adds               : {len(valid)}")
    print(f"  Projected total                  : {projected} / {MONTHLY_CAP}")
    if projected > MONTHLY_CAP:
        print(f"\nWARNING: Projected total {projected} exceeds monthly cap {MONTHLY_CAP}!")
        print("  Reduce audience size or spread send dates into next month.")
        if not args.dry_run:
            ans = input("  Continue anyway? [y/N] ").strip().lower()
            if ans != "y":
                sys.exit("Aborted.")

    # Load seeds and build send plan
    seeds = load_seeds()
    if seeds:
        print(f"\nTest seeds (prepended to batch 1): {[s['email'] for s in seeds]}")
    plan = build_send_plan(slug, valid, start_date, seeds)

    print(f"\nSend plan:")
    print(f"  Batch size: {BATCH_SIZE}/day")
    print(f"  Start date: {plan['start_date']}")
    print(f"  End date  : {plan['end_date']}")
    print(f"  Total days: {len(plan['batches'])}")
    for day, emails in list(plan["batches"].items())[:5]:
        print(f"    {day}: {len(emails)} emails")
    if len(plan["batches"]) > 5:
        print(f"    ... ({len(plan['batches']) - 5} more days)")

    # Daily collision check
    collisions = check_daily_collision(plan, slug)
    if collisions:
        print(f"\nWARNING: Daily cap collisions detected:")
        for c in collisions:
            print(c)
        print("  Consider shifting the start date for this campaign.")

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return 0

    # Write cleaned audience.csv
    out_csv = campaign_dir / "audience.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "email"])
        writer.writeheader()
        writer.writerows(valid)
    print(f"\nWrote: {out_csv}")

    # Write send-plan.json
    out_plan = campaign_dir / "send-plan.json"
    out_plan.write_text(json.dumps(plan, indent=2))
    print(f"Wrote: {out_plan}")

    # Update config.json status
    config_path = campaign_dir / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text())
        config["status"] = "Audience Loaded"
        config["audience_count"] = len(valid)
        config_path.write_text(json.dumps(config, indent=2))
        print(f"Updated config status → Audience Loaded")

    print("\nStage 2 complete. Proceed to Stage 3 (send-time research) in chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
