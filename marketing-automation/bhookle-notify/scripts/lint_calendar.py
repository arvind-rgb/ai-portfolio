#!/usr/bin/env python3
"""Guard rails for the notification calendar. Run after generating any new week.

Fails (exit 1) if:
  - a title is repeated anywhere in the calendar (no duplicate messages, ever)
  - a title exceeds 26 chars (would truncate on phones)
  - body is empty (FCM rejects empty body)
  - status is not one of the allowed values
  - a (date, slot) pair appears twice
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_lib as cal_lib  # noqa: E402

ALLOWED = {cal_lib.STATUS_DRAFT, cal_lib.STATUS_SCHEDULED, cal_lib.STATUS_POSTED}
MAX_LEN = 26


def main():
    cal = cal_lib.load()
    errors = []
    seen_titles = {}
    seen_slots = set()

    for e in cal["entries"]:
        t = e["title"]
        key = t.strip().lower()
        if key in seen_titles:
            errors.append(f"DUPLICATE title {t!r} on {e['date']} {e['slot']} (also {seen_titles[key]})")
        else:
            seen_titles[key] = f"{e['date']} {e['slot']}"
        if len(t) > MAX_LEN:
            errors.append(f"TOO LONG ({len(t)}>{MAX_LEN}) {t!r} on {e['date']} {e['slot']}")
        if not e.get("body"):
            errors.append(f"EMPTY body on {e['date']} {e['slot']} (FCM rejects empty)")
        if e["status"] not in ALLOWED:
            errors.append(f"BAD status {e['status']!r} on {e['date']} {e['slot']}")
        ds = (e["date"], e["slot"])
        if ds in seen_slots:
            errors.append(f"DUPLICATE slot {ds}")
        seen_slots.add(ds)

    if errors:
        print("CALENDAR LINT FAILED:")
        for er in errors:
            print(f"  ✗ {er}")
        sys.exit(1)
    print(f"CALENDAR LINT OK — {len(cal['entries'])} entries, {len(seen_titles)} unique titles, all <= {MAX_LEN} chars")


if __name__ == "__main__":
    main()
