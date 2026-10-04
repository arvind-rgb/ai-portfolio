#!/usr/bin/env python3
"""
Lemlist API helpers — shared by all lemlist-ops scripts.

Auth: HTTP Basic with empty username + LEMLIST_API_KEY as password
      → Authorization: Basic base64(":<key>")

Env required:
  LEMLIST_API_KEY — get from Lemlist Settings → API Keys
"""
import os
import sys
import base64
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[3]

# Load .env if running locally (GH Actions injects env directly)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

API_KEY = os.environ.get("LEMLIST_API_KEY")
BASE_URL = "https://api.lemlist.com/api"

if not API_KEY:
    sys.exit("❌ LEMLIST_API_KEY must be set in .env or GH secrets")

AUTH_HEADER = "Basic " + base64.b64encode(f":{API_KEY}".encode()).decode()
HEADERS = {"Authorization": AUTH_HEADER, "Content-Type": "application/json"}


def get(path: str, **params):
    """GET /api/{path} → returns parsed JSON or raises."""
    r = requests.get(f"{BASE_URL}/{path.lstrip('/')}", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def post(path: str, body=None):
    """POST /api/{path} with JSON body → returns parsed JSON or raises."""
    r = requests.post(
        f"{BASE_URL}/{path.lstrip('/')}",
        headers=HEADERS,
        data=json.dumps(body) if body is not None else None,
        timeout=30,
    )
    if r.status_code >= 400:
        # Don't raise for "already running" — caller decides
        try:
            return {"_error": r.json(), "_status": r.status_code}
        except Exception:
            return {"_error": r.text, "_status": r.status_code}
    if r.text.strip():
        return r.json()
    return {"ok": True}


# ── Convenience wrappers ────────────────────────────────────────────────

def list_campaigns():
    """All campaigns in team."""
    return get("campaigns")


def get_campaign(campaign_id: str):
    return get(f"campaigns/{campaign_id}")


def get_campaign_leads(campaign_id: str, limit: int = 200, state: str = None):
    params = {"limit": limit}
    if state:
        params["state"] = state
    return get(f"campaigns/{campaign_id}/leads", **params)


def get_campaign_stats(campaign_id: str, start_date: str, end_date: str):
    """v2 endpoint — richer metrics."""
    r = requests.get(
        f"{BASE_URL}/v2/campaigns/{campaign_id}/stats",
        headers=HEADERS,
        params={"startDate": start_date, "endDate": end_date},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_campaign_statutes(campaign_id: str):
    return get(f"campaigns/{campaign_id}/statutes")


def search_people(filters: list, page: int = 1, size: int = 100):
    """Search people database with filters."""
    return post("database/people", {"filters": filters, "page": page, "size": size})


def get_contact(contact_id: str):
    return get(f"contacts/{contact_id}")


def create_lead(campaign_id: str, lead: dict):
    """Add a lead to a campaign. Email required."""
    return post(f"campaigns/{campaign_id}/leads/", lead)


def launch_lead(lead_id: str):
    """Move lead from 'scanned' → 'reviewed' (queued for sending)."""
    return post(f"leads/review/{lead_id}")


def start_campaign(campaign_id: str):
    return post(f"campaigns/{campaign_id}/start")


def pause_campaign(campaign_id: str):
    return post(f"campaigns/{campaign_id}/pause")
