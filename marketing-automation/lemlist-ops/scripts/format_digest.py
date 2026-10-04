#!/usr/bin/env python3
"""
Format the latest Lemlist daily-stats JSON into a Bhookle-branded HTML digest
and a plain-text fallback, ready to email via Gmail SMTP.

Outputs:
  /tmp/lemlist-digest.html
  /tmp/lemlist-digest.txt
  /tmp/lemlist-digest-subject.txt
  /tmp/lemlist-digest-mode.txt    ('daily' or 'completion')
"""
import sys
import json
import glob
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = ROOT / "email-marketing" / "lemlist"
IST = timezone(timedelta(hours=5, minutes=30))


def load_latest_for_campaign(slug_dir: Path) -> dict:
    daily_files = sorted(slug_dir.glob("daily-*.json"))
    if not daily_files:
        return {}
    return json.loads(daily_files[-1].read_text())


def calc_metrics(data: dict) -> dict:
    """Pull commonly-used numbers from raw stats response."""
    stats = data.get("stats", {})
    # The Lemlist v2 stats response has various nested structures; we defensively
    # walk both top-level shortcuts and per-message metrics.

    total = data.get("total_leads", 0)
    states = data.get("lead_states", {})

    # Email metrics (cumulative)
    sent = stats.get("emailsSent", stats.get("sent", 0))
    delivered = stats.get("emailsDelivered", stats.get("delivered", 0))
    opened = stats.get("emailsOpened", stats.get("opened", 0))
    clicked = stats.get("emailsClicked", stats.get("clicked", 0))
    replied = stats.get("emailsReplied", stats.get("replied", 0))
    bounced = stats.get("emailsBounced", stats.get("bounced", 0))

    # LinkedIn metrics
    li_invited = stats.get("linkedinInvited", 0)
    li_accepted = stats.get("linkedinAccepted", 0)
    li_messaged = stats.get("linkedinMessaged", 0)

    # Rates
    open_rate = round(100 * opened / sent, 1) if sent else 0
    reply_rate = round(100 * replied / sent, 1) if sent else 0
    bounce_rate = round(100 * bounced / sent, 1) if sent else 0
    accept_rate = round(100 * li_accepted / li_invited, 1) if li_invited else 0

    # Lead state quick-grouping
    in_flight = sum(c for s, c in states.items()
                    if s in {"active", "review", "reviewed", "scheduled", "running", "scanned"})
    interested = states.get("interested", 0)
    not_interested = states.get("notInterested", 0)
    unsubscribed = states.get("unsubscribed", 0)
    ended = states.get("ended", 0) + states.get("endOfSequence", 0)

    return {
        "total": total,
        "sent": sent, "delivered": delivered, "opened": opened, "clicked": clicked,
        "replied": replied, "bounced": bounced,
        "open_rate": open_rate, "reply_rate": reply_rate, "bounce_rate": bounce_rate,
        "li_invited": li_invited, "li_accepted": li_accepted, "li_messaged": li_messaged,
        "accept_rate": accept_rate,
        "in_flight": in_flight, "interested": interested,
        "not_interested": not_interested, "unsubscribed": unsubscribed, "ended": ended,
    }


def health_status(m: dict) -> tuple[str, str]:
    """Return (emoji, label) — green/yellow/red based on key metrics."""
    if m["bounce_rate"] > 5:
        return ("🔴", "RED — bounce rate above 5%, pause immediately")
    if m["bounce_rate"] > 2:
        return ("🟡", "YELLOW — bounce rate climbing, monitor closely")
    if m["sent"] >= 10 and m["open_rate"] < 25:
        return ("🟡", "YELLOW — low open rate, consider tweaking subject line")
    return ("✅", "GREEN — all metrics healthy")


