#!/usr/bin/env python3
"""Read/write helpers for the Bhookle notification calendar.

The calendar (notifications/notification-calendar.json) is the single source of
truth. Status lifecycle per entry:  yet_to_schedule -> scheduled -> posted
  - yet_to_schedule : draft, not armed (e.g. a future week awaiting approval)
  - scheduled       : approved & armed; the tick will fire it at its send time
  - posted          : already sent to FCM
"""
import os
import json
import datetime

import pytz

IST = pytz.timezone("Asia/Kolkata")

STATUS_DRAFT = "yet_to_schedule"
STATUS_SCHEDULED = "scheduled"
STATUS_POSTED = "posted"


def calendar_path():
    return os.environ.get("NOTIF_CALENDAR_PATH", "notifications/notification-calendar.json")


def load():
    with open(calendar_path(), encoding="utf-8") as f:
        return json.load(f)


def save(cal):
    cal.setdefault("meta", {})["updated"] = datetime.datetime.now(IST).strftime("%Y-%m-%d")
    with open(calendar_path(), "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)
        f.write("\n")


def iso_week(date_str):
    y, m, d = map(int, date_str.split("-"))
    iso = datetime.date(y, m, d).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def set_status_for_dates(cal, dates, status):
    """Flip status for all entries whose date is in `dates`. Returns count changed."""
    n = 0
    for e in cal["entries"]:
        if e["date"] in dates and e["status"] != status:
            e["status"] = status
            n += 1
    return n
