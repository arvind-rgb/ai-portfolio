#!/usr/bin/env python3
"""
format_stats_digest.py — print a human-readable email digest of all campaign stats.

Reads email-marketing/campaigns/*/results.json and prints a plain-text summary
suitable for piping into an email body. Called by the email-stats GH Actions
workflow right before the dawidd6/action-send-mail step.
"""

import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGNS_DIR = PROJECT_ROOT / "email-marketing" / "campaigns"


def fmt_pct(v) -> str:
    return f"{v:.1f}%" if isinstance(v, (int, float)) else "—"


def main():
    today = datetime.now().strftime("%a %b %d, %Y")
    print(f"📧 Bhookle Email Stats — {today}")
    print("=" * 60)

    if not CAMPAIGNS_DIR.is_dir():
        print("No campaigns directory found.")
        return

    campaigns = sorted(d for d in CAMPAIGNS_DIR.iterdir() if d.is_dir())
    if not campaigns:
        print("No campaigns found.")
        return

    grand_sent = grand_opened = grand_clicked = grand_bounced = 0

    for campaign_dir in campaigns:
        results_file = campaign_dir / "results.json"
        if not results_file.is_file():
            continue
        try:
            data = json.loads(results_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        sent = data.get("total_sent", 0)
        delivered = data.get("delivered", 0)
        opened = data.get("opened", 0)
        clicked = data.get("clicked", 0)
        bounced = data.get("bounced", 0)
        last_updated = data.get("last_updated", "")[:19].replace("T", " ")

        grand_sent += sent
        grand_opened += opened
        grand_clicked += clicked
        grand_bounced += bounced

        print()
        print(f"▸ {campaign_dir.name}")
        print(f"  Sent:      {sent:>5}    Delivered: {delivered:>5} ({fmt_pct(data.get('delivery_rate'))})")
        print(f"  Opened:    {opened:>5} ({fmt_pct(data.get('open_rate'))})    Clicked: {clicked:>5} ({fmt_pct(data.get('click_rate'))})")
        print(f"  Bounced:   {bounced:>5}    Complained: {data.get('complained', 0):>3}")
        if last_updated:
            print(f"  Updated:   {last_updated} UTC")

    print()
    print("─" * 60)
    print("Totals across all campaigns:")
    print(f"  Sent: {grand_sent}   Opened: {grand_opened}   Clicked: {grand_clicked}   Bounced: {grand_bounced}")
    if grand_sent:
        print(f"  Overall open rate:  {grand_opened / grand_sent * 100:.1f}%")
        print(f"  Overall click rate: {grand_clicked / grand_sent * 100:.1f}%")
    print()
    print("Full breakdown: email-marketing/campaigns-master.xlsx (attached)")


if __name__ == "__main__":
    main()
