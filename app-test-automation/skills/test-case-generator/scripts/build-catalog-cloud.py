#!/usr/bin/env python3
"""
build-catalog-cloud.py — push a freshly-generated TC batch up to the hosted
                        Bhookle QA catalog (qa.test_catalog in Postgres).

Replaces build-catalog-json.py. Same stdin contract; instead of writing
~/.claude/skills/_bhookle-test-state/testcases/catalog.json, this POSTs each
TC to ${QA_API_BASE}/api/tcs (upserting via PUT for existing tc_ids).

stdin JSON shape (unchanged):
  { "meta": {...}, "test_cases": [ {tc fields...} ] }

Env required:
  QA_API_BASE   — e.g. https://<region>-<your-project>.cloudfunctions.net/bhookleQaBackend
  QA_CLI_TOKEN  — shared secret matching the BE's QA_CLI_TOKEN

Notes:
- run_results + bugs are preserved server-side automatically (they live in
  separate qa.* tables and this script never touches them).
- The legacy --preserve-runs flag is accepted and ignored (no-op).
- This script is called by the test-case-generator skill at the end of
  Phase 5 (or by the `refine` flow). See SKILL.md.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"[build-catalog-cloud] missing env: {name}")
    return v


def req(method, url, body=None, token=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("X-CLI-Token", token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, body


def main():
    payload = json.load(sys.stdin)
    api = env("QA_API_BASE").rstrip("/")
    tok = env("QA_CLI_TOKEN")

    tcs = payload.get("test_cases") or []
    if not tcs:
        sys.exit("[build-catalog-cloud] stdin has no test_cases")

    # Fetch existing TC ids to decide PUT vs POST.
    code, body = req("GET", f"{api}/api/catalog", token=tok)
    if code != 200:
        sys.exit(f"[build-catalog-cloud] GET /catalog failed {code}: {body}")
    existing = {t["tc_id"] for t in (body.get("test_cases") or [])}

    created = updated = skipped = 0
    for t in tcs:
        tid = t.get("tc_id")
        if not tid:
            skipped += 1
            continue
        if tid in existing:
            # Partial update — only push fields the BE accepts (all TC fields).
            code, b = req("PUT", f"{api}/api/tcs/{tid}", body=t, token=tok)
            if code == 200:
                updated += 1
            else:
                print(f"[build-catalog-cloud] PUT {tid} → {code} {b}", file=sys.stderr)
                skipped += 1
        else:
            # New TC — POST. BE re-assigns tc_id from screen prefix, so we
            # cannot use generator-supplied ids on first insert. The
            # generator's ids are authoritative for stable references, so
            # we PUT with the requested id by going through a specific path:
            # try POST then patch the resulting id back. For now: error out
            # if the generator produced an id the BE doesn't already have —
            # the generator's full-catalog dump is meant for `migrate-from-json`
            # not for incremental adds.
            print(
                f"[build-catalog-cloud] {tid} not in BE; use migrate-from-json for bulk seeding "
                "or add manually via the dashboard.",
                file=sys.stderr,
            )
            skipped += 1

    print(json.dumps({
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "api_base": api,
    }, indent=2))


if __name__ == "__main__":
    main()
