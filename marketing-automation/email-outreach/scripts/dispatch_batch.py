#!/usr/bin/env python3
"""
dispatch_batch.py — Stage 4: daily email dispatch via Resend batch API.

Run by GitHub Actions on the daily cron schedule.
Also runnable locally for testing.

Usage:
  python3 dispatch_batch.py               # dispatch today's batches
  python3 dispatch_batch.py --dry-run     # preview without sending
  python3 dispatch_batch.py --check-env  # verify credentials + domain
  python3 dispatch_batch.py --campaign <slug>  # single campaign only
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
EMAIL_MARKETING = PROJECT_ROOT / "email-marketing"

RESEND_API = "https://api.resend.com"
FROM_EMAIL = "team@example.com"
FROM_NAME = "Bhookle"
DAILY_CAP = 100
BATCH_CHUNK = 100  # Resend max per batch call


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dispatch today's email batches via Resend.")
    p.add_argument("--dry-run", action="store_true", help="Preview without sending")
    p.add_argument("--check-env", action="store_true", help="Verify env + domain only")
    p.add_argument("--campaign", help="Restrict to a single campaign slug")
    p.add_argument("--test", help="Send only to these emails (comma-separated). Bypasses send-plan date check.")
    p.add_argument("--test-name", help="Name to use for --test recipients not in audience (default: 'there')")
    return p.parse_args()


HEADERS_BASE = {
    "Authorization": "",          # filled per-call
    "User-Agent": "bhookle-email-outreach/1.0",
}


def resend_get(path: str, api_key: str) -> dict:
    import urllib.request
    req = urllib.request.Request(
        f"{RESEND_API}{path}",
        headers={**HEADERS_BASE, "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def resend_post_batch(messages: list[dict], api_key: str) -> list[dict]:
    import urllib.request
    body = json.dumps(messages).encode()
    req = urllib.request.Request(
        f"{RESEND_API}/emails/batch",
        data=body,
        headers={
            **HEADERS_BASE,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
        # Resend batch returns {"data": [...]} or plain list
        return data.get("data", data) if isinstance(data, dict) else data


def check_verified_domain(api_key: str) -> bool:
    try:
        data = resend_get("/domains", api_key)
        domains = data.get("data", [])
        verified = [d for d in domains if d.get("status") == "verified"]
        if not verified:
            print("ERROR: No verified Resend domain found.")
            print("  Verify your domain at resend.com/domains before sending.")
            return False
        print(f"  Verified domain: {verified[0]['name']}")
        return True
    except Exception as e:
        # 403 = key lacks domain-list permission but may still send — proceed with warning
        print(f"  Domain check skipped ({e}) — proceeding (send will fail if domain unverified)")
        return True


def count_sent_today(all_campaign_dirs: list[Path]) -> int:
    today = date.today().isoformat()
    total = 0
    for campaign_dir in all_campaign_dirs:
        sent_log = campaign_dir / "sent-log.csv"
        if not sent_log.is_file():
            continue
        with open(sent_log, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("sent_at") or "").startswith(today):
                    total += 1
    return total


def build_name_lookup(campaign_dir: Path) -> dict[str, str]:
    """Return {email: name} from audience.csv + seeds."""
    lookup: dict[str, str] = {}
    # From audience.csv
    aud = campaign_dir / "audience.csv"
    if aud.is_file():
        with open(aud, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email = (row.get("email") or "").strip().lower()
                name = (row.get("name") or "").strip()
                if email:
                    lookup[email] = name
    # From seeds file
    seeds_file = SCRIPT_DIR.parent / "references" / "test-seeds.json"
    if seeds_file.is_file():
        import json as _json
        for s in _json.loads(seeds_file.read_text()).get("seeds", []):
            lookup[s["email"].lower()] = s["name"]
    return lookup


def personalise(text: str, email: str, name_lookup: dict[str, str], fallback: str = "there") -> str:
    """Replace [Name] with the recipient's name from the lookup."""
    name = name_lookup.get(email.lower(), "") or fallback
    return text.replace("[Name]", name)


