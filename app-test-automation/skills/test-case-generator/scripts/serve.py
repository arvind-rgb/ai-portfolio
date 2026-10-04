#!/usr/bin/env python3
"""
serve.py — tiny stdlib HTTP server for the test-catalog dashboard.

Routes:
  GET  /                 → dashboard.html
  GET  /catalog.json     → current catalog (single source of truth)
  POST /api/save         → overwrite catalog.json with request body
  POST /api/lock         → write .locked marker (called when all approved)
  POST /api/unlock       → remove .locked marker
  GET  /api/status       → { all_approved: bool, locked: bool, counts: {...} }

Usage:
  python3 serve.py [--port 7777] [--no-browser] [--catalog path/to/catalog.json]

Stdlib only — no Flask, no install.
"""
import argparse
import json
import os
import sys
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

# State dir is overridable so the dashboard can run against any catalog
# (e.g. the portfolio's sample-state/) via BHOOKLE_TEST_STATE or --catalog.
STATE_DIR = Path(os.environ.get("BHOOKLE_TEST_STATE", Path.home() / ".claude/skills/_bhookle-test-state"))
TC_DIR = STATE_DIR / "testcases"
CATALOG = TC_DIR / "catalog.json"
LOCK = TC_DIR / ".locked"
DASHBOARD = Path(__file__).parent.parent / "dashboard.html"

APPROVED_OK = {"Approved", "Skip-Until-Flag-On"}


def _read_catalog():
    if not CATALOG.exists():
        return None
    return json.loads(CATALOG.read_text())


def _write_catalog(obj):
    # Atomic-ish: write to .tmp then move
    tmp = CATALOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(CATALOG)


def _compute_status_summary(cat):
    tcs = cat.get("test_cases", [])
    by_status = Counter((t.get("status") or "Pending Review") for t in tcs)
    by_priority = Counter(t.get("priority", "?") for t in tcs)
    all_approved = len(tcs) > 0 and all(
        (t.get("status") or "Pending Review") in APPROVED_OK for t in tcs
    )
    return {
        "total": len(tcs),
        "by_status": dict(by_status),
        "by_priority": dict(by_priority),
        "all_approved": all_approved,
        "locked": LOCK.exists(),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Quieter logs
        sys.stderr.write(f"[serve] {fmt % args}\n")

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/dashboard.html"):
            if not DASHBOARD.exists():
                return self._send(500, {"error": f"dashboard missing at {DASHBOARD}"})
            return self._send(200, DASHBOARD.read_bytes(), ctype="text/html; charset=utf-8")
        if path == "/catalog.json":
            cat = _read_catalog()
            if cat is None:
                return self._send(404, {"error": "no catalog yet — run /test-case-generator"})
            return self._send(200, cat)
        if path == "/api/status":
            cat = _read_catalog() or {}
            return self._send(200, _compute_status_summary(cat))
        return self._send(404, {"error": "not found", "path": path})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            return self._send(400, {"error": f"bad json: {e}"})

        if path == "/api/save":
            # Expect full-catalog shape; merge into existing to preserve fields the UI doesn't show
            existing = _read_catalog() or {}
            existing["test_cases"] = data.get("test_cases", existing.get("test_cases", []))
            existing["meta"] = data.get("meta", existing.get("meta", {}))
            # Don't blow away run_results or bugs
            existing.setdefault("run_results", [])
            existing.setdefault("bugs", [])
            _write_catalog(existing)
            summary = _compute_status_summary(existing)
            return self._send(200, {"ok": True, "summary": summary})

        if path == "/api/lock":
            LOCK.write_text(json.dumps({
                "locked_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "locked_by": "dashboard",
            }, indent=2))
            return self._send(200, {"ok": True, "locked": True})

        if path == "/api/unlock":
            if LOCK.exists():
                LOCK.unlink()
            return self._send(200, {"ok": True, "locked": False})

        return self._send(404, {"error": "not found", "path": path})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--catalog", help="path to a catalog.json (overrides the state dir)")
    args = ap.parse_args()

    global CATALOG, LOCK
    if args.catalog:
        CATALOG = Path(args.catalog).expanduser().resolve()
        LOCK = CATALOG.parent / ".locked"

    if not CATALOG.exists():
        print(f"❌ No catalog at {CATALOG}. Run /test-case-generator first.", file=sys.stderr)
        sys.exit(2)
    if not DASHBOARD.exists():
        print(f"❌ Dashboard not found at {DASHBOARD}.", file=sys.stderr)
        sys.exit(2)

    url = f"http://localhost:{args.port}/"
    print(f"📋 Test-case dashboard: {url}")
    print(f"   Catalog: {CATALOG}")
    print(f"   Lock file: {LOCK} ({'present' if LOCK.exists() else 'not yet'})")
    print(f"   Stop with Ctrl-C.")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    srv = HTTPServer(("127.0.0.1", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] stopped.")


if __name__ == "__main__":
    main()
