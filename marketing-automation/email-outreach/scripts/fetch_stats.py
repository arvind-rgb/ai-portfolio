#!/usr/bin/env python3
"""
fetch_stats.py — Stage 5: poll Resend /emails/{id} for each sent message.

Run by GitHub Actions daily at 02:00 IST. Writes results.json per campaign.

Usage:
  python3 fetch_stats.py              # poll last 7 days
  python3 fetch_stats.py --days 14    # poll last N days
  python3 fetch_stats.py --campaign <slug>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"

RESEND_API = "https://api.resend.com"

# Event hierarchy — higher = better outcome tracked
EVENT_RANK = {
    "complained": -2,
    "bounced": -1,
    "sent": 1,
    "delivered": 2,
    "opened": 3,
    "clicked": 4,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch email stats from Resend API.")
    # Default 2 days: most opens/clicks arrive in 24-48h. Polling 7 days bloated
    # runtime to 18 min/run on GH Actions for ~2000 cumulative resend_ids.
    # Aggregates remain accurate because older messages are settled and update_master_xlsx
    # merges historical results.json into the master workbook.
    p.add_argument("--days", type=int, default=2, help="Poll messages sent in last N days (default: 2)")
    p.add_argument("--campaign", help="Restrict to a single campaign slug")
    return p.parse_args()


def resend_get(path: str, api_key: str) -> dict | None:
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        f"{RESEND_API}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "bhookle-email-outreach/1.0",  # Cloudflare bot-block fix
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  Rate limited — sleeping 5s", file=sys.stderr)
            time.sleep(5)
            return None
        if e.code == 404:
            return None
        raise


def fetch_campaign_stats(campaign_dir: Path, days: int, api_key: str) -> dict:
    slug = campaign_dir.name
    log_file = campaign_dir / "sent-log.csv"
    if not log_file.is_file():
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stats: dict[str, dict] = {}  # email -> {resend_id, last_event, events_seen}

    with open(log_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sent_at_str = row.get("sent_at", "")
            try:
                sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if sent_at < cutoff:
                continue
            resend_id = row.get("resend_id", "")
            email = row.get("email", "")
            if resend_id and email:
                stats[email] = {"resend_id": resend_id, "sent_at": sent_at_str, "last_event": "sent"}

    print(f"  [{slug}] Polling {len(stats)} messages from last {days} days...")

    for email, entry in stats.items():
        data = resend_get(f"/emails/{entry['resend_id']}", api_key)
        if not data:
            continue
        last_event = data.get("last_event", "sent")
        entry["last_event"] = last_event
        time.sleep(0.1)  # ~10 req/s safety

    return stats


def aggregate_results(stats: dict) -> dict:
    counts = {
        "total_sent": len(stats),
        "delivered": 0,
        "opened": 0,
        "clicked": 0,
        "bounced": 0,
        "complained": 0,
    }
    for entry in stats.values():
        event = entry.get("last_event", "sent")
        rank = EVENT_RANK.get(event, 0)
        if rank >= EVENT_RANK["delivered"]:
            counts["delivered"] += 1
        if rank >= EVENT_RANK["opened"]:
            counts["opened"] += 1
        if rank >= EVENT_RANK["clicked"]:
            counts["clicked"] += 1
        if event == "bounced":
            counts["bounced"] += 1
        if event == "complained":
            counts["complained"] += 1

    sent = counts["total_sent"]
    counts["open_rate"] = round(counts["opened"] / sent * 100, 1) if sent else 0.0
    counts["click_rate"] = round(counts["clicked"] / sent * 100, 1) if sent else 0.0
    counts["delivery_rate"] = round(counts["delivered"] / sent * 100, 1) if sent else 0.0
    counts["last_updated"] = datetime.now(timezone.utc).isoformat()
    return counts


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    args = parse_args()
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        sys.exit("error: RESEND_API_KEY not set")

    print(f"\n=== Bhookle Email Stats (last {args.days} days) ===")

    campaigns_dir = EMAIL_MARKETING / "campaigns"
    if args.campaign:
        campaign_dirs = [campaigns_dir / args.campaign]
    else:
        campaign_dirs = [d for d in campaigns_dir.iterdir() if d.is_dir()] if campaigns_dir.is_dir() else []

    for campaign_dir in sorted(campaign_dirs):
        if not campaign_dir.is_dir():
            print(f"  WARNING: {campaign_dir} not found")
            continue

        raw_stats = fetch_campaign_stats(campaign_dir, args.days, api_key)
        if not raw_stats:
            print(f"  [{campaign_dir.name}] No recent sends found")
            continue

        results = aggregate_results(raw_stats)

        out = campaign_dir / "results.json"
        out.write_text(json.dumps(results, indent=2))
        print(f"  [{campaign_dir.name}] open_rate={results['open_rate']}%  "
              f"click_rate={results['click_rate']}%  "
              f"bounced={results['bounced']}  → {out.name}")

    print("\nDone. Run update_master_xlsx.py to sync results into Excel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