def embed_images(html: str, campaign_dir: Path) -> str:
    """Replace relative src="filename" with Cloudinary CDN URLs (from image-urls.json)."""
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
    """Load subject, body_html, body_txt from campaign dir."""
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
                      test_emails: list[str] | None = None) -> int:
    slug = campaign_dir.name
    plan_file = campaign_dir / "send-plan.json"
    if not plan_file.is_file():
        return 0

    plan = json.loads(plan_file.read_text())

    if test_emails:
        today_batch = test_emails
    else:
        today_batch = plan.get("batches", {}).get(today_str, [])
        if not today_batch:
            return 0
        # Idempotency: skip emails already sent for this campaign on this date
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

    email_content = load_campaign_email(campaign_dir)
    if not email_content:
        print(f"  [{slug}] SKIP: missing subject.txt or body files")
        return 0

    name_lookup = build_name_lookup(campaign_dir)
    print(f"  [{slug}] {len(today_batch)} emails to send")

    if dry_run:
        for addr in today_batch:
            name = name_lookup.get(addr.lower(), "(no name)")
            print(f"  [{slug}] [dry-run] → {addr} as '{name}'")
        return 0

    # Build personalised messages
    messages = []
    for email_addr in today_batch:
        msg = {
            "from": f"{FROM_NAME} <{FROM_EMAIL}>",
            "to": [email_addr],
            "subject": personalise(email_content["subject"], email_addr, name_lookup),
            "text": personalise(email_content["text"], email_addr, name_lookup),
            "headers": {
                "X-Campaign": slug,
                "X-Batch-Date": today_str,
            },
        }
        if email_content["html"]:
            html = personalise(email_content["html"], email_addr, name_lookup)
            msg["html"] = embed_images(html, campaign_dir)
        messages.append(msg)

    # Send in chunks of 100
    sent_rows = []
    now_utc = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(messages), BATCH_CHUNK):
        chunk = messages[i : i + BATCH_CHUNK]
        try:
            results = resend_post_batch(chunk, api_key)
            if isinstance(results, list):
                for result, email_addr in zip(results, today_batch[i : i + BATCH_CHUNK]):
                    sent_rows.append({
                        "resend_id": result.get("id", ""),
                        "email": email_addr,
                        "campaign": slug,
                        "sent_at": now_utc,
                        "batch_date": today_str,
                    })
        except Exception as e:
            print(f"  [{slug}] ERROR sending chunk {i//BATCH_CHUNK + 1}: {e}")
            continue

    if not sent_rows:
        return 0

    # Append to sent-log.csv
    log_file = campaign_dir / "sent-log.csv"
    write_header = not log_file.is_file()
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["resend_id", "email", "campaign", "sent_at", "batch_date"])
        if write_header:
            writer.writeheader()
        writer.writerows(sent_rows)

    print(f"  [{slug}] Sent {len(sent_rows)} emails — logged to {log_file.name}")
    return len(sent_rows)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    args = parse_args()
    api_key = os.environ.get("RESEND_API_KEY", "")

    print("\n=== Bhookle Email Dispatch ===")
    today_str = date.today().isoformat()
    print(f"Date: {today_str}")

    # Env check
    if not api_key:
        print("ERROR: RESEND_API_KEY not set in .env or environment.")
        return 1

    print(f"\nChecking Resend domain...")
    if not check_verified_domain(api_key):
        return 1

    if args.check_env:
        print("\nEnvironment OK.")
        return 0

    # Find campaigns
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

    # Daily cap check
    already_sent = count_sent_today(campaign_dirs)
    planned_today = sum(
        len(json.loads((d / "send-plan.json").read_text()).get("batches", {}).get(today_str, []))
        for d in campaign_dirs
        if (d / "send-plan.json").is_file()
    )

    print(f"\nDaily quota: {already_sent} already sent today, {planned_today} planned")
    if already_sent + planned_today > DAILY_CAP:
        print(f"ERROR: {already_sent + planned_today} total would exceed daily cap of {DAILY_CAP}.")
        print("  Some campaigns will be skipped to stay within limit.")

    test_emails = [e.strip() for e in args.test.split(",")] if args.test else None
    if test_emails:
        print(f"\nTEST MODE — sending only to: {test_emails}")

    print(f"\nDispatching{' [DRY RUN]' if args.dry_run else ''}...")
    total_sent = 0
    remaining_cap = DAILY_CAP - already_sent

    for campaign_dir in sorted(campaign_dirs):
        plan_file = campaign_dir / "send-plan.json"
        if not plan_file.is_file():
            continue

        if not test_emails:
            plan = json.loads(plan_file.read_text())
            today_batch = plan.get("batches", {}).get(today_str, [])
            if not today_batch:
                continue
            if len(today_batch) > remaining_cap:
                print(f"  [{campaign_dir.name}] SKIP: {len(today_batch)} would exceed remaining cap ({remaining_cap})")
                continue

        sent = dispatch_campaign(campaign_dir, today_str, api_key, args.dry_run, test_emails)
        total_sent += sent
        remaining_cap -= sent

    print(f"\nTotal sent today: {total_sent}")

    # Send dispatch report only when this run actually sent new emails.
    # Prevents repeated report emails when idempotency guard skips re-sends.
    if not args.dry_run and not test_emails and total_sent > 0:
        send_dispatch_report(campaign_dirs, today_str, api_key)

    return 0


