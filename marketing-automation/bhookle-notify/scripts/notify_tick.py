#!/usr/bin/env python3
"""Bhookle notification tick — send any due notifications, then mark them posted.

Idempotent: only fires entries that are status=scheduled, dated today (IST), and
whose send time has passed. On success the entry flips to posted, so a retry run
(or a duplicate trigger) no-ops. Safe to run many times a day.

Flags:
  --dry-run   validate_only (FCM delivers nothing); does NOT mark posted
  --force     ignore the time gate (still requires status=scheduled, date=today)
"""
import os
import sys
import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_lib as cal_lib  # noqa: E402
from fcm_client import send_topic  # noqa: E402

IST = pytz.timezone("Asia/Kolkata")


def main():
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    # Credential self-test: prove FCM auth works on this runner without delivering.
    if "--selftest" in sys.argv:
        ok, code, text = send_topic("selftest", " ", "bhookle_notif_pipetest", dry_run=True)
        print(f"[SELFTEST {'OK' if ok else 'FAIL'}] FCM auth — {code}")
        sys.exit(0 if ok else 1)

    # NOTIF_FAKE_NOW (ISO "YYYY-MM-DDTHH:MM") lets us test the matcher without waiting.
    fake = os.environ.get("NOTIF_FAKE_NOW")
    if fake:
        now = IST.localize(datetime.datetime.fromisoformat(fake))
    else:
        now = datetime.datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    cal = cal_lib.load()
    topic = cal.get("meta", {}).get("topic", "all")

    sent, failed, changed = [], [], False

    for e in cal["entries"]:
        if e["status"] != cal_lib.STATUS_SCHEDULED:
            continue
        if e["date"] != today:
            continue
        hh, mm = map(int, e["send_ist"].split(":"))
        due = (now.hour, now.minute) >= (hh, mm)
        if not (due or force):
            continue

        ok, code, text = send_topic(e["title"], e.get("body", " "), topic, dry_run=dry)
        if ok:
            sent.append(e)
            if not dry:
                e["status"] = cal_lib.STATUS_POSTED
                e["posted_at"] = now.isoformat()
                changed = True
            print(f"[SENT{' DRY' if dry else ''}] {e['date']} {e['slot']:6} :: {e['title']}")
        else:
            failed.append(e)
            print(f"[FAIL] {e['date']} {e['slot']} :: {code} {text}", file=sys.stderr)

    if changed:
        cal_lib.save(cal)

    print(f"Summary: sent={len(sent)} failed={len(failed)} dry={dry} now={now:%Y-%m-%d %H:%M} IST")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
