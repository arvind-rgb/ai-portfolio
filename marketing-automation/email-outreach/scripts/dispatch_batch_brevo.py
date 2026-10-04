#!/usr/bin/env python3
"""
dispatch_batch_brevo.py — Stage 4 (Brevo transport): daily email dispatch via Brevo.

Drop-in replacement for dispatch_batch.py that sends through Brevo's transactional
API (https://api.brevo.com/v3/smtp/email) instead of Resend. All campaign content,
personalisation, image embedding, send-plan batching, and the idempotent sent-log
are retained verbatim — only the send transport changes.

Why Brevo:
  - Free tier: 300 emails/day (vs Resend 100/day) — the whole ~1.5k list clears in ~5 days.
  - Stats are aggregated server-side by TAG and never expire, which fixes the
    "78 vs 1,347" stats bug (Resend's per-message events aged out of the 2-day poll window).

Every send is tagged with the campaign slug so fetch_stats_brevo.py can pull retained,
cumulative open/click/bounce totals per campaign in a single call.

Usage:
  python3 dispatch_batch_brevo.py                 # dispatch today's batches
  python3 dispatch_batch_brevo.py --dry-run       # preview without sending
  python3 dispatch_batch_brevo.py --check-env     # verify credentials + sender
  python3 dispatch_batch_brevo.py --campaign <slug>
  python3 dispatch_batch_brevo.py --test a@b.com  # send only to these addrs
  python3 dispatch_batch_brevo.py --cap 90        # override daily cap (warmup ramp)

Env (.env or GitHub secrets):
  BREVO_API_KEY          required
  EMAIL_FROM_EMAIL       optional (default team@example.com)
  EMAIL_FROM_NAME        optional (default Bhookle)
  EMAIL_ADMIN_RECIPIENT  optional (default owner@example.com)
  GMAIL_USER / GMAIL_APP_PASSWORD   for the dispatch report (unchanged)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"

BREVO_API = "https://api.brevo.com/v3"
FROM_EMAIL = os.environ.get("EMAIL_FROM_EMAIL", "team@example.com")
FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Bhookle")
DAILY_CAP = 300  # Brevo free-tier daily limit. Override with --cap for warmup ramps.
RATE_SLEEP = 0.12  # ~8 req/s, safely under Brevo's ~10 req/s transactional limit.


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dispatch today's email batches via Brevo.")
    p.add_argument("--dry-run", action="store_true", help="Preview without sending")
    p.add_argument("--check-env", action="store_true", help="Verify env + sender only")
    p.add_argument("--campaign", help="Restrict to a single campaign slug")
    p.add_argument("--cap", type=int, default=DAILY_CAP, help=f"Daily send cap (default {DAILY_CAP})")
    p.add_argument("--test", help="Send only to these emails (comma-separated). Bypasses send-plan date check.")
    p.add_argument("--test-name", help="Name for --test recipients not in audience (default: 'there')")
    return p.parse_args()


def _headers(api_key: str) -> dict:
    return {
        "api-key": api_key,
        "accept": "application/json",
        "content-type": "application/json",
        "User-Agent": "bhookle-email-outreach/1.0",
    }


def brevo_get(path: str, api_key: str) -> dict | None:
    import urllib.request
    import urllib.error
    req = urllib.request.Request(f"{BREVO_API}{path}", headers=_headers(api_key))
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  Brevo GET {path} -> HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}")
        return None


def brevo_send(message: dict, api_key: str) -> str | None:
    """POST one transactional email. Returns Brevo messageId, or None on failure."""
    import urllib.request
    import urllib.error
    body = json.dumps(message).encode()
    req = urllib.request.Request(
        f"{BREVO_API}/smtp/email", data=body, headers=_headers(api_key), method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            return data.get("messageId", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:200]
        print(f"  Brevo send error HTTP {e.code}: {detail}")
        return None


def check_sender(api_key: str) -> bool:
    """Confirm the API key works and the from-address is a verified/authenticated sender."""
    acct = brevo_get("/account", api_key)
    if not acct:
        print("ERROR: BREVO_API_KEY rejected or /account unreachable.")
        return False
    print(f"  Account: {acct.get('email', '(unknown)')}  plan credits ok")
    senders = brevo_get("/senders", api_key)
    if senders and isinstance(senders.get("senders"), list):
        addrs = {s.get("email", "").lower(): s.get("active") for s in senders["senders"]}
        if FROM_EMAIL.lower() in addrs:
            active = addrs[FROM_EMAIL.lower()]
            print(f"  Sender {FROM_EMAIL}: {'active/verified' if active else 'NOT yet verified'}")
            if not active:
                print("  WARN: sender not verified — sends may soft-fail. Verify in Brevo > Senders & Domains.")
        else:
            print(f"  WARN: {FROM_EMAIL} not in Brevo senders list — add + authenticate the domain first.")
    return True


def count_sent_today(all_campaign_dirs: list[Path]) -> int:
    today = date.today().isoformat()
    total = 0
    for campaign_dir in all_campaign_dirs:
        sent_log = campaign_dir / "sent-log.csv"
        if not sent_log.is_file():
            continue
        with open(sent_log, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("sent_at") or "").startswith(today):
                    total += 1
    return total


def build_name_lookup(campaign_dir: Path) -> dict[str, str]:
    lookup: dict[str, str] = {}
    aud = campaign_dir / "audience.csv"
    if aud.is_file():
        with open(aud, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email = (row.get("email") or "").strip().lower()
                name = (row.get("name") or "").strip()
                if email:
                    lookup[email] = name
    seeds_file = SCRIPT_DIR.parent / "references" / "test-seeds.json"
    if seeds_file.is_file():
        for s in json.loads(seeds_file.read_text()).get("seeds", []):
            lookup[s["email"].lower()] = s["name"]
    return lookup


def personalise(text: str, email: str, name_lookup: dict[str, str], fallback: str = "there") -> str:
    name = name_lookup.get(email.lower(), "") or fallback
    return text.replace("[Name]", name)


def embed_images(html: str, campaign_dir: Path) -> str:
    import re as _re
    urls_file = campaign_dir / "image-urls.json"
    url_map = json.loads(urls_file.read_text()) if urls_file.is_file() else {}

    def replacer(m):
        src = m.group(1)
        if src.startswith("http") or src.startswith("data:"):
            return m.group(0)
        filename = Path(src).name
        if filename in url_map:
            return f'src="{url_map[filename]}"'
        return m.group(0)

    return _re.sub(r'src="([^"]+)"', replacer, html)


def load_campaign_email(campaign_dir: Path) -> dict | None:
    subject_file = campaign_dir / "subject.txt"
    html_file = campaign_dir / "body.html"
    txt_file = campaign_dir / "body.txt"
    subject = subject_file.read_text().strip() if subject_file.is_file() else ""
    body_html = html_file.read_text() if html_file.is_file() else None
    body_txt = txt_file.read_text() if txt_file.is_file() else ""
    if not subject:
        return None
    return {"subject": subject, "html": body_html, "text": body_txt}


def dispatch_campaign(campaign_dir: Path, today_str: str, api_key: str, dry_run: bool,
                      cap_remaining: int, test_emails: list[str] | None = None,
                      test_name: str = "there") -> int:
    slug = campaign_dir.name
    plan_file = campaign_dir / "send-plan.json"
    if not plan_file.is_file() and not test_emails:
        return 0

    if test_emails:
        today_batch = test_emails
    else:
        plan = json.loads(plan_file.read_text())
        today_batch = plan.get("batches", {}).get(today_str, [])
        if not today_batch:
            return 0
        # Idempotency: skip emails already logged for this campaign on this date
        already_sent_emails = set()
        log_file = campaign_dir / "sent-log.csv"
        if log_file.is_file():
            with open(log_file, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("batch_date") == today_str:
                        already_sent_emails.add(row.get("email", "").lower())
        planned_count = len(today_batch)
        today_batch = [e for e in today_batch if e.lower() not in already_sent_emails]
        if not today_batch:
            print(f"  [{slug}] All {planned_count} emails for {today_str} already sent — skipping")
            return 0
        if already_sent_emails:
            print(f"  [{slug}] {len(already_sent_emails)} already sent today, {len(today_batch)} remaining")

    # Respect the remaining daily cap
    if not test_emails and len(today_batch) > cap_remaining:
        print(f"  [{slug}] Trimming {len(today_batch)} -> {cap_remaining} to stay within daily cap")
        today_batch = today_batch[:cap_remaining]

    email_content = load_campaign_email(campaign_dir)
    if not email_content:
        print(f"  [{slug}] SKIP: missing subject.txt or body files")
        return 0

    name_lookup = build_name_lookup(campaign_dir)
    print(f"  [{slug}] {len(today_batch)} emails to send")

    if dry_run:
        for addr in today_batch:
            name = name_lookup.get(addr.lower(), "(no name)")
            print(f"  [{slug}] [dry-run] -> {addr} as '{name}'")
        return 0

    sent_rows = []
    now_utc = datetime.now(timezone.utc).isoformat()
    html_template = email_content["html"]

    for email_addr in today_batch:
        name = name_lookup.get(email_addr.lower(), "") or test_name
        message = {
            "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
            "to": [{"email": email_addr, "name": name}],
            "subject": personalise(email_content["subject"], email_addr, name_lookup, test_name),
            "textContent": personalise(email_content["text"], email_addr, name_lookup, test_name),
            "headers": {"X-Campaign": slug, "X-Batch-Date": today_str},
            # Tag every send with the slug so Brevo aggregates retained stats per campaign.
            "tags": [slug],
        }
        if html_template:
            html = personalise(html_template, email_addr, name_lookup, test_name)
            message["htmlContent"] = embed_images(html, campaign_dir)
        msg_id = brevo_send(message, api_key)
        if msg_id is not None:
            sent_rows.append({
                "message_id": msg_id,
                "email": email_addr,
                "campaign": slug,
                "sent_at": now_utc,
                "batch_date": today_str,
            })
        time.sleep(RATE_SLEEP)

    if not sent_rows:
        return 0

    log_file = campaign_dir / "sent-log.csv"
    write_header = not log_file.is_file()
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["message_id", "email", "campaign", "sent_at", "batch_date"])
        if write_header:
            writer.writeheader()
        writer.writerows(sent_rows)

    print(f"  [{slug}] Sent {len(sent_rows)} emails — logged to {log_file.name}")
    return len(sent_rows)


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    args = parse_args()
    api_key = os.environ.get("BREVO_API_KEY", "")

    print("\n=== Bhookle Email Dispatch (Brevo) ===")
    today_str = date.today().isoformat()
    print(f"Date: {today_str}")

    if not api_key:
        print("ERROR: BREVO_API_KEY not set in .env or environment.")
        return 1

    print("\nChecking Brevo account + sender...")
    if not check_sender(api_key):
        return 1

    if args.check_env:
        print("\nEnvironment OK.")
        return 0

    campaigns_dir = EMAIL_MARKETING / "campaigns"
    if args.campaign:
        campaign_dirs = [campaigns_dir / args.campaign]
        if not campaign_dirs[0].is_dir():
            sys.exit(f"error: campaign not found: {args.campaign}")
    else:
        campaign_dirs = [d for d in campaigns_dir.iterdir() if d.is_dir()]

    if not campaign_dirs:
        print("No campaigns found.")
        return 0

    already_sent = count_sent_today(campaign_dirs)
    cap = args.cap
    remaining_cap = max(0, cap - already_sent)
    print(f"\nDaily quota: {already_sent} already sent today, cap {cap}, {remaining_cap} remaining")

    test_emails = [e.strip() for e in args.test.split(",")] if args.test else None
    test_name = args.test_name or "there"
    if test_emails:
        print(f"\nTEST MODE — sending only to: {test_emails}")

    print(f"\nDispatching{' [DRY RUN]' if args.dry_run else ''}...")
    total_sent = 0

    for campaign_dir in sorted(campaign_dirs):
        if not test_emails and remaining_cap <= 0:
            print(f"  [{campaign_dir.name}] SKIP: daily cap reached")
            continue
        sent = dispatch_campaign(
            campaign_dir, today_str, api_key, args.dry_run,
            remaining_cap, test_emails, test_name,
        )
        total_sent += sent
        if not test_emails:
            remaining_cap -= sent

    print(f"\nTotal sent today: {total_sent}")

    if not args.dry_run and not test_emails and total_sent > 0:
        send_dispatch_report(campaign_dirs, today_str)

    return 0


def send_dispatch_report(campaign_dirs: list[Path], today_str: str) -> None:
    """Email a per-campaign summary of today's sends to the admin via Gmail SMTP.

    Counts come from the sent-log (what we dispatched). Delivery/open enrichment is
    left to fetch_stats_brevo.py, which reads Brevo's retained per-tag aggregates.
    """
    admin = os.environ.get("EMAIL_ADMIN_RECIPIENT", "owner@example.com")
    per_campaign: list[dict] = []
    for campaign_dir in sorted(campaign_dirs):
        log_file = campaign_dir / "sent-log.csv"
        if not log_file.is_file():
            continue
        today_rows = []
        with open(log_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("batch_date") == today_str:
                    today_rows.append(row)
        if today_rows:
            per_campaign.append({
                "slug": campaign_dir.name,
                "name": _read_campaign_name(campaign_dir),
                "sent": len(today_rows),
            })
    if not per_campaign:
        return

    total_sent = sum(c["sent"] for c in per_campaign)
    subject = f"📬 Bhookle dispatch report (Brevo) — {today_str} ({total_sent} sent)"
    rows_html = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #FFE0B2;'>{c['name']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #FFE0B2;text-align:center;'><b>{c['sent']}</b></td></tr>"
        for c in per_campaign
    )
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:600px;background:#FFF8EC;padding:24px;'>"
        f"<h2 style='color:#3D0C11;margin:0 0 8px;'>📬 Bhookle dispatch report</h2>"
        f"<p style='color:#666;margin:0 0 20px;'>{today_str} · {total_sent} emails sent today · via Brevo</p>"
        f"<table style='width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;'>"
        f"<thead><tr style='background:#FF6B00;color:#fff;'>"
        f"<th style='padding:10px;text-align:left;'>Campaign</th><th style='padding:10px;'>Sent</th>"
        f"</tr></thead><tbody>{rows_html}"
        f"<tr style='background:#FFE0B2;font-weight:bold;'><td style='padding:8px;'>TOTAL</td>"
        f"<td style='padding:8px;text-align:center;'>{total_sent}</td></tr></tbody></table>"
        f"<p style='color:#888;font-size:12px;margin-top:24px;'>Auto-sent by email-outreach skill (Brevo) · {today_str}</p></div>"
    )
    text = f"Bhookle dispatch report (Brevo) — {today_str}\n\n" + "\n".join(
        f"  {c['name']}: sent={c['sent']}" for c in per_campaign
    ) + f"\n\nTOTAL sent={total_sent}\n"

    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_user or not gmail_pass:
        print("  WARN: GMAIL_USER/GMAIL_APP_PASSWORD not set — skipping report")
        return
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Bhookle Dispatch Bot <{gmail_user}>"
        msg["To"] = admin
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, [admin], msg.as_string())
        print(f"  Report sent to {admin} via Gmail SMTP")
    except Exception as e:
        print(f"  ERROR sending report: {e}")


def _read_campaign_name(campaign_dir: Path) -> str:
    cfg = campaign_dir / "config.json"
    if cfg.is_file():
        try:
            return json.loads(cfg.read_text()).get("name", campaign_dir.name)
        except Exception:
            pass
    return campaign_dir.name


if __name__ == "__main__":
    raise SystemExit(main())