def html_block(data: dict, mode: str = "daily") -> str:
    m = calc_metrics(data)
    health_emoji, health_msg = health_status(m)
    today_ist = datetime.now(IST).strftime("%a %b %d, %Y")
    title_prefix = "🎉 CAMPAIGN COMPLETE" if mode == "completion" else "📊 Daily Report"
    title = f"{title_prefix} — {data.get('campaign_name','?')}"

    return f"""\
<html><body style="font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color:#1A1A1A; background:#FFF8EC; padding:24px; margin:0;">
  <div style="max-width:600px; margin:0 auto; background:#FFFFFF; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    <div style="background:#FFA70B; padding:18px 24px;">
      <div style="color:#2D1B3D; font-weight:700; font-size:20px; letter-spacing:-0.01em;">Bhookle · Lemlist Ops</div>
    </div>
    <div style="padding:24px;">
      <h2 style="color:#2D1B3D; margin:0 0 6px; font-size:20px;">{title}</h2>
      <p style="margin:0 0 18px; color:#6E4F7A; font-size:13px;">{today_ist} · {data.get('campaign_status','?')}</p>

      <table style="width:100%; border-collapse:collapse; margin:8px 0 18px;">
        <tr>
          <td style="padding:12px; background:#FFF8EC; border-radius:8px; width:33%;">
            <div style="font-size:11px; color:#6E4F7A;">EMAILS SENT</div>
            <div style="font-size:22px; font-weight:700; color:#2D1B3D;">{m['sent']}</div>
          </td>
          <td style="width:6px;"></td>
          <td style="padding:12px; background:#FFF8EC; border-radius:8px; width:33%;">
            <div style="font-size:11px; color:#6E4F7A;">OPEN RATE</div>
            <div style="font-size:22px; font-weight:700; color:#2D1B3D;">{m['open_rate']}%</div>
          </td>
          <td style="width:6px;"></td>
          <td style="padding:12px; background:#FFF8EC; border-radius:8px; width:33%;">
            <div style="font-size:11px; color:#6E4F7A;">REPLIES</div>
            <div style="font-size:22px; font-weight:700; color:#2D1B3D;">{m['replied']} <span style="font-size:12px; color:#6E4F7A;">({m['reply_rate']}%)</span></div>
          </td>
        </tr>
      </table>

      <table style="width:100%; border-collapse:collapse; margin:0 0 18px;">
        <tr>
          <td style="padding:12px; background:#F4ECFB; border-radius:8px; width:33%;">
            <div style="font-size:11px; color:#6E4F7A;">LI INVITES SENT</div>
            <div style="font-size:22px; font-weight:700; color:#2D1B3D;">{m['li_invited']}</div>
          </td>
          <td style="width:6px;"></td>
          <td style="padding:12px; background:#F4ECFB; border-radius:8px; width:33%;">
            <div style="font-size:11px; color:#6E4F7A;">LI ACCEPTED</div>
            <div style="font-size:22px; font-weight:700; color:#2D1B3D;">{m['li_accepted']} <span style="font-size:12px; color:#6E4F7A;">({m['accept_rate']}%)</span></div>
          </td>
          <td style="width:6px;"></td>
          <td style="padding:12px; background:#F4ECFB; border-radius:8px; width:33%;">
            <div style="font-size:11px; color:#6E4F7A;">LI MESSAGES</div>
            <div style="font-size:22px; font-weight:700; color:#2D1B3D;">{m['li_messaged']}</div>
          </td>
        </tr>
      </table>

      <div style="padding:14px 16px; background:#FFE9C2; border-left:4px solid #FFA70B; border-radius:6px; margin:18px 0;">
        <div style="font-weight:700; color:#2D1B3D; margin-bottom:4px;">Lead Pipeline ({m['total']} total)</div>
        <div style="color:#6E4F7A; font-size:13px; line-height:1.6;">
          🔄 In flight: <strong>{m['in_flight']}</strong> &nbsp;·&nbsp;
          ✅ Done: <strong>{m['ended']}</strong> &nbsp;·&nbsp;
          🔥 Interested: <strong>{m['interested']}</strong> &nbsp;·&nbsp;
          ❌ Not interested: <strong>{m['not_interested']}</strong> &nbsp;·&nbsp;
          🚫 Unsubscribed: <strong>{m['unsubscribed']}</strong> &nbsp;·&nbsp;
          ⚠️ Bounced: <strong>{m['bounced']}</strong>
        </div>
      </div>

      <div style="padding:12px 14px; background:#F5F5F5; border-radius:6px; font-size:13px; color:#2D1B3D;">
        <strong>{health_emoji} {health_msg}</strong>
      </div>

      {'<div style="margin-top:18px; padding:14px; background:#E8F5E9; border-radius:6px; color:#1B5E20;"><strong>🎉 Campaign sequence is fully complete.</strong> Review interested leads in Lemlist Inbox and plan next batch.</div>' if mode == 'completion' else ''}

      <p style="margin:24px 0 0; font-size:12px; color:#6E4F7A;">
        Open the campaign:
        <a href="https://app.lemlist.com/campaigns/{data.get('campaign_id','')}/leads" style="color:#FFA70B; text-decoration:none;">app.lemlist.com</a>
      </p>
    </div>
  </div>
</body></html>"""


