#!/usr/bin/env python3
"""
Fetch daily stats for an active Lemlist campaign, write JSON to disk,
and detect if the campaign has reached completion.

Outputs:
  email-marketing/lemlist/{campaign-slug}/daily-{YYYY-MM-DD}.json
  email-marketing/lemlist/{campaign-slug}/state.json   ← persistent state for completion detection

Exits:
  0 = success (stats fetched, state updated)
  3 = campaign completed today (signals workflow to send completion email)
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
import lemlist_api as lem

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "email-marketing" / "lemlist"

# IST timezone for date stamping
IST = timezone(timedelta(hours=5, minutes=30))


def slugify(name: str) -> str:
    return name.lower().replace(" ", "-").replace("/", "-").replace(",", "")[:60]


def fetch(campaign_id: str):
    """Pull all data needed for daily digest + completion detection."""
    campaign = lem.get_campaign(campaign_id)
    name = campaign.get("name", "unknown")
    slug = slugify(name)

    # Stats window: campaign creation → now
    created = campaign.get("createdAt", datetime.now(IST).isoformat())
    end = datetime.now(IST).isoformat()
    stats = lem.get_campaign_stats(campaign_id, created, end)

    # Lead state breakdown
    leads = lem.get_campaign_leads(campaign_id, limit=500)
    from collections import Counter
    lead_states = Counter(l.get("state", "unknown") for l in leads)

    # Completion logic: campaign is "done" when every lead is in a terminal state
    # Terminal states: ended (completed sequence), unsubscribed, bounced, interested, notInterested
    TERMINAL = {"ended", "unsubscribed", "bounced", "interested", "notInterested",
                "endOfSequence", "interrupted", "deleted"}
    total = len(leads)
    terminal_count = sum(c for s, c in lead_states.items() if s in TERMINAL)
    is_complete = total > 0 and terminal_count == total

    return {
        "campaign_id": campaign_id,
        "campaign_name": name,
        "slug": slug,
        "fetched_at": end,
        "campaign_status": campaign.get("status"),
        "total_leads": total,
        "lead_states": dict(lead_states),
        "terminal_count": terminal_count,
        "is_complete": is_complete,
        "stats": stats,
    }


def save_and_detect_completion(data: dict) -> bool:
    """Save daily snapshot + persistent state. Return True if completion JUST detected."""
    slug = data["slug"]
    out_dir = DATA_ROOT / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(IST).strftime("%Y-%m-%d")
    daily_path = out_dir / f"daily-{today}.json"
    state_path = out_dir / "state.json"

    # Load previous state (if any) to detect transition
    prev_state = {}
    if state_path.exists():
        try:
            prev_state = json.loads(state_path.read_text())
        except Exception:
            pass

    completion_just_detected = (
        data["is_complete"]
        and not prev_state.get("completion_notified_at")
    )

    # Write daily snapshot
    daily_path.write_text(json.dumps(data, indent=2, default=str))

    # Update state
    new_state = {
        **prev_state,
        "campaign_id": data["campaign_id"],
        "campaign_name": data["campaign_name"],
        "last_fetched": data["fetched_at"],
        "is_complete": data["is_complete"],
    }
    if completion_just_detected:
        new_state["completion_notified_at"] = datetime.now(IST).isoformat()
    state_path.write_text(json.dumps(new_state, indent=2))

    return completion_just_detected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign-id", required=False,
                    help="Campaign ID. If omitted, processes all 'running' campaigns.")
    args = ap.parse_args()

    if args.campaign_id:
        campaign_ids = [args.campaign_id]
    else:
        # Auto-discover: all running campaigns
        all_camps = lem.list_campaigns()
        campaign_ids = [c["_id"] for c in all_camps if c.get("status") == "running"]
        if not campaign_ids:
            print("ℹ️  No running campaigns found.")
            return 0

    any_just_completed = False
    for cid in campaign_ids:
        print(f"📊 Fetching stats for {cid} ...")
        data = fetch(cid)
        just_done = save_and_detect_completion(data)
        print(f"   {data['campaign_name']}: {data['terminal_count']}/{data['total_leads']} leads terminal "
              f"({'✅ COMPLETE' if data['is_complete'] else '🟡 in progress'})")
        if just_done:
            print(f"   🎉 Just completed — flagging for notification email")
            any_just_completed = True

    # Exit code 3 signals to the GH workflow that completion email should fire
    return 3 if any_just_completed else 0


if __name__ == "__main__":
    sys.exit(main())
