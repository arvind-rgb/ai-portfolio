#!/usr/bin/env python3
"""Manually arm a week's notifications (yet_to_schedule -> scheduled) + email confirmation.

Approval happens in chat at generation time; this is the canonical CLI to flip a
pre-generated week to armed. Email confirmation is best-effort (needs GMAIL_* env).

Usage: approve_week.py 2026-W27
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_lib as cal_lib  # noqa: E402
from mail_lib import send_email  # noqa: E402


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("usage: approve_week.py <ISO-week e.g. 2026-W27>", file=sys.stderr)
        sys.exit(2)
    week = sys.argv[1].strip()

    cal = cal_lib.load()
    dates = {e["date"] for e in cal["entries"] if cal_lib.iso_week(e["date"]) == week}
    if not dates:
        print(f"No entries found for {week}; nothing to arm.", file=sys.stderr)
        sys.exit(1)

    n = cal_lib.set_status_for_dates(cal, dates, cal_lib.STATUS_SCHEDULED)
    cal_lib.save(cal)
    print(f"Armed {n} entries for {week}.")

    rows = "".join(
        f"<tr><td>{e['date']} {e['day']}</td><td>{e['slot']}</td>"
        f"<td>{e['send_ist']}</td><td>{e['title']}</td></tr>"
        for e in cal["entries"]
        if e["date"] in dates
    )
    html = f"""
    <div style="font-family:system-ui,Arial,sans-serif;color:#341C3D">
      <h2>✅ Notifications are set up — {week}</h2>
      <p>This week's lunch &amp; dinner nudges are armed and will fire automatically
         (lunch 11:45, dinner 18:45 IST) to all app users.</p>
      <table cellpadding="8" style="border-collapse:collapse;font-size:14px">
        <tr style="background:#FFA70B;color:#341C3D"><th>Day</th><th>Slot</th><th>IST</th><th>Message</th></tr>
        {rows}
      </table>
    </div>"""
    try:
        send_email(f"✅ Bhookle notifications set up — {week}", html)
    except Exception as exc:  # don't fail the arm if email hiccups
        print(f"(warning) confirmation email failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