def send_dispatch_report(campaign_dirs: list[Path], today_str: str, api_key: str) -> None:
    """After dispatch, verify each Resend message and email a summary to the admin."""
    import time as _time
    admin = os.environ.get("EMAIL_ADMIN_RECIPIENT", "owner@example.com")

    print(f"\n=== Building dispatch report for {admin} ===")
    per_campaign: list[dict] = []
    total_delivered = total_failed = total_pending = 0

    for campaign_dir in sorted(campaign_dirs):
        log_file = campaign_dir / "sent-log.csv"
        if not log_file.is_file():
            continue
        # Pull today's sends for this campaign
        today_rows = []
        with open(log_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("batch_date") == today_str:
                    today_rows.append(row)
        if not today_rows:
            continue

        # Verify each via Resend (small sleep to avoid rate-limit)
        delivered = failed = pending = 0
        for row in today_rows:
            rid = row.get("resend_id", "")
            try:
                data = resend_get(f"/emails/{rid}", api_key)
                event = data.get("last_event", "sent")
                if event in ("delivered", "opened", "clicked"):
                    delivered += 1
                elif event in ("bounced", "complained"):
                    failed += 1
                else:
                    pending += 1
            except Exception:
                pending += 1
            _time.sleep(0.05)

        per_campaign.append({
            "slug": campaign_dir.name,
            "name": _read_campaign_name(campaign_dir),
            "sent": len(today_rows),
            "delivered": delivered,
            "failed": failed,
            "pending": pending,
        })
        total_delivered += delivered
        total_failed += failed
        total_pending += pending

    if not per_campaign:
        print("  No dispatched campaigns to report — skipping.")
        return

    # Build report HTML + text
    total_sent = sum(c["sent"] for c in per_campaign)
    subject = f"📬 Bhookle dispatch report — {today_str} ({total_sent} sent, {total_delivered} delivered)"

    rows_html = "".join(
        f"<tr>"
        f"<td style='padding:8px;border-bottom:1px solid #FFE0B2;'>{c['name']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #FFE0B2;text-align:center;'><b>{c['sent']}</b></td>"
        f"<td style='padding:8px;border-bottom:1px solid #FFE0B2;text-align:center;color:#2D7D2D;'>{c['delivered']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #FFE0B2;text-align:center;color:#888;'>{c['pending']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #FFE0B2;text-align:center;color:#C00;'>{c['failed']}</td>"
        f"</tr>"
        for c in per_campaign
    )
    html = (
        f"<div style='font-family:Arial,sans-serif;max-width:600px;background:#FFF8EC;padding:24px;'>"
        f"<h2 style='color:#3D0C11;margin:0 0 8px;'>📬 Bhookle dispatch report</h2>"
        f"<p style='color:#666;margin:0 0 20px;'>{today_str} · {total_sent} emails sent today</p>"
        f"<table style='width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;'>"
        f"<thead><tr style='background:#FF6B00;color:#fff;'>"
        f"<th style='padding:10px;text-align:left;'>Campaign</th>"
        f"<th style='padding:10px;'>Sent</th>"
        f"<th style='padding:10px;'>Delivered</th>"
        f"<th style='padding:10px;'>Pending</th>"
        f"<th style='padding:10px;'>Failed</th>"
        f"</tr></thead><tbody>{rows_html}"
        f"<tr style='background:#FFE0B2;font-weight:bold;'>"
        f"<td style='padding:8px;'>TOTAL</td>"
        f"<td style='padding:8px;text-align:center;'>{total_sent}</td>"
        f"<td style='padding:8px;text-align:center;color:#2D7D2D;'>{total_delivered}</td>"
        f"<td style='padding:8px;text-align:center;'>{total_pending}</td>"
        f"<td style='padding:8px;text-align:center;color:#C00;'>{total_failed}</td>"
        f"</tr></tbody></table>"
        f"<p style='color:#888;font-size:12px;margin-top:24px;'>Auto-sent by email-outreach skill · {today_str}</p>"
        f"</div>"
    )
    text_rows = "\n".join(
        f"  {c['name']}: sent={c['sent']} delivered={c['delivered']} pending={c['pending']} failed={c['failed']}"
        for c in per_campaign
    )
    text = (
        f"Bhookle dispatch report — {today_str}\n\n"
        f"{text_rows}\n\n"
        f"TOTAL: sent={total_sent} delivered={total_delivered} pending={total_pending} failed={total_failed}\n"
    )

    # Send via Gmail SMTP (no Resend quota impact)
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
        print(f"  Report sent to {admin} via Gmail SMTP (no Resend quota used)")
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
