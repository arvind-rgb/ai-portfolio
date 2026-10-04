#!/usr/bin/env python3
"""One-off FCM blast to a list of device tokens (selective segment push).

Unlike fcm_client.py (topic broadcast), this sends per-token via HTTP v1 —
used for targeted segments like reg-but-not-ordered. Supports --dry-run
(validate_only: exercises auth + message shape, delivers nothing) and --limit
for a canary send.

Usage:
  python3 send_tokens.py --file tokens.txt --title "..." --body "..." [--dry-run] [--limit 5]

Auth identical to fcm_client.py: FCM_SERVICE_ACCOUNT_JSON (raw JSON, GH secret)
or FCM_SERVICE_ACCOUNT_FILE (local path).
"""
import os, sys, json, argparse, time

import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request

PROJECT_ID = "<firebase-project-id>"
FCM_ENDPOINT = f"https://fcm.googleapis.com/v1/projects/{PROJECT_ID}/messages:send"
SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


def _load_credentials():
    raw = os.environ.get("FCM_SERVICE_ACCOUNT_JSON")
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = os.environ.get("FCM_SERVICE_ACCOUNT_FILE")
    if path and os.path.exists(path):
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    raise SystemExit("No FCM credentials (FCM_SERVICE_ACCOUNT_JSON or FCM_SERVICE_ACCOUNT_FILE).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="text file, one FCM token per line")
    ap.add_argument("--title", required=True)
    ap.add_argument("--body", default=" ")
    ap.add_argument("--dry-run", action="store_true", help="validate_only — delivers nothing")
    ap.add_argument("--limit", type=int, default=0, help="send to first N tokens only (canary)")
    a = ap.parse_args()

    tokens = [t.strip() for t in open(a.file) if t.strip()]
    if a.limit:
        tokens = tokens[: a.limit]
    print(f"tokens to process: {len(tokens)} | dry_run={a.dry_run}")

    creds = _load_credentials()
    creds.refresh(Request())
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json; UTF-8",
    })

    sent = invalid = errors = 0
    for i, tok in enumerate(tokens, 1):
        message = {
            "token": tok,
            "notification": {"title": a.title, "body": a.body or " "},
            "android": {"priority": "high", "notification": {"sound": "default"}},
            "apns": {"payload": {"aps": {"sound": "default"}}},
        }
        try:
            r = session.post(FCM_ENDPOINT,
                             data=json.dumps({"message": message, "validate_only": bool(a.dry_run)}),
                             timeout=30)
            if r.status_code == 200:
                sent += 1
            elif r.status_code in (400, 404) and "UNREGISTERED" in r.text or "registration-token" in r.text:
                invalid += 1
            else:
                errors += 1
                if errors <= 5:
                    print(f"  err {r.status_code}: {r.text[:120]}")
            # refresh auth token if long run
            if i % 500 == 0:
                creds.refresh(Request())
                session.headers["Authorization"] = f"Bearer {creds.token}"
                print(f"  progress {i}/{len(tokens)} (sent {sent}, invalid {invalid}, errors {errors})")
        except requests.RequestException as e:
            errors += 1
            if errors <= 5:
                print(f"  exception: {str(e)[:100]}")
            time.sleep(1)

    mode = "validated" if a.dry_run else "delivered"
    print(f"\nDONE — {mode}: {sent} | invalid/expired tokens: {invalid} | errors: {errors}")
    sys.exit(0 if errors < len(tokens) * 0.5 else 1)


if __name__ == "__main__":
    main()
