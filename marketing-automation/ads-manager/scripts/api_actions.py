#!/usr/bin/env python3
"""
AdsManager — Marketing API Action Library
-----------------------------------------
Functions wrapping the Meta Marketing API for write operations.
Used by the skill (and walkthroughs) to actually execute action items.

All functions raise RuntimeError on API failure with the user-facing message.

Functions:
  pause_ad(ad_id)                                  pause an ad
  pause_campaign(campaign_id)                      pause a campaign
  pause_adset(adset_id)                            pause an ad set
  activate_ad(ad_id) / activate_campaign(...) / activate_adset(...)
  set_adset_budget(adset_id, daily_inr)            set ad-set daily budget (₹)
  set_campaign_budget(campaign_id, daily_inr)      set campaign daily budget (₹)
  set_adset_optimization_goal(adset_id, goal)      e.g. OFFSITE_CONVERSIONS, APP_INSTALLS
  reallocate_budget(from_adset_id, to_adset_id, amount_inr)
  create_campaign(name, objective, daily_inr)      basic skeleton
  create_adset(...)                                use Ads Manager for first-time setup

Run directly to test:
  python3 api_actions.py pause_ad <AD_ID>
"""

import os, sys, json, requests
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

TOKEN = os.environ["META_ADS_TOKEN"]
ACCOUNT = os.environ["META_AD_ACCOUNT_ID"]
API_BASE = "https://graph.facebook.com/v21.0"


def _post(path, data):
    data = {**data, "access_token": TOKEN}
    r = requests.post(f"{API_BASE}/{path}", data=data, timeout=30)
    j = r.json()
    if r.status_code != 200 or "error" in j:
        raise RuntimeError(f"API error: {j.get('error', {}).get('message', r.text)}")
    return j


def _get(path, params):
    params = {**params, "access_token": TOKEN}
    r = requests.get(f"{API_BASE}/{path}", params=params, timeout=30)
    j = r.json()
    if r.status_code != 200 or "error" in j:
        raise RuntimeError(f"API error: {j.get('error', {}).get('message', r.text)}")
    return j


# ── Status changes ──────────────────────────────────────────────────────────
def pause_ad(ad_id):       return _post(ad_id, {"status": "PAUSED"})
def pause_campaign(cid):   return _post(cid,   {"status": "PAUSED"})
def pause_adset(aid):      return _post(aid,   {"status": "PAUSED"})
def activate_ad(ad_id):    return _post(ad_id, {"status": "ACTIVE"})
def activate_campaign(cid):return _post(cid,   {"status": "ACTIVE"})
def activate_adset(aid):   return _post(aid,   {"status": "ACTIVE"})


# ── Budget changes ──────────────────────────────────────────────────────────
def set_adset_budget(adset_id, daily_inr):
    """daily_inr is in rupees (₹). Stored on Meta as paise (×100)."""
    paise = int(round(float(daily_inr) * 100))
    return _post(adset_id, {"daily_budget": paise})


def set_campaign_budget(campaign_id, daily_inr):
    paise = int(round(float(daily_inr) * 100))
    return _post(campaign_id, {"daily_budget": paise})


# ── Targeting / optimization ────────────────────────────────────────────────
def set_adset_optimization_goal(adset_id, goal):
    """
    goal: APP_INSTALLS | OFFSITE_CONVERSIONS | LINK_CLICKS | LANDING_PAGE_VIEWS |
          IMPRESSIONS | REACH | POST_ENGAGEMENT | VALUE | LEAD_GENERATION
    """
    return _post(adset_id, {"optimization_goal": goal})


# ── Composite actions ───────────────────────────────────────────────────────
def reallocate_budget(from_adset_id, to_adset_id, amount_inr):
    """
    Subtract `amount_inr` from the source ad set's daily budget and add it to the target.
    Returns dict {from: {old, new}, to: {old, new}}.
    """
    src = _get(from_adset_id, {"fields": "daily_budget,name"})
    tgt = _get(to_adset_id,   {"fields": "daily_budget,name"})
    src_old = int(src.get("daily_budget") or 0) / 100
    tgt_old = int(tgt.get("daily_budget") or 0) / 100
    if src_old < amount_inr:
        raise RuntimeError(f"Source ad set only has ₹{src_old:.0f}/day — can't move ₹{amount_inr:.0f}")
    src_new = src_old - amount_inr
    tgt_new = tgt_old + amount_inr
    set_adset_budget(from_adset_id, src_new)
    set_adset_budget(to_adset_id,   tgt_new)
    return {
        "from": {"id": from_adset_id, "name": src.get("name"), "old": src_old, "new": src_new},
        "to":   {"id": to_adset_id,   "name": tgt.get("name"), "old": tgt_old, "new": tgt_new},
    }


# ── Create operations (skeletons) ───────────────────────────────────────────
def create_campaign(name, objective, daily_inr=None):
    """
    objective: OUTCOME_APP_PROMOTION | OUTCOME_SALES | OUTCOME_LEADS |
               OUTCOME_AWARENESS | OUTCOME_TRAFFIC | OUTCOME_ENGAGEMENT
    Returns campaign id. Note: Ad sets + ads still need to be created separately;
    Meta requires creative + targeting setup that's best done in Ads Manager
    for first-time campaigns.
    """
    data = {
        "name": name,
        "objective": objective,
        "status": "PAUSED",                  # safe default
        "special_ad_categories": "[]",
    }
    if daily_inr:
        data["daily_budget"] = int(round(daily_inr * 100))
    return _post(f"act_{ACCOUNT}/campaigns", data)


# ── Reflection helper ───────────────────────────────────────────────────────
def get_entity(entity_id, fields="name,status,effective_status,daily_budget,lifetime_budget,optimization_goal"):
    return _get(entity_id, {"fields": fields})


# ── CLI for ad-hoc test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: api_actions.py <function> <args...>\n"
                 "  e.g. api_actions.py pause_ad <AD_ID>")
    fn_name, *args = sys.argv[1:]
    fn = globals().get(fn_name)
    if not callable(fn):
        sys.exit(f"Unknown function: {fn_name}")
    try:
        out = fn(*args)
        print(json.dumps(out, indent=2))
    except Exception as e:
        sys.exit(f"❌ {e}")
