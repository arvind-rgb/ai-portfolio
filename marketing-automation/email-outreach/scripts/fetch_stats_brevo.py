#!/usr/bin/env python3
"""
fetch_stats_brevo.py — Stage 5 (Brevo transport): pull retained per-campaign stats.

Replaces fetch_stats.py. Instead of polling each message id inside a 2-day window
(the Resend approach that silently truncated totals to the last batch), this queries
Brevo's aggregated transactional report BY TAG. Brevo keeps these aggregates
server-side and cumulative, so the full-campaign totals never age out.

Writes results.json per campaign in the SAME schema the old fetcher used, so
update_master_xlsx.py keeps working unchanged.

Usage:
  python3 fetch_stats_brevo.py                    # all campaigns, full history
  python3 fetch_stats_brevo.py --campaign <slug>
  python3 fetch_stats_brevo.py --start 2026-07-01 --end 2026-07-31

Env: BREVO_API_KEY
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"
BREVO_API = "https://api.brevo.com/v3"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch retained per-campaign stats from Brevo (by tag).")
    p.add_argument("--campaign", help="Restrict to a single campaign slug")
    p.add_argument("--start", help="Start date YYYY-MM-DD (default: campaign start or omitted)")
    p.add_argument("--end", help="End date YYYY-MM-DD (default: today)")
    return p.parse_args()


def brevo_get(path: str, api_key: str) -> dict | None:
    req = urllib.request.Request(
        f"{BREVO_API}{path}",
        headers={"api-key": api_key, "accept": "application/json",
                 "User-Agent": "bhookle-email-outreach/1.0"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  Brevo GET {path} -> HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}")
        return None


def sent_log_count(campaign_dir: Path) -> int:
    """Authoritative count of what WE actually dispatched (our own record)."""
    log_file = campaign_dir / "sent-log.csv"
    if not log_file.is_file():
        return 0
    with open(log_file, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def campaign_dates(campaign_dir: Path) -> tuple[str | None, str | None]:
    cfg = campaign_dir / "config.json"
    if cfg.is_file():
        try:
            c = json.loads(cfg.read_text())
            return c.get("start_date"), c.get("end_date")
        except Exception:
            pass
    return None, None


def fetch_tag_report(slug: str, api_key: str, start: str | None, end: str | None) -> dict | None:
    params = {"tag": slug}
    if start:
        params["startDate"] = start
    if end:
        params["endDate"] = end
    qs = urllib.parse.urlencode(params)
    return brevo_get(f"/smtp/statistics/aggregatedReport?{qs}", api_key)


def aggregate_results(report: dict, total_sent: int) -> dict:
    """Map Brevo's aggregatedReport fields to our results.json schema."""
    delivered = int(report.get("delivered", 0))
    opened = int(report.get("uniqueOpens", report.get("opens", 0)))
    clicked = int(report.get("uniqueClicks", report.get("clicks", 0)))
    bounced = int(report.get("hardBounces", 0)) + int(report.get("softBounces", 0))
    complained = int(report.get("spamReports", 0))
    # Prefer our own sent-log count; fall back to Brevo's request count.
    sent = total_sent or int(report.get("requests", 0))
    return {
        "total_sent": sent,
        "delivered": delivered,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "complained": complained,
        "open_rate": round(opened / sent * 100, 1) if sent else 0.0,
        "click_rate": round(clicked / sent * 100, 1) if sent else 0.0,
        "delivery_rate": round(delivered / sent * 100, 1) if sent else 0.0,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    args = parse_args()
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not api_key:
        sys.exit("error: BREVO_API_KEY not set")

    print("\n=== Bhookle Email Stats (Brevo, retained per-tag aggregates) ===")

    campaigns_dir = EMAIL_MARKETING / "campaigns"
    if args.campaign:
        campaign_dirs = [campaigns_dir / args.campaign]
    else:
        campaign_dirs = [d for d in campaigns_dir.iterdir() if d.is_dir()] if campaigns_dir.is_dir() else []

    for campaign_dir in sorted(campaign_dirs):
        if not campaign_dir.is_dir():
            continue
        slug = campaign_dir.name
        cfg_start, cfg_end = campaign_dates(campaign_dir)
        start = args.start or cfg_start
        end = args.end or datetime.now(timezone.utc).date().isoformat()

        report = fetch_tag_report(slug, api_key, start, end)
        if report is None:
            print(f"  [{slug}] No Brevo report returned (tag may have no sends yet)")
            continue

        total_sent = sent_log_count(campaign_dir)
        results = aggregate_results(report, total_sent)
        (campaign_dir / "results.json").write_text(json.dumps(results, indent=2))
        print(f"  [{slug}] sent={results['total_sent']} delivered={results['delivered']} "
              f"open={results['open_rate']}% click={results['click_rate']}% "
              f"bounced={results['bounced']} -> results.json")

    print("\nDone. Run update_master_xlsx.py to sync results into Excel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
