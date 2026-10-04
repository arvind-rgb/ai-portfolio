#!/usr/bin/env python3
"""
Meta prepaid wallet watchdog.

Checks the ad account's available prepaid balance and emails an alert when it
falls below the threshold (default ₹1,000). Designed to run every 6h via
GitHub Actions (.github/workflows/meta-wallet-check.yml).

Alert rules:
  - balance >= threshold  → no email; reset alert state
  - balance <  threshold  → email on the transition, then re-remind at most
    once every 24h while it stays low (so you aren't spammed 4x/day)

State lives in AdManager/wallet_state.json (committed back by the workflow).
"""

import json, os, re, smtplib, ssl, sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
except ImportError:
    pass

TOKEN = os.environ.get("META_ADS_TOKEN")
ACCOUNT = os.environ.get("META_AD_ACCOUNT_ID", "<AD_ACCOUNT_ID>")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT = os.environ.get("ADS_REPORT_RECIPIENT", "owner@example.com")
THRESHOLD = float(os.environ.get("WALLET_ALERT_THRESHOLD_INR", "1000"))
REMIND_HOURS = 24

ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "AdManager" / "wallet_state.json"

if not TOKEN:
    sys.exit("❌ META_ADS_TOKEN not set")


def get_balance_inr():
    """Prepaid available balance in INR. Parses funding_source_details display
    string; falls back to (spend_cap - amount_spent)."""
    r = requests.get(
        f"https://graph.facebook.com/v21.0/act_{ACCOUNT}",
        params={"fields": "funding_source_details,spend_cap,amount_spent,is_prepay_account",
                "access_token": TOKEN},
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    disp = (d.get("funding_source_details") or {}).get("display_string", "")
    m = re.search(r"([\d,]+(?:\.\d+)?)", disp.replace(" ", " "))
    if m:
        return float(m.group(1).replace(",", "")), disp
    cap, spent = float(d.get("spend_cap") or 0), float(d.get("amount_spent") or 0)
    if cap:
        return (cap - spent) / 100.0, "derived from spend_cap - amount_spent"
    sys.exit(f"❌ Could not determine balance from: {json.dumps(d)[:300]}")


def send_alert(balance):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        sys.exit("❌ GMAIL_USER / GMAIL_APP_PASSWORD not set — cannot send alert")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚠️ Meta Ads wallet low: ₹{balance:,.0f} left (threshold ₹{THRESHOLD:,.0f})"
    msg["From"] = f"Bhookle AdsManager <{GMAIL_USER}>"
    msg["To"] = RECIPIENT
    html = f"""
    <div style="font-family:sans-serif;max-width:520px">
      <h2 style="color:#2D1B3D">Meta Ads prepaid balance is low</h2>
      <p style="font-size:28px;font-weight:bold;color:#E51A4B">₹{balance:,.2f} remaining</p>
      <p>Alert threshold: ₹{THRESHOLD:,.0f}. Active campaigns currently spend around
      ₹1,000/day — ads will stop when the wallet hits zero.</p>
      <p><a href="https://business.facebook.com/billing_hub/accounts?asset_id={ACCOUNT}"
      style="background:#FFA70B;color:#2D1B3D;padding:12px 20px;border-radius:8px;
      text-decoration:none;font-weight:bold">Top up wallet</a></p>
      <p style="color:#6E4F7A;font-size:12px">Sent by the wallet watchdog
      (meta-wallet-check workflow, runs every 6h).</p>
    </div>"""
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, [RECIPIENT], msg.as_string())


def main():
    balance, source = get_balance_inr()
    now = datetime.now(timezone.utc)
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            state = {}

    low = balance < THRESHOLD
    alerted_at = state.get("last_alert_utc")
    hours_since = None
    if alerted_at:
        try:
            hours_since = (now - datetime.fromisoformat(alerted_at)).total_seconds() / 3600
        except ValueError:
            hours_since = None

    action = "none"
    if low and (not state.get("below_threshold") or hours_since is None or hours_since >= REMIND_HOURS):
        send_alert(balance)
        state["last_alert_utc"] = now.isoformat()
        action = "alert_sent"
    state["below_threshold"] = low
    state["last_balance_inr"] = round(balance, 2)
    state["last_checked_utc"] = now.isoformat()
    state["balance_source"] = source

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    print(f"balance=₹{balance:,.2f} threshold=₹{THRESHOLD:,.0f} low={low} action={action}")


if __name__ == "__main__":
    main()
