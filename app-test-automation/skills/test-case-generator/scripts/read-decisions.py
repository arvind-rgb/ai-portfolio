#!/usr/bin/env python3
"""
read-decisions.py — extract user decisions from catalog.json.

Usage:
  python3 read-decisions.py [--all] > decisions.json

Default: emit only TCs whose Status is Rejected or Needs Refinement.
--all: emit every TC with its current Status + Comments.

Output JSON shape:
  {
    "total_rows": N,
    "by_status": {"Approved": .., "Rejected": .., ...},
    "decisions": [ {tc fields...}, ... ],
    "all_approved": bool,
    "catalog_path": "..."
  }
"""
import json
import sys
from pathlib import Path
from collections import Counter

CATALOG = Path.home() / ".claude/skills/_bhookle-test-state/testcases/catalog.json"

NEEDS_REFINEMENT = {"Rejected", "Needs Refinement"}
APPROVED_OR_SKIP = {"Approved", "Skip-Until-Flag-On"}


def main():
    if not CATALOG.exists():
        print(json.dumps({"error": f"No catalog at {CATALOG}. Run /test-case-generator first."}), file=sys.stderr)
        sys.exit(2)

    cat = json.loads(CATALOG.read_text())
    tcs = cat.get("test_cases", [])

    emit_all = "--all" in sys.argv
    status_counts = Counter()
    rows = []

    for tc in tcs:
        status = (tc.get("status") or "Pending Review").strip()
        status_counts[status] += 1
        if emit_all or status in NEEDS_REFINEMENT:
            rows.append(tc)

    statuses = dict(status_counts)
    total = sum(statuses.values())
    actionable = sum(c for s, c in statuses.items() if s in NEEDS_REFINEMENT)
    all_approved = total > 0 and all(s in APPROVED_OR_SKIP for s in statuses.keys())

    out = {
        "total_rows": total,
        "by_status": statuses,
        "actionable_count": actionable,
        "all_approved": all_approved,
        "catalog_path": str(CATALOG),
        "decisions": rows,
    }
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
