#!/usr/bin/env python3
"""Runway watchdog — emails a warning if the notification calendar is running low
or if TODAY has no armed notifications. Runs daily in GitHub Actions, so it is
app-independent (catches gaps even if nobody opens the Claude app).

Warn when: days-of-runway < RUNWAY_THRESHOLD (default 5), OR today is not fully armed.
"""
import os
import sys
import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_lib as cal_lib  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")
THRESHOLD = int(os.environ.get("RUNWAY_THRESHOLD", "5"))


def main():
    cal = cal_lib.load()
    today = datetime.datetime.now(IST).date()
    today_str = today.isoformat()

    armed_dates = sorted(
        {e["date"] for e in cal["entries"]
         if e["status"] in (cal_lib.STATUS_SCHEDULED, cal_lib.STATUS_POSTED)}
    )
    last = datetime.date.fromisoformat(armed_dates[-1]) if armed_dates else today
    runway = (last - today).days
    today_slots = sum(
        1 for e in cal["entries"]
        if e["date"] == today_str and e["status"] in (cal_lib.STATUS_SCHEDULED, cal_lib.STATUS_POSTED)
    )

    print(f"runway: last_armed={last} days_left={runway} today_slots={today_slots}/2")

    today_gap = today_slots < 2
    low = runway < THRESHOLD
    if not (low or today_gap):
        print("runway OK — no alert")
        return

    reasons = []
    if today_gap:
        reasons.append(f"<b>TODAY ({today_str}) has only {today_slots}/2 notifications armed — a gap!</b>")
    if low:
        reasons.append(f"Only <b>{runway} days</b> of runway left (armed through {last}).")

    html = f"""
    <div style="font-family:system-ui,Arial,sans-serif;color:#341C3D">
      <h2>⚠️ Bhookle notifications need topping up</h2>
      <ul>{''.join(f'<li>{r}</li>' for r in reasons)}</ul>
      <p>Ask Claude to <i>run the bhookle-notify skill</i> and generate the next week(s),
         or reply to trigger it. Lunch 11:45 / dinner 18:45 IST won't fire on unarmed days.</p>
    </div>"""
    try:
        from mail_lib import send_email
        send_email(f"⚠️ Bhookle notifications runway low ({runway}d left)", html)
        print("alert email sent")
    except Exception as exc:  # noqa: BLE001
        print(f"alert email failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
