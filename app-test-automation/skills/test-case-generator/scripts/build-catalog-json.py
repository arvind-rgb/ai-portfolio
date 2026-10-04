#!/usr/bin/env python3
"""
build-catalog-json.py — write the test catalog as JSON (single source of truth).

Usage:
  cat tcs.json | python3 build-catalog-json.py [--preserve-runs]

Input (stdin): JSON object with shape:
  { "meta": {...}, "test_cases": [ {tc fields...} ] }

Output: writes ~/.claude/skills/_bhookle-test-state/testcases/catalog.json

The output JSON is consumed by:
  - dashboard.html (read + edit + POST back to /api/save)
  - serve.py (read on startup, write on /api/save)
  - read-decisions.py (read for refinement workflow)
  - run-auto-test (skill #3 — read approved TCs)

--preserve-runs: keep existing run_results + bugs arrays from prior file.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

STATE_DIR = Path.home() / ".claude/skills/_bhookle-test-state"
CATALOG = STATE_DIR / "testcases" / "catalog.json"


def main():
    payload = json.load(sys.stdin)
    preserve = "--preserve-runs" in sys.argv

    CATALOG.parent.mkdir(parents=True, exist_ok=True)

    # Default per-TC fields the dashboard expects
    defaults = {
        "status": "Pending Review",
        "comments": "",
        "last_run_result": "",
        "last_run_ts": "",
        "failure_reason": "",
        "screenshot_path": "",
    }
    for tc in payload["test_cases"]:
        # status falls back to default_status from generator, else "Pending Review"
        tc.setdefault("status", tc.get("default_status", "Pending Review"))
        for k, v in defaults.items():
            tc.setdefault(k, v)

    out = {
        "meta": payload.get("meta", {}),
        "test_cases": payload["test_cases"],
        "run_results": [],
        "bugs": [],
        "schema_version": 1,
        "written_at": datetime.now().isoformat(timespec="seconds"),
    }

    if preserve and CATALOG.exists():
        try:
            old = json.load(open(CATALOG))
            out["run_results"] = old.get("run_results", [])
            out["bugs"] = old.get("bugs", [])
            # Preserve user-edited status + comments across regeneration
            old_by_id = {t["tc_id"]: t for t in old.get("test_cases", [])}
            for tc in out["test_cases"]:
                prev = old_by_id.get(tc["tc_id"])
                if prev:
                    for k in ("status", "comments"):
                        if prev.get(k):
                            tc[k] = prev[k]
        except Exception as e:
            print(f"(warn) failed to preserve prior catalog: {e}", file=sys.stderr)

    CATALOG.write_text(json.dumps(out, indent=2))
    print(str(CATALOG))
    print(f"Wrote {len(out['test_cases'])} test cases.")


if __name__ == "__main__":
    main()
