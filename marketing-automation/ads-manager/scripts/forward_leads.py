#!/usr/bin/env python3
"""
Instant Form lead alerting for ops@example.com.

Two-tier, runs every ~30 min via GitHub Actions (kids-lead-forward.yml):

  Tier 1 (full details): read leads via /{form_id}/leads and email each lead's
  name/phone. Requires leads_retrieval on META_ADS_TOKEN — currently NOT granted
  (Meta app can't request it without review). Attempted every run so the moment
  the permission lands, alerts silently upgrade to full detail.

  Tier 2 (count alert, active today): read the campaign's lead COUNT from the
  Insights API (needs only ads_read). When the count increases, email ops
  "N new lead(s)" with a Leads Center link. No PII available at this tier.

State lives in AdManager/leads_state.json (committed back by the workflow).
"""

import json, os, smtplib, ssl, sys
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
PAGE_ID = "<FB_PAGE_ID>"
FORM_IDS = [f.strip() for f in os.environ.get("LEAD_FORM_IDS", "<LEAD_FORM_ID>").split(",")]
CAMPAIGN_IDS = [c.strip() for c in os.environ.get("LEAD_CAMPAIGN_IDS", "<CAMPAIGN_ID>").split(",")]
RECIPIENT = os.environ.get("LEADS_RECIPIENT", "ops@example.com")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
BASE = "https://graph.facebook.com/v21.0"
LEADS_CENTER_URL = f"https://business.facebook.com/latest/leads_center?asset_id={PAGE_ID}"

ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = ROOT / "AdManager" / "leads_state.json"

if not TOKEN:
    sys.exit("❌ META_ADS_TOKEN not set")


def send_email(subject, html):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("⚠️ Gmail creds missing — cannot send; printing instead:", subject)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Bhookle Leads <{GMAIL_USER}>"
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, [RECIPIENT], msg.as_string())


# ── Tier 1: full lead details (requires leads_retrieval) ────────────────────
def try_full_details(state):
    try:
        r = requests.get(f"{BASE}/me/accounts",
                         params={"fields": "id,access_token", "access_token": TOKEN}, timeout=60)
        pt = next(p["access_token"] for p in r.json().get("data", []) if p["id"] == PAGE_ID)
    except (StopIteration, requests.RequestException):
        return False, 0

    seen = set(state.get("seen_lead_ids", []))
    new_count = 0
    for form_id in FORM_IDS:
        url = f"{BASE}/{form_id}/leads"
        params = {"fields": "id,created_time,field_data,ad_name", "limit": 100, "access_token": pt}
        while url:
            j = requests.get(url, params=params, timeout=60).json()
            if "error" in j:
                return False, 0        # permission still missing → Tier 2
            for lead in j.get("data", []):
                if lead["id"] in seen:
                    continue
                fields = {f["name"]: ", ".join(f.get("values", [])) for f in lead.get("field_data", [])}
                name = fields.get("full_name", "—")
                phone = fields.get("phone", fields.get("phone_number", "—"))
                rows = "".join(f"<tr><td style='padding:6px 12px;color:#6E4F7A'>{k}</td>"
                               f"<td style='padding:6px 12px;font-weight:bold'>{v}</td></tr>"
                               for k, v in fields.items())
                send_email(
                    f"🎒 New Bhookle Kids lead: {name} ({phone})",
                    f"<div style='font-family:sans-serif;max-width:520px'>"
                    f"<h2 style='color:#2D1B3D'>New Bhookle Kids trial lead</h2>"
                    f"<table style='border-collapse:collapse;background:#FFF8EC'>{rows}</table>"
                    f"<p><b>Call within the hour</b> — conversion drops fast after that.</p>"
                    f"<p style='color:#6E4F7A;font-size:12px'>Submitted {lead.get('created_time','')}"
                    f" via \"{lead.get('ad_name','—')}\".</p></div>")
                seen.add(lead["id"])
                new_count += 1
            url = j.get("paging", {}).get("next")
            params = {}
    state["seen_lead_ids"] = sorted(seen)[-5000:]
    return True, new_count


# ── Tier 2: count-based alert via Insights (ads_read only) ──────────────────
LEAD_ACTION_TYPES = ("leadgen_grouped", "lead", "onsite_conversion.lead_grouped")

def count_leads(campaign_id):
    r = requests.get(f"{BASE}/{campaign_id}/insights",
                     params={"fields": "actions", "date_preset": "maximum",
                             "access_token": TOKEN}, timeout=60)
    j = r.json()
    if "error" in j:
        print(f"⚠️ insights error on {campaign_id}: {j['error'].get('message','')[:120]}")
        return 0
    actions = ((j.get("data") or [{}])[0]).get("actions") or []
    by_type = {a.get("action_type"): int(float(a.get("value", 0))) for a in actions}
    for t in LEAD_ACTION_TYPES:
        if t in by_type:
            return by_type[t]
    return 0


def tier2_count_alert(state):
    counts = state.setdefault("campaign_lead_counts", {})
    total_new = 0
    for cid in CAMPAIGN_IDS:
        current = count_leads(cid)
        previous = counts.get(cid, 0)
        if current > previous:
            total_new += current - previous
        counts[cid] = max(current, previous)
    if total_new > 0:
        plural = "s" if total_new > 1 else ""
        send_email(
            f"🎒 {total_new} new Bhookle Kids lead{plural} — call now",
            f"<div style='font-family:sans-serif;max-width:520px'>"
            f"<h2 style='color:#2D1B3D'>{total_new} new lead{plural} on the Kids Instant Form</h2>"
            f"<p>Name and phone number are in Leads Center:</p>"
            f"<p><a href='{LEADS_CENTER_URL}' style='background:#FFA70B;color:#2D1B3D;"
            f"padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold'>"
            f"Open Leads Center</a></p>"
            f"<p><b>Call within the hour</b> — conversion drops fast after that.</p>"
            f"<p style='color:#6E4F7A;font-size:12px'>Checked every ~30 min. This alert has "
            f"the count only; lead details live in Leads Center (or Meta Business Suite app).</p></div>")
    return total_new


def main():
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            state = {}

    full_ok, forwarded = try_full_details(state)
    if full_ok:
        mode, n = "full_details", forwarded
    else:
        mode, n = "count_alert", tier2_count_alert(state)

    state["last_checked_utc"] = datetime.now(timezone.utc).isoformat()
    state["mode"] = mode
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    print(f"mode={mode} new_leads={n}")


if __name__ == "__main__":
    main()
