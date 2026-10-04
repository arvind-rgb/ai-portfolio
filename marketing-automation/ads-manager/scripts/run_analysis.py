#!/usr/bin/env python3
"""
AdsManager — Meta Ads Analysis Engine
-------------------------------------
Pulls 90-day campaign / ad-set / ad / creative data from Meta Marketing API,
runs expert-marketer analysis across 6 dimensions, generates action items,
and produces a JSON payload that build_report.py turns into a branded PDF.

Usage
  python3 run_analysis.py                 # full run (JSON + PDF)
  python3 run_analysis.py --json-only     # JSON only, skip PDF
  python3 run_analysis.py --debug         # verbose API logging
"""

import os, sys, json, argparse, subprocess
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ────────────────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

TOKEN   = os.environ.get("META_ADS_TOKEN")
ACCOUNT = os.environ.get("META_AD_ACCOUNT_ID")
if not TOKEN or not ACCOUNT:
    sys.exit("❌ META_ADS_TOKEN and META_AD_ACCOUNT_ID must be set in .env")

BASE     = f"https://graph.facebook.com/v21.0/act_{ACCOUNT}"
TODAY    = datetime.now().strftime("%Y-%m-%d")
STAMP    = datetime.now().strftime("%Y%m%d")
OUT_DIR  = ROOT / "AdManager" / "Output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEBUG = False
def log(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


# ────────────────────────────────────────────────────────────────────────────
# Meta API helpers
# ────────────────────────────────────────────────────────────────────────────
def get(url, params):
    params["access_token"] = TOKEN
    log(f"GET {url}")
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        log(f"  ↳ {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    return r.json()


def fetch_all(url, params):
    """Paginated GET, returns flattened list."""
    out, cursor = [], None
    while True:
        if cursor:
            params["after"] = cursor
        data = get(url, params)
        out.extend(data.get("data", []))
        cursor = data.get("paging", {}).get("cursors", {}).get("after")
        if not cursor or not data.get("paging", {}).get("next"):
            break
    return out


def _num(d, key):
    """Safe float coerce; returns None if missing/'Not available'."""
    v = d.get(key) if isinstance(d, dict) else None
    if v is None or v == "Not available":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _action_value(insights, action_type):
    for a in insights.get("actions", []) or []:
        if a.get("action_type") == action_type:
            try:
                return int(float(a["value"]))
            except (ValueError, TypeError):
                pass
    return 0


def _cost_per_action(insights, action_type):
    for a in insights.get("cost_per_action_type", []) or []:
        if a.get("action_type") == action_type:
            try:
                return float(a["value"])
            except (ValueError, TypeError):
                pass
    return None


def _video_pct(insights, percentile_key):
    v = insights.get(percentile_key, [])
    if v and isinstance(v, list):
        try:
            return int(float(v[0].get("value", 0)))
        except (ValueError, TypeError):
            pass
    return 0


# ────────────────────────────────────────────────────────────────────────────
# Data pull
# ────────────────────────────────────────────────────────────────────────────
def pull_campaigns():
    fields = "id,name,status,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time,buying_type,bid_strategy,configured_status"
    return fetch_all(f"{BASE}/campaigns", {"fields": fields, "limit": 100})


def pull_insights(level, date_preset, extra_fields=""):
    base_fields = "campaign_id,campaign_name,adset_id,ad_id,spend,impressions,clicks,ctr,cpc,cpm,reach,frequency,actions,cost_per_action_type"
    if level == "ad":
        base_fields += ",video_p25_watched_actions,video_p50_watched_actions,video_p75_watched_actions,video_p100_watched_actions"
    if extra_fields:
        base_fields += "," + extra_fields
    return fetch_all(f"{BASE}/insights", {
        "level": level,
        "fields": base_fields,
        "date_preset": date_preset,
        "limit": 250,
    })


def pull_adsets(campaign_ids):
    out = []
    for cid in campaign_ids:
        adsets = fetch_all(f"https://graph.facebook.com/v21.0/{cid}/adsets", {
            "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,bid_strategy,optimization_goal,targeting,start_time,end_time,billing_event",
            "limit": 50
        })
        for a in adsets:
            a["campaign_id"] = cid
        out.extend(adsets)
    return out


def pull_ads(campaign_ids):
    if not campaign_ids:
        return []
    return fetch_all(f"{BASE}/ads", {
        "fields": "id,name,status,effective_status,campaign_id,adset_id,created_time,creative{id,name,body,title,call_to_action_type,thumbnail_url,object_story_spec}",
        "filtering": json.dumps([{"field": "campaign.id", "operator": "IN", "value": campaign_ids}]),
        "limit": 250,
    })


# ────────────────────────────────────────────────────────────────────────────
# Analysis modules
# ────────────────────────────────────────────────────────────────────────────
def analyse_campaigns(campaigns, insights_by_window, non_install_campaigns=None):
    """Per-campaign 90/30/7d metrics + fatigue flags + commentary.
    non_install_campaigns: campaign ids whose active ad sets optimize for
    something other than APP_INSTALLS — their CPI is not a valid yardstick."""
    non_install_campaigns = non_install_campaigns or set()
    out = []
    for c in campaigns:
        cid = c["id"]
        i90 = insights_by_window["90d"].get(cid, {})
        i30 = insights_by_window["30d"].get(cid, {})
        i7  = insights_by_window["7d"].get(cid, {})

        spend_90 = _num(i90, "spend") or 0
        spend_30 = _num(i30, "spend") or 0
        spend_7  = _num(i7,  "spend") or 0
        installs_90 = _action_value(i90, "omni_app_install")
        installs_30 = _action_value(i30, "omni_app_install")
        installs_7  = _action_value(i7,  "omni_app_install")
        cpi_90 = _cost_per_action(i90, "omni_app_install")
        cpi_30 = _cost_per_action(i30, "omni_app_install")
        cpi_7  = _cost_per_action(i7,  "omni_app_install")
        ctr_90 = _num(i90, "ctr")
        ctr_30 = _num(i30, "ctr")
        ctr_7  = _num(i7,  "ctr")
        freq_30 = _num(i30, "frequency")
        reach_30 = _num(i30, "reach")

        ctr_decay = None
        if ctr_30 and ctr_7:
            ctr_decay = round((ctr_7 - ctr_30) / ctr_30 * 100, 1)
        cpi_spike = None
        if cpi_30 and cpi_7:
            cpi_spike = round((cpi_7 - cpi_30) / cpi_30 * 100, 1)

        # Commentary: rule-based expert reading
        notes = []
        if cid in non_install_campaigns:
            notes.append("ℹ️ This campaign does NOT optimize for installs — judge it on its own "
                         "optimization event (e.g., checkouts) and frequency, never on CPI. "
                         "Install-CPI comparisons against acquisition campaigns are invalid.")
        elif c["effective_status"] == "ACTIVE" and cpi_30:
            if cpi_30 < 5:
                notes.append(f"Strong unit economics at ₹{cpi_30:.2f} CPI — well below the ₹5 efficient-CAC threshold for India app installs.")
            elif cpi_30 < 15:
                notes.append(f"Acceptable CPI of ₹{cpi_30:.2f} but above the ₹5 efficiency benchmark — room to optimize.")
            else:
                notes.append(f"High CPI of ₹{cpi_30:.2f} indicates audience-creative mismatch or saturation.")
        if cpi_spike is not None and cpi_spike > 25:
            notes.append(f"⚠️ CPI has spiked {cpi_spike}% in the last 7 days vs the 30-day baseline — fatigue or auction-pressure signal.")
        if ctr_decay is not None and ctr_decay < -15:
            notes.append(f"⚠️ CTR has dropped {abs(ctr_decay)}% week-over-week — creative is losing audience interest.")
        if freq_30 and freq_30 > 2.5:
            notes.append(f"⚠️ Frequency at {freq_30:.1f} — same users seeing ads 2.5x+ per month. Expand audience or pause.")
        if "retarg" in c["name"].lower() and c.get("objective") in ("OUTCOME_APP_PROMOTION", "APP_INSTALLS"):
            notes.append("🔍 Retargeting campaign optimized for app installs — likely mis-configured (audience has already installed). Consider switching to first-order or app-event optimization.")

        out.append({
            "id": cid,
            "name": c["name"],
            "status": c["effective_status"],
            "objective": c.get("objective"),
            "buying_type": c.get("buying_type"),
            "bid_strategy": c.get("bid_strategy"),
            "daily_budget_inr": round(int(c.get("daily_budget") or 0) / 100, 2),
            "lifetime_budget_inr": round(int(c.get("lifetime_budget") or 0) / 100, 2),
            "start_time": c.get("start_time"),
            # 90-day window
            "spend_90d": round(spend_90, 2),
            "installs_90d": installs_90,
            "cpi_90d": round(cpi_90, 2) if cpi_90 else None,
            "ctr_90d": round(ctr_90, 2) if ctr_90 else None,
            # 30-day window
            "spend_30d": round(spend_30, 2),
            "installs_30d": installs_30,
            "cpi_30d": round(cpi_30, 2) if cpi_30 else None,
            "ctr_30d": round(ctr_30, 2) if ctr_30 else None,
            "freq_30d": round(freq_30, 2) if freq_30 else None,
            "reach_30d": int(reach_30) if reach_30 else None,
            # 7-day window
            "spend_7d": round(spend_7, 2),
            "installs_7d": installs_7,
            "cpi_7d": round(cpi_7, 2) if cpi_7 else None,
            "ctr_7d": round(ctr_7, 2) if ctr_7 else None,
            # Trend signals
            "ctr_decay_pct": ctr_decay,
            "cpi_spike_pct": cpi_spike,
            "commentary": notes,
        })
    return out


def analyse_creatives(ads, ad_insights_by_window):
    out = []
    for ad in ads:
        aid = ad["id"]
        i90 = ad_insights_by_window["90d"].get(aid, {})
        i30 = ad_insights_by_window["30d"].get(aid, {})
        i7  = ad_insights_by_window["7d"].get(aid, {})

        spend_90 = _num(i90, "spend") or 0
        spend_30 = _num(i30, "spend") or 0
        spend_7  = _num(i7,  "spend") or 0
        installs_30 = _action_value(i30, "omni_app_install")
        installs_7  = _action_value(i7,  "omni_app_install")
        cpi_90 = _cost_per_action(i90, "omni_app_install")
        cpi_30 = _cost_per_action(i30, "omni_app_install")
        cpi_7  = _cost_per_action(i7,  "omni_app_install")
        ctr_30 = _num(i30, "ctr")
        ctr_7  = _num(i7,  "ctr")
        freq_30 = _num(i30, "frequency")
        impr_30 = _num(i30, "impressions") or 0

        # Video completion funnel (30d)
        p25  = _video_pct(i30, "video_p25_watched_actions")
        p50  = _video_pct(i30, "video_p50_watched_actions")
        p75  = _video_pct(i30, "video_p75_watched_actions")
        p100 = _video_pct(i30, "video_p100_watched_actions")
        total_views = _action_value(i30, "video_view")
        hold_rate = round(p100 / total_views * 100, 1) if total_views else None

        ctr_decay = None
        if ctr_30 and ctr_7:
            ctr_decay = round((ctr_7 - ctr_30) / ctr_30 * 100, 1)
        cpi_spike = None
        if cpi_30 and cpi_7:
            cpi_spike = round((cpi_7 - cpi_30) / cpi_30 * 100, 1)

        # Creative age in days
        age_days = None
        if ad.get("created_time"):
            try:
                created = datetime.strptime(ad["created_time"][:10], "%Y-%m-%d")
                age_days = (datetime.now() - created).days
            except ValueError:
                pass

        # Fatigue scoring
        score = 0
        if ctr_decay is not None and ctr_decay < -20: score += 3
        elif ctr_decay is not None and ctr_decay < -10: score += 2
        elif ctr_decay is not None and ctr_decay < -5: score += 1
        if cpi_spike is not None and cpi_spike > 50: score += 3
        elif cpi_spike is not None and cpi_spike > 25: score += 2
        elif cpi_spike is not None and cpi_spike > 10: score += 1
        if freq_30 and freq_30 > 3: score += 2
        elif freq_30 and freq_30 > 2.5: score += 1
        if age_days and age_days > 180: score += 1
        if hold_rate is not None and hold_rate < 5: score += 1

        fatigue_level = "HIGH" if score >= 5 else "MEDIUM" if score >= 3 else "LOW" if score >= 1 else "NONE"

        creative = ad.get("creative", {}) or {}
        out.append({
            "ad_id": aid,
            "ad_name": ad.get("name"),
            "campaign_id": ad.get("campaign_id"),
            "adset_id": ad.get("adset_id"),
            "status": ad.get("effective_status"),
            "created_time": ad.get("created_time"),
            "creative_age_days": age_days,
            "creative_id": creative.get("id"),
            "creative_body": (creative.get("body") or "")[:240],
            "creative_cta": creative.get("call_to_action_type"),
            "thumbnail_url": creative.get("thumbnail_url"),
            "spend_90d": round(spend_90, 2),
            "spend_30d": round(spend_30, 2),
            "spend_7d": round(spend_7, 2),
            "installs_30d": installs_30,
            "installs_7d": installs_7,
            "impressions_30d": int(impr_30) if impr_30 else 0,
            "cpi_90d": round(cpi_90, 2) if cpi_90 else None,
            "cpi_30d": round(cpi_30, 2) if cpi_30 else None,
            "cpi_7d": round(cpi_7, 2) if cpi_7 else None,
            "ctr_30d": round(ctr_30, 2) if ctr_30 else None,
            "ctr_7d": round(ctr_7, 2) if ctr_7 else None,
            "freq_30d": round(freq_30, 2) if freq_30 else None,
            "ctr_decay_pct": ctr_decay,
            "cpi_spike_pct": cpi_spike,
            "video_p25": p25, "video_p50": p50, "video_p75": p75, "video_p100": p100,
            "video_hold_rate_pct": hold_rate,
            "fatigue_score": score,
            "fatigue_level": fatigue_level,
        })
    return out


NEW_CREATIVE_WINDOW_DAYS = 28
LEARNING_INSTALL_THRESHOLD = 50   # Meta's learning phase exits around ~50 conversions

def new_creative_watch(creatives_a):
    """Launch-cohort tracker: every ad created in the last NEW_CREATIVE_WINDOW_DAYS
    days, benchmarked against incumbent ads in the same ad set. Verdicts respect
    the learning phase — a new creative is never judged on CPI before it has
    enough installs to be readable."""
    cohort = [c for c in creatives_a
              if c.get("creative_age_days") is not None
              and c["creative_age_days"] <= NEW_CREATIVE_WINDOW_DAYS]
    if not cohort:
        return []

    incumbents = [c for c in creatives_a
                  if (c.get("creative_age_days") or 0) > NEW_CREATIVE_WINDOW_DAYS
                  and c["status"] == "ACTIVE" and c.get("cpi_30d")]

    def bench_for(adset_id):
        pool = sorted(c["cpi_30d"] for c in incumbents if c["adset_id"] == adset_id) \
               or sorted(c["cpi_30d"] for c in incumbents)
        return pool[len(pool) // 2] if pool else None

    out = []
    for c in sorted(cohort, key=lambda x: -(x.get("spend_30d") or 0)):
        benchmark = bench_for(c["adset_id"])
        spend    = c.get("spend_30d") or 0
        installs = c.get("installs_30d") or 0
        cpi      = c.get("cpi_30d")
        in_learning = installs < LEARNING_INSTALL_THRESHOLD

        if c["status"] != "ACTIVE" and spend < 50:
            verdict, note = "NOT_DELIVERING", f"Status {c['status']} with almost no spend — check review/delivery status."
        elif spend < 50:
            verdict, note = "TOO_EARLY", "Barely any spend yet — no read possible. Check again next report."
        elif installs == 0 and spend > 300:
            verdict, note = "NO_TRACTION", (
                f"₹{spend:.0f} spent with zero attributed installs. Verify tracking first; "
                "if installs are genuinely zero, this is a pause candidate.")
        elif in_learning:
            if benchmark and cpi and cpi <= benchmark * 1.1:
                verdict, note = "PROMISING", (
                    f"CPI ₹{cpi:.2f} already at/below the incumbent benchmark (₹{benchmark:.2f}) "
                    f"while still in learning ({installs}/{LEARNING_INSTALL_THRESHOLD} installs). Early winner signal.")
            else:
                verdict, note = "LEARNING", (
                    f"{installs}/{LEARNING_INSTALL_THRESHOLD} installs — still in learning; "
                    f"CPI {'₹%.2f' % cpi if cpi else 'n/a'} is not yet meaningful. Do not pause or judge.")
        elif benchmark and cpi and cpi <= benchmark * 1.1:
            verdict, note = "WINNER", (
                f"Post-learning CPI ₹{cpi:.2f} beats/matches the incumbent benchmark of ₹{benchmark:.2f}. "
                "Scale candidate — consider shifting budget toward it and building variants.")
        elif benchmark and cpi and cpi <= benchmark * 1.5:
            verdict, note = "AVERAGE", (
                f"Post-learning CPI ₹{cpi:.2f} vs benchmark ₹{benchmark:.2f} — holding its own but not a breakout. "
                "Keep running; refresh hook if CTR decays.")
        else:
            verdict, note = "UNDERPERFORMER", (
                f"Post-learning CPI {'₹%.2f' % cpi if cpi else 'n/a'} vs benchmark "
                f"{'₹%.2f' % benchmark if benchmark else 'n/a'} — materially worse than incumbents. Pause candidate.")

        out.append({
            "ad_id": c["ad_id"],
            "ad_name": c["ad_name"],
            "adset_id": c["adset_id"],
            "campaign_id": c["campaign_id"],
            "status": c["status"],
            "launched": (c.get("created_time") or "")[:10],
            "age_days": c["creative_age_days"],
            "spend_30d": spend,
            "spend_7d": c.get("spend_7d") or 0,
            "installs_30d": installs,
            "installs_7d": c.get("installs_7d") or 0,
            "cpi_30d": cpi,
            "cpi_7d": c.get("cpi_7d"),
            "ctr_30d": c.get("ctr_30d"),
            "ctr_7d": c.get("ctr_7d"),
            "video_hold_rate_pct": c.get("video_hold_rate_pct"),
            "benchmark_cpi": round(benchmark, 2) if benchmark else None,
            "in_learning": in_learning,
            "verdict": verdict,
            "note": note,
        })
    return out


def analyse_targeting(adsets):
    out = []
    for a in adsets:
        t = a.get("targeting", {}) or {}
        geo = t.get("geo_locations", {}) or {}
        countries = geo.get("countries", []) or []
        cities = [c.get("name") for c in (geo.get("cities") or [])]
        regions = [r.get("name") for r in (geo.get("regions") or [])]
        age_min = t.get("age_min")
        age_max = t.get("age_max")
        genders = t.get("genders", []) or []
        interests = []
        for spec in (t.get("flexible_spec") or []):
            interests.extend([i.get("name") for i in (spec.get("interests") or [])])
        exclusions = []
        excl = t.get("exclusions") or {}
        for spec in (excl.get("flexible_spec") or []):
            exclusions.extend([i.get("name") for i in (spec.get("interests") or [])])

        # Spot misconfigurations
        flags = []
        if "retarg" in (a.get("name") or "").lower() and a.get("optimization_goal") == "APP_INSTALLS":
            flags.append("⚠️ Retargeting campaign optimized for APP_INSTALLS — likely targeting users who already installed")
        if len(interests) > 10:
            flags.append(f"⚠️ Very broad interest stack ({len(interests)} interests) — may dilute targeting precision")
        if len(cities) == 1 and not regions and not countries:
            flags.append(f"🌍 Single-city targeting ({cities[0]}) — consider geographic expansion if creative is performing")

        out.append({
            "adset_id": a["id"],
            "adset_name": a.get("name"),
            "campaign_id": a["campaign_id"],
            "status": a.get("effective_status"),
            "daily_budget_inr": round(int(a.get("daily_budget") or 0) / 100, 2),
            "lifetime_budget_inr": round(int(a.get("lifetime_budget") or 0) / 100, 2),
            "optimization_goal": a.get("optimization_goal"),
            "bid_strategy": a.get("bid_strategy"),
            "billing_event": a.get("billing_event"),
            "age_range": f"{age_min}–{age_max}" if age_min else "All",
            "genders": ["male" if g == 1 else "female" for g in genders] or ["all"],
            "countries": countries,
            "cities": cities[:5],
            "regions": regions[:5],
            "interests": interests[:15],
            "exclusions": exclusions[:5],
            "flags": flags,
        })
    return out


def budget_reallocation(campaigns_analysis, non_install_campaigns=None):
    """Find inefficiencies + propose specific moves. Campaigns that don't
    optimize installs are excluded — comparing their install-CPI against
    acquisition campaigns produces misleading 'shift budget' recommendations."""
    non_install_campaigns = non_install_campaigns or set()
    active = [c for c in campaigns_analysis
              if c["status"] == "ACTIVE" and c["cpi_30d"]
              and c["id"] not in non_install_campaigns]
    if len(active) < 2:
        return []
    active.sort(key=lambda x: x["cpi_30d"])
    best, worst = active[0], active[-1]
    moves = []
    if worst["cpi_30d"] > best["cpi_30d"] * 1.5:
        moves.append({
            "from_campaign": worst["name"],
            "from_campaign_id": worst["id"],
            "from_cpi": worst["cpi_30d"],
            "to_campaign": best["name"],
            "to_campaign_id": best["id"],
            "to_cpi": best["cpi_30d"],
            "efficiency_multiple": round(worst["cpi_30d"] / best["cpi_30d"], 1),
            "rationale": f"{best['name']} delivers installs at ₹{best['cpi_30d']:.2f} vs ₹{worst['cpi_30d']:.2f} for {worst['name']} — {round(worst['cpi_30d']/best['cpi_30d'],1)}x more efficient. Shifting budget here should compound install volume."
        })
    return moves


def opportunity_scan(campaigns_analysis, creatives_analysis, targeting_analysis):
    """Surface improvement opportunities the campaigns aren't currently exploiting."""
    opps = []
    active_creatives = [c for c in creatives_analysis if c["status"] == "ACTIVE"]
    if active_creatives:
        unique_bodies = set([c["creative_body"][:80] for c in active_creatives])
        if len(unique_bodies) < 2:
            opps.append({
                "title": "Creative monotony",
                "detail": f"All {len(active_creatives)} active ads use near-identical copy. Audiences see no variety, accelerating fatigue. Test 2-3 distinct copy angles (e.g., 'home-cooked vs restaurant', 'mom chef story', 'price + speed') in parallel.",
                "priority": "HIGH",
            })
        # Best-performing creative angle
        ranked = sorted([c for c in active_creatives if c["cpi_30d"]], key=lambda x: x["cpi_30d"])
        if len(ranked) >= 2:
            top = ranked[0]
            opps.append({
                "title": "Scale the winning creative",
                "detail": f"'{top['ad_name']}' is your most efficient at ₹{top['cpi_30d']:.2f} CPI. Build 2-3 variants (different hook, different chef story, vertical vs square) to compound its performance.",
                "priority": "MEDIUM",
            })

    # Targeting opportunities
    cities_used = set()
    for t in targeting_analysis:
        if t["status"] == "ACTIVE":
            cities_used.update(t["cities"])
    if cities_used and "Bangalore" in cities_used and not (cities_used - {"Bangalore"}):
        opps.append({
            "title": "Geographic expansion",
            "detail": "All active targeting is Bangalore-only. With your current ₹2.68 CPI baseline, you could test Mumbai, Hyderabad, or Pune — tier-1 cities with similar home-food demand profiles.",
            "priority": "MEDIUM",
        })

    # Bid strategy opportunities
    cost_cap_count = sum(1 for c in campaigns_analysis if c.get("bid_strategy") == "COST_CAP")
    lowest_cost = sum(1 for c in campaigns_analysis if c.get("bid_strategy") == "LOWEST_COST_WITHOUT_CAP")
    if cost_cap_count and lowest_cost:
        opps.append({
            "title": "Bid strategy A/B test",
            "detail": "You're running both COST_CAP and LOWEST_COST campaigns. Compare their efficiency over the last 30 days — if COST_CAP is delivering tighter CPI control with similar volume, consolidate toward it.",
            "priority": "LOW",
        })

    # Pacing
    for c in campaigns_analysis:
        if c["status"] == "ACTIVE" and c["daily_budget_inr"] and c["spend_30d"]:
            expected_30 = c["daily_budget_inr"] * 30
            if c["spend_30d"] < expected_30 * 0.5:
                opps.append({
                    "title": f"Underpacing: {c['name']}",
                    "detail": f"Spent ₹{c['spend_30d']} of expected ₹{expected_30:.0f} over 30 days. Either budget cap is too high, audience too narrow, or auction signal weak. Investigate.",
                    "priority": "MEDIUM",
                })

    return opps


def generate_action_items(campaigns_a, creatives_a, targeting_a, budget_moves, opportunities, new_watch=None):
    """Concrete, executable action items with API-action hints."""
    actions, idx = [], 1
    new_watch = new_watch or []
    learning_ids = {w["ad_id"] for w in new_watch if w["in_learning"]}

    # 0. New-creative cohort signals (launch monitoring)
    for w in new_watch:
        if w["verdict"] == "NO_TRACTION":
            actions.append({
                "id": idx, "priority": "HIGH", "category": "New Creative",
                "title": f"New creative has no traction: {w['ad_name']}",
                "rationale": w["note"] + f" (launched {w['launched']}, {w['age_days']}d ago)",
                "api_action": {"type": "manual_review", "entity_id": w["ad_id"]},
                "entity_name": w["ad_name"], "status": "pending",
            }); idx += 1
        elif w["verdict"] == "UNDERPERFORMER":
            actions.append({
                "id": idx, "priority": "MEDIUM", "category": "New Creative",
                "title": f"Pause underperforming new creative: {w['ad_name']}",
                "rationale": w["note"],
                "api_action": {"type": "pause_ad", "entity_id": w["ad_id"]},
                "entity_name": w["ad_name"], "status": "pending",
            }); idx += 1
        elif w["verdict"] == "WINNER":
            actions.append({
                "id": idx, "priority": "MEDIUM", "category": "New Creative",
                "title": f"Scale winning new creative: {w['ad_name']}",
                "rationale": w["note"],
                "api_action": {"type": "manual_review", "entity_id": w["ad_id"]},
                "entity_name": w["ad_name"], "status": "pending",
            }); idx += 1

    # 1. Fatigued creatives (HIGH priority) — learning-phase ads are exempt:
    #    their early CTR/CPI swings are auction noise, not fatigue.
    for c in creatives_a:
        if c["ad_id"] in learning_ids:
            continue
        if c["fatigue_level"] == "HIGH" and c["status"] == "ACTIVE":
            actions.append({
                "id": idx, "priority": "HIGH", "category": "Creative",
                "title": f"Pause fatigued creative: {c['ad_name']}",
                "rationale": (
                    f"Fatigue score {c['fatigue_score']}/9. "
                    f"CTR change 7d-vs-30d: {c['ctr_decay_pct']}%. "
                    f"CPI change 7d-vs-30d: {c['cpi_spike_pct']}%. "
                    f"Frequency: {c['freq_30d']}. "
                    f"Video hold-rate to 100%: {c['video_hold_rate_pct']}%."
                ),
                "api_action": {"type": "pause_ad", "entity_id": c["ad_id"]},
                "entity_name": c["ad_name"],
                "status": "pending",
            })
            idx += 1

    # 2. Mis-optimized retargeting (HIGH)
    for t in targeting_a:
        if "⚠️ Retargeting campaign optimized for APP_INSTALLS" in (t.get("flags") or []) and t["status"] == "ACTIVE":
            actions.append({
                "id": idx, "priority": "HIGH", "category": "Targeting",
                "title": f"Re-optimize {t['adset_name']} away from APP_INSTALLS",
                "rationale": "Retargeting an audience that has already installed wastes spend. Switch optimization to first-order, post-install event, or app-event (e.g., view_content).",
                "api_action": {"type": "update_optimization_goal", "entity_id": t["adset_id"], "suggested_value": "OFFSITE_CONVERSIONS"},
                "entity_name": t["adset_name"],
                "status": "pending",
            })
            idx += 1

    # 3. Budget reallocation (HIGH)
    for m in budget_moves:
        actions.append({
            "id": idx, "priority": "HIGH", "category": "Budget",
            "title": f"Shift budget from {m['from_campaign']} → {m['to_campaign']}",
            "rationale": m["rationale"],
            "api_action": {
                "type": "reallocate_budget",
                "from_id": m["from_campaign_id"],
                "to_id": m["to_campaign_id"]
            },
            "entity_name": f"{m['from_campaign']} → {m['to_campaign']}",
            "status": "pending",
        })
        idx += 1

    # 4. Medium-fatigue creatives (MEDIUM) — learning-phase ads exempt here too
    for c in creatives_a:
        if c["ad_id"] in learning_ids:
            continue
        if c["fatigue_level"] == "MEDIUM" and c["status"] == "ACTIVE":
            actions.append({
                "id": idx, "priority": "MEDIUM", "category": "Creative",
                "title": f"Monitor + refresh: {c['ad_name']}",
                "rationale": (
                    f"Early fatigue signs (score {c['fatigue_score']}/9). "
                    f"Plan a replacement creative within 2 weeks before performance deteriorates."
                ),
                "api_action": {"type": "monitor", "entity_id": c["ad_id"]},
                "entity_name": c["ad_name"],
                "status": "pending",
            })
            idx += 1

    # 5. Opportunity items
    for opp in opportunities:
        actions.append({
            "id": idx,
            "priority": opp["priority"],
            "category": "Opportunity",
            "title": opp["title"],
            "rationale": opp["detail"],
            "api_action": {"type": "manual_review"},
            "entity_name": opp["title"],
            "status": "pending",
        })
        idx += 1

    # 6. Reactivation candidates (LOW)
    for c in campaigns_a:
        if c["status"] == "PAUSED" and c["cpi_90d"] and c["cpi_90d"] < 5:
            actions.append({
                "id": idx, "priority": "LOW", "category": "Campaign",
                "title": f"Consider reactivating {c['name']}",
                "rationale": f"Paused but had strong 90d CPI of ₹{c['cpi_90d']:.2f}. With refreshed creative, could deliver again.",
                "api_action": {"type": "activate_campaign", "entity_id": c["id"]},
                "entity_name": c["name"],
                "status": "pending",
            })
            idx += 1

    return actions


def executive_summary(campaigns_a, creatives_a, action_items):
    active = [c for c in campaigns_a if c["status"] == "ACTIVE"]
    spend_90 = sum(c["spend_90d"] or 0 for c in campaigns_a)
    spend_30 = sum(c["spend_30d"] or 0 for c in campaigns_a)
    spend_7  = sum(c["spend_7d"]  or 0 for c in campaigns_a)
    installs_90 = sum(c["installs_90d"] or 0 for c in campaigns_a)
    installs_30 = sum(c["installs_30d"] or 0 for c in campaigns_a)
    installs_7  = sum(c["installs_7d"]  or 0 for c in campaigns_a)
    blended_cpi_90 = round(spend_90 / installs_90, 2) if installs_90 else None
    blended_cpi_30 = round(spend_30 / installs_30, 2) if installs_30 else None
    blended_cpi_7  = round(spend_7  / installs_7,  2) if installs_7  else None
    fatigued_active = [c for c in creatives_a if c["fatigue_level"] in ("HIGH","MEDIUM") and c["status"] == "ACTIVE"]
    high_pri = [a for a in action_items if a["priority"] == "HIGH"]

    # Account health score (0-100)
    health = 100
    if blended_cpi_30 and blended_cpi_30 > 5:  health -= 15
    if blended_cpi_30 and blended_cpi_30 > 10: health -= 15
    health -= min(30, len(fatigued_active) * 10)
    health -= min(20, len(high_pri) * 5)
    health = max(0, health)

    return {
        "run_date": TODAY,
        "account_id": ACCOUNT,
        "active_campaigns": len(active),
        "total_campaigns": len(campaigns_a),
        "spend_90d": round(spend_90, 2),
        "spend_30d": round(spend_30, 2),
        "spend_7d":  round(spend_7,  2),
        "installs_90d": installs_90,
        "installs_30d": installs_30,
        "installs_7d":  installs_7,
        "blended_cpi_90d": blended_cpi_90,
        "blended_cpi_30d": blended_cpi_30,
        "blended_cpi_7d":  blended_cpi_7,
        "fatigued_active_creatives": len(fatigued_active),
        "action_items_total": len(action_items),
        "action_items_high": len(high_pri),
        "health_score": health,
    }


# ────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ────────────────────────────────────────────────────────────────────────────
def run(json_only=False):
    print("⏳ [1/5] Fetching campaigns…")
    campaigns = pull_campaigns()
    print(f"     found {len(campaigns)} campaigns")

    campaign_ids = [c["id"] for c in campaigns]
    if not campaign_ids:
        sys.exit("❌ No campaigns found on this ad account")

    print("⏳ [2/5] Fetching insights (90d / 30d / 7d)…")
    def insight_map(level, window):
        rows = pull_insights(level, window)
        key = "campaign_id" if level == "campaign" else "ad_id"
        return {r[key]: r for r in rows if r.get(key)}

    insights_by_window = {
        "90d": insight_map("campaign", "last_90d"),
        "30d": insight_map("campaign", "last_30d"),
        "7d":  insight_map("campaign", "last_7d"),
    }

    print("⏳ [3/5] Fetching ad sets + targeting…")
    adsets = pull_adsets(campaign_ids)
    print(f"     found {len(adsets)} ad sets")

    print("⏳ [4/5] Fetching ads + creative + ad-level insights…")
    ads = pull_ads(campaign_ids)
    print(f"     found {len(ads)} ads")
    ad_insights = {
        "90d": insight_map("ad", "last_90d"),
        "30d": insight_map("ad", "last_30d"),
        "7d":  insight_map("ad", "last_7d"),
    }

    print("🧠 [5/5] Running analysis modules…")
    # Campaigns whose ACTIVE ad sets optimize for something other than installs
    # (remarketing/checkout campaigns) — excluded from all install-CPI comparisons.
    non_install = {a["campaign_id"] for a in adsets
                   if a.get("effective_status") == "ACTIVE"
                   and a.get("optimization_goal") not in (None, "APP_INSTALLS")}
    campaigns_a = analyse_campaigns(campaigns, insights_by_window, non_install)
    creatives_a = analyse_creatives(ads, ad_insights)
    new_watch = new_creative_watch(creatives_a)
    targeting_a = analyse_targeting(adsets)
    budget_moves = budget_reallocation(campaigns_a, non_install)
    opportunities = opportunity_scan(campaigns_a, creatives_a, targeting_a)
    action_items = generate_action_items(campaigns_a, creatives_a, targeting_a, budget_moves, opportunities, new_watch)
    summary = executive_summary(campaigns_a, creatives_a, action_items)
    summary["new_creatives_28d"] = len(new_watch)
    summary["new_creatives_learning"] = sum(1 for w in new_watch if w["in_learning"])
    summary["new_creatives_winning"] = sum(1 for w in new_watch if w["verdict"] in ("WINNER", "PROMISING"))

    payload = {
        "summary": summary,
        "campaigns": campaigns_a,
        "creatives": creatives_a,
        "new_creative_watch": new_watch,
        "targeting": targeting_a,
        "budget_reallocation": budget_moves,
        "opportunities": opportunities,
        "action_items": action_items,
    }

    # Save JSON (date-stamped + latest pointer)
    json_path = OUT_DIR / f"ads-analysis-{STAMP}.json"
    json_path.write_text(json.dumps(payload, indent=2))
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, indent=2))
    print(f"✅ JSON saved → {json_path}")

    if json_only:
        return str(json_path), None

    # Build PDF
    print("📄 Building branded PDF…")
    pdf_path = OUT_DIR / f"Bhookle-AdsReport-{STAMP}.pdf"
    build_script = SKILL_DIR / "scripts" / "build_report.py"
    result = subprocess.run(
        ["python3", str(build_script), str(json_path), str(pdf_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"⚠️  PDF build failed:\n{result.stderr}")
        return str(json_path), None
    print(f"✅ PDF saved → {pdf_path}")
    return str(json_path), str(pdf_path)


# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    DEBUG = args.debug
    json_path, pdf_path = run(json_only=args.json_only)
    print("\n📊 ─── Analysis complete ───")
    print(f"  JSON: {json_path}")
    print(f"  PDF:  {pdf_path or '(skipped)'}")