def text_block(data: dict, mode: str = "daily") -> str:
    m = calc_metrics(data)
    health_emoji, health_msg = health_status(m)
    today_ist = datetime.now(IST).strftime("%a %b %d, %Y")
    prefix = "🎉 CAMPAIGN COMPLETE" if mode == "completion" else "📊 Daily Report"
    return f"""{prefix} — {data.get('campaign_name','?')}
{today_ist} · status: {data.get('campaign_status','?')}
─────────────────────────────────────────────

📧 EMAIL
   Sent:        {m['sent']}
   Opened:      {m['opened']} ({m['open_rate']}%)
   Replied:     {m['replied']} ({m['reply_rate']}%)
   Bounced:     {m['bounced']} ({m['bounce_rate']}%)

🔗 LINKEDIN
   Invites:     {m['li_invited']}
   Accepted:    {m['li_accepted']} ({m['accept_rate']}%)
   Messages:    {m['li_messaged']}

👥 LEAD PIPELINE ({m['total']} total)
   In flight:       {m['in_flight']}
   Done:            {m['ended']}
   🔥 Interested:    {m['interested']}
   Not interested:  {m['not_interested']}
   Unsubscribed:    {m['unsubscribed']}

🚦 HEALTH: {health_emoji} {health_msg}

Lemlist: https://app.lemlist.com/campaigns/{data.get('campaign_id','')}/leads
"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "completion"], default="daily")
    ap.add_argument("--campaign-slug", help="If omitted, uses most-recent daily file across all campaigns")
    args = ap.parse_args()

    # Pick the campaign to digest
    if args.campaign_slug:
        slug_dir = DATA_ROOT / args.campaign_slug
    else:
        # Most recent daily-*.json across all campaign slugs
        all_dailies = sorted(DATA_ROOT.glob("*/daily-*.json"))
        if not all_dailies:
            print("⚠️  No daily snapshots found. Run fetch_daily_stats.py first.")
            return 1
        slug_dir = all_dailies[-1].parent

    data = load_latest_for_campaign(slug_dir)
    if not data:
        print(f"⚠️  No data in {slug_dir}")
        return 1

    today_ist = datetime.now(IST).strftime("%a %b %d")
    subject_prefix = "🎉 Bhookle Lemlist — Campaign Complete" if args.mode == "completion" \
                     else "📊 Bhookle Lemlist — Daily Report"
    subject = f"{subject_prefix} ({today_ist}) — {data.get('campaign_name','?')}"

    Path("/tmp/lemlist-digest.html").write_text(html_block(data, args.mode))
    Path("/tmp/lemlist-digest.txt").write_text(text_block(data, args.mode))
    Path("/tmp/lemlist-digest-subject.txt").write_text(subject)
    Path("/tmp/lemlist-digest-mode.txt").write_text(args.mode)

    print(f"✅ Digest ready ({args.mode})")
    print(f"   Subject: {subject}")
    print(f"   HTML:    /tmp/lemlist-digest.html ({Path('/tmp/lemlist-digest.html').stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
