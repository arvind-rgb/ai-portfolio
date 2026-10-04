#!/usr/bin/env python3
"""
read-decisions-cloud.py — read user review decisions from the hosted QA
                        catalog (qa.test_catalog).

Replaces read-decisions.py. Same stdout contract:
  {
    "total_rows": N,
    "by_status": {"Approved": .., "Rejected": .., ...},
    "decisions": [ {tc fields...}, ... ],
    "all_approved": bool,
    "catalog_path": "<API_BASE>"
  }

Default: only TCs whose Status is Rejected or Needs Refinement.
--all: every TC with current Status + Comments.

Env required:
  QA_API_BASE   — hosted BE URL
  QA_CLI_TOKEN  — shared secret matching the BE
"""
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter


NEEDS_REFINEMENT = {"Rejected", "Needs Refinement"}
APPROVED_OR_SKIP = {"Approved", "Skip-Until-Flag-On"}


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"[read-decisions-cloud] missing env: {name}")
    return v


def main():
    api = env("QA_API_BASE").rstrip("/")
    tok = env("QA_CLI_TOKEN")
    emit_all = "--all" in sys.argv

    r = urllib.request.Request(f"{api}/api/catalog", method="GET")
    r.add_header("X-CLI-Token", tok)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            cat = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"[read-decisions-cloud] GET /catalog failed {e.code}: {e.read().decode('utf-8','replace')}")

    tcs = cat.get("test_cases") or []
    counts = Counter(t.get("status") or "Pending Review" for t in tcs)
    if emit_all:
        decisions = tcs
    else:
        decisions = [t for t in tcs if (t.get("status") or "") in NEEDS_REFINEMENT]

    unapproved = sum(1 for t in tcs if (t.get("status") or "") not in APPROVED_OR_SKIP)
    out = {
        "total_rows": len(tcs),
        "by_status": dict(counts),
        "decisions": decisions,
        "all_approved": len(tcs) > 0 and unapproved == 0,
        "catalog_path": api,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
