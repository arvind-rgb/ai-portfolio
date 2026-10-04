#!/usr/bin/env python3
"""
AdsManager — Email Dispatcher
-----------------------------
Sends the latest AdsManager PDF to owner@example.com via Gmail SMTP.

Env required (already in your repo's GH Actions secrets):
  GMAIL_USER          — sender Gmail address (e.g. team@example.com)
  GMAIL_APP_PASSWORD  — 16-char Gmail App Password (Account → Security → App passwords)

Usage:
  python3 send_email.py                       # latest PDF in AdManager/Output
  python3 send_email.py path/to/file.pdf      # specific PDF
"""

import os, sys, json, smtplib, ssl
from pathlib import Path
from datetime import datetime
from email.message import EmailMessage
from dotenv import load_dotenv

ROOT    = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "AdManager" / "Output"
load_dotenv(ROOT / ".env")

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT  = os.environ.get("ADS_REPORT_RECIPIENT", "owner@example.com")

if not GMAIL_USER or not GMAIL_PASS:
    sys.exit("❌ GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env or GH secrets")


def find_latest_pdf():
    pdfs = sorted(OUT_DIR.glob("Bhookle-AdsReport-*.pdf"))
    if not pdfs:
        sys.exit(f"❌ No PDFs found in {OUT_DIR}")
    return pdfs[-1]


def html_body(summary):
    return f"""\
<html><body style="font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color:#1A1A1A; background:#FFF8EC; padding:24px;">
  <div style="max-width:560px; margin:0 auto; background:#FFFFFF; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    <div style="background:#FFA70B; padding:18px 24px;">
      <div style="color:#2D1B3D; font-weight:700; font-size:20px; letter-spacing:-0.01em;">Bhookle · Ads Intelligence</div>
    </div>
    <div style="padding:24px;">
      <h2 style="color:#2D1B3D; margin:0 0 12px; font-size:22px;">Weekly Ads Report — {summary.get('run_date','')}</h2>
      <p style="margin:0 0 16px; color:#6E4F7A;">90-day account analysis with action items.</p>

      <table style="width:100%; border-collapse:collapse; margin:16px 0;">
        <tr>
          <td style="padding:10px; background:#FFF8EC; border-radius:8px; width:50%;">
            <div style="font-size:11px; color:#6E4F7A;">SPEND (30d)</div>
            <div style="font-size:20px; font-weight:700; color:#2D1B3D;">₹{summary.get('spend_30d',0):,.0f}</div>
          </td>
          <td style="width:8px;"></td>
          <td style="padding:10px; background:#FFF8EC; border-radius:8px; width:50%;">
            <div style="font-size:11px; color:#6E4F7A;">INSTALLS (30d)</div>
            <div style="font-size:20px; font-weight:700; color:#2D1B3D;">{summary.get('installs_30d',0):,}</div>
          </td>
        </tr>
        <tr><td colspan="3" style="height:8px;"></td></tr>
        <tr>
          <td style="padding:10px; background:#FFF8EC; border-radius:8px;">
            <div style="font-size:11px; color:#6E4F7A;">BLENDED CPI (30d)</div>
            <div style="font-size:20px; font-weight:700; color:#2D1B3D;">₹{(summary.get('blended_cpi_30d') or 0):.2f}</div>
          </td>
          <td style="width:8px;"></td>
          <td style="padding:10px; background:#FFF8EC; border-radius:8px;">
            <div style="font-size:11px; color:#6E4F7A;">HEALTH SCORE</div>
            <div style="font-size:20px; font-weight:700; color:#2D1B3D;">{summary.get('health_score',0)}/100</div>
          </td>
        </tr>
      </table>

      <div style="padding:14px 16px; background:#FFE9C2; border-left:4px solid #FFA70B; border-radius:6px; margin:18px 0;">
        <div style="font-weight:700; color:#2D1B3D; margin-bottom:4px;">
          {summary.get('action_items_total',0)} action items
          ({summary.get('action_items_high',0)} HIGH priority)
        </div>
        <div style="color:#6E4F7A; font-size:13px;">
          Open the attached PDF for full details. In Claude Code, run
          <code style="background:#FFF; padding:2px 6px; border-radius:4px;">/show-ad-research</code>
          to walk through each item.
        </div>
      </div>

      <p style="color:#6E4F7A; font-size:13px; margin:18px 0 0;">
        — Bhookle AdsManager · auto-generated
      </p>
    </div>
  </div>
</body></html>
"""


def send(pdf_path):
    pdf_path = Path(pdf_path)
    summary = {}
    latest_json = OUT_DIR / "latest.json"
    if latest_json.exists():
        summary = json.loads(latest_json.read_text()).get("summary", {})

    msg = EmailMessage()
    msg["Subject"] = f"Bhookle · Weekly Ads Report · {summary.get('run_date', datetime.now().strftime('%Y-%m-%d'))}"
    msg["From"] = GMAIL_USER
    msg["To"]   = RECIPIENT
    msg.set_content(
        f"Your Bhookle Ads Intelligence Report for {summary.get('run_date','today')} is attached.\n\n"
        f"  Spend (30d):  ₹{summary.get('spend_30d', 0):,.0f}\n"
        f"  Installs (30d): {summary.get('installs_30d', 0):,}\n"
        f"  Blended CPI:  ₹{(summary.get('blended_cpi_30d') or 0):.2f}\n"
        f"  Health score: {summary.get('health_score', 0)}/100\n"
        f"  Action items: {summary.get('action_items_total', 0)} ({summary.get('action_items_high', 0)} HIGH)\n\n"
        "Open the PDF for full details. In Claude Code, run /show-ad-research to walk through each item.\n\n"
        "— Bhookle AdsManager"
    )
    msg.add_alternative(html_body(summary), subtype="html")

    with open(pdf_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application", subtype="pdf",
            filename=pdf_path.name
        )

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.send_message(msg)
    print(f"✅ Sent {pdf_path.name} to {RECIPIENT}")


if __name__ == "__main__":
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_pdf()
    send(pdf)
