#!/usr/bin/env python3
"""FCM HTTP v1 client for Bhookle push notifications.

Auth via a Firebase service-account JSON. Source, in priority order:
  1. env FCM_SERVICE_ACCOUNT_JSON  (raw JSON string — used in GitHub Actions)
  2. env FCM_SERVICE_ACCOUNT_FILE  (path to a .json key — used for local tests)

Sends a title-only notification to an FCM topic. Body defaults to a single
space because FCM rejects an empty body string. Supports dry_run (validate_only)
which exercises auth + message validation WITHOUT delivering anything.

Project: <firebase-project-id>   Default topic: all (every app device subscribes in App.tsx)
"""
import os
import sys
import json
import argparse

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

PROJECT_ID = "<firebase-project-id>"
FCM_ENDPOINT = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


def _load_credentials():
    raw = os.environ.get("FCM_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    path = os.environ.get("FCM_SERVICE_ACCOUNT_FILE")
    if path and os.path.exists(path):
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise SystemExit(
        "No FCM credentials. Set FCM_SERVICE_ACCOUNT_JSON (raw JSON) "
        "or FCM_SERVICE_ACCOUNT_FILE (path to key.json)."
    )


def _access_token(creds):
    creds.refresh(Request())
    return creds.token


def send_topic(title, body=" ", topic="all", dry_run=False, data=None):
    """Send a title-only notification to a topic. Returns (ok, status_code, text)."""
    creds = _load_credentials()
    token = _access_token(creds)

    message = {
        "topic": topic,
        "notification": {"title": title, "body": body if body else " "},
        "android": {"priority": "high", "notification": {"sound": "default"}},
        "apns": {"payload": {"aps": {"sound": "default"}}},
    }
    if data:
        message["data"] = {k: str(v) for k, v in data.items()}

    payload = {"message": message, "validate_only": bool(dry_run)}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; UTF-8",
    }
    resp = requests.post(FCM_ENDPOINT, headers=headers, data=json.dumps(payload), timeout=30)
    return resp.status_code == 200, resp.status_code, resp.text


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Send an FCM topic notification.")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default=" ")
    ap.add_argument("--topic", default="all")
    ap.add_argument("--dry-run", action="store_true", help="validate_only — delivers nothing")
    a = ap.parse_args()
    ok, code, text = send_topic(a.title, a.body, a.topic, a.dry_run)
    tag = "OK" if ok else "FAIL"
    print(f"[{tag}] {code} {text}")
    sys.exit(0 if ok else 1)
