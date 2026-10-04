#!/usr/bin/env python3
"""List pending Reel posts from the social planner. Static vs Reel aware.

Usage:
  list_pending.py CALENDAR.xlsx [--json] [--check-models]
"""
import sys, json, argparse, os
import requests
import openpyxl

API_KEY = os.environ.get("GEMINI_API_KEY", "")
DEFAULT_MODELS = ["imagen-4.0-ultra-generate-001",
                  "gemini-3.1-flash-image-preview",
                  "veo-3.1-fast-generate-preview"]


def check_models():
    r = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}", timeout=15)
    live = {m["name"].split("/")[-1] for m in r.json().get("models", [])}
    ok = True
    for m in DEFAULT_MODELS:
        present = m in live
        ok = ok and present
        print(f"  {'OK ' if present else 'MISSING'}  {m}")
    return ok


def is_reel(row):
    """A row is a Reel if AssetType says so, else fall back to PostFormat == Reel."""
    at = (row.get("AssetType") or "").lower()
    if at:
        return "reel" in at or "video" in at
    return (row.get("PostFormat") or "").strip().lower() == "reel"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("calendar")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check-models", action="store_true")
    ap.add_argument("--sheet", default="Instagram_Facebook")
    a = ap.parse_args()

    if a.check_models:
        print("Model availability:")
        sys.exit(0 if check_models() else 1)

    wb = openpyxl.load_workbook(a.calendar, read_only=True)
    ws = wb[a.sheet]
    rows = list(ws.iter_rows(values_only=True))
    hdr = {h: i for i, h in enumerate(rows[0])}
    def g(r, k): return r[hdr[k]] if k in hdr else None

    pending = []
    for r in rows[1:]:
        rec = {k: g(r, k) for k in hdr}
        if not is_reel(rec):
            continue
        status = (rec.get("PostStatus") or "").strip().lower()
        if status == "creative locked":
            continue
        pending.append({
            "PostID": rec.get("PostID"),
            "PostName": rec.get("PostName"),
            "PostFormat": rec.get("PostFormat"),
            "ContentCategory": rec.get("ContentCategory"),
            "PostGenPrompt": rec.get("PostGenPrompt"),
            "ExistingAssetLink": rec.get("ExistingAssetLink"),
            "AssetAction": rec.get("AssetAction"),
        })

    if a.json:
        print(json.dumps(pending, indent=2, default=str))
    else:
        for p in pending:
            print(f"{p['PostID']}\t{p['PostName']}")
        print(f"\n{len(pending)} pending reel(s).")


if __name__ == "__main__":
    main()
