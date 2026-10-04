#!/usr/bin/env python3
"""Monday 07:00 IST — email an FYI of the upcoming 7 days of notifications.

Window: the 7 days starting on the run date (Mon..Sun). Pure heads-up — weeks are
pre-generated and armed in chat, so this just shows what will go out. Reply to the
email to request changes before the first nudge.
"""
import os
import sys
import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_lib as cal_lib  # noqa: E402
from mail_lib import send_email  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")


def main():
    fake = os.environ.get("NOTIF_FAKE_NOW")
    now = IST.localize(datetime.datetime.fromisoformat(fake)) if fake else datetime.datetime.now(IST)
    start = now.date()
    window = {(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}

    cal = cal_lib.load()
    entries = sorted(
        (e for e in cal["entries"] if e["date"] in window),
        key=lambda e: (e["date"], e["send_ist"]),
    )
    if not entries:
        print("No entries in the upcoming 7-day window; skipping preview email.")
        return

    week = cal_lib.iso_week(min(e["date"] for e in entries))
    badge = {"scheduled": "🟢 armed", "posted": "✅ sent", "yet_to_schedule": "🟡 not armed"}
    rows = "".join(
        f"<tr><td>{e['date']} {e['day']}</td><td>{'🍲' if e['slot']=='lunch' else '🌙'} {e['slot']}</td>"
        f"<td>{e['send_ist']}</td><td>{e['title']}</td>"
        f"<td>{badge.get(e['status'], e['status'])}</td></tr>"
        for e in entries
    )

    html = f"""
    <div style="font-family:system-ui,Arial,sans-serif;color:#341C3D;max-width:640px">
      <h2>🍲 Bhookle notifications — week {week}</h2>
      <p>Here are this week's lunch &amp; dinner nudges going out to all app users
         (lunch 11:45, dinner 18:45 IST).</p>
      <p style="color:#555">🟢 = armed and will send. Reply to this email with any changes
         before the first nudge.</p>
      <table cellpadding="8" style="border-collapse:collapse;font-size:14px;border:1px solid #eee">
        <tr style="background:#341C3D;color:#fff">
          <th>Day</th><th>Slot</th><th>IST</th><th>Message</th><th>Status</th></tr>
        {rows}
      </table>
      <p style="color:#777;font-size:12px;margin-top:16px">Bhookle Bot · Amma in a Dabba</p>
    </div>"""

    send_email(f"🍲 Bhookle notifications — week {week}", html)


if __name__ == "__main__":
    main()
