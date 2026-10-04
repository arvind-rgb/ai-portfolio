"""
Lead DISCOVERY adapters for the getLeads engine.

Each adapter returns a list of candidate dicts in this unified shape:
    {
      "firm":         str,   # investor / fund name (raw, pre-canonicalization)
      "signal_type":  str,   # news_fund_close | news_seed_deal | thesis | lookalike | static_deal
      "trigger_text": str,   # human-readable "why now" (headline / portfolio note)
      "source_url":   str,
      "date":         str,   # YYYY-MM-DD or ""
      "portfolio_co": str,   # startup they backed, if known
      "round":        str,   # round type, if known
      "amount":       str,   # amount, if known
      "sector_hint":  str,   # domain / sector text, if known
    }

Sourcing is intentionally separate from enrichment — these only FIND firms +
the signal. Gating, scoring and contact-enrichment happen downstream.
"""
import os
import re
import json
import time
import requests

import feedparser

from enrich_engine import _gemini  # Google-grounded Gemini (reused)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36")
}

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              + GEMINI_MODEL + ":generateContent")

# Bhookle thesis keywords — used for static-corpus filtering + scoring hints.
FOOD_KEYWORDS = (
    "food", "kitchen", "tiffin", "meal", "snack", "beverage", "dining",
    "restaurant", "grocery", "dairy", "fmcg", "d2c", "consumer", "hyperlocal",
    "qsr", "nutrition", "cloud kitchen", "home food", "cook", "bakery",
    "coffee", "tea", "spice", "sweets", "confection", "consumer tech",
    "consumer internet", "cpg", "packaged", "brand", "lifestyle",
)

# ──────────────────────────────────────────────────────────────────────────────
# Plain (non-grounded) Gemini call for fast structured extraction from text we
# already have (headlines). Grounding not needed → faster, cheaper, deterministic.
# ──────────────────────────────────────────────────────────────────────────────
def _gemini_extract(prompt, timeout=30):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        r = requests.post(
            GEMINI_URL + "?key=" + key,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        cand = (r.json().get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
        m = re.search(r"\[[\s\S]*\]", text) or re.search(r"\{[\s\S]*\}", text)
        return json.loads(m.group()) if m else None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# A. Google News RSS — the real-time signal engine (zero-key, no anti-bot)
# ──────────────────────────────────────────────────────────────────────────────
NEWS_FEEDS = [
    # fund-close / dry-powder signals (the fund IS the investor)
    {"signal": "news_fund_close",
     "q": 'India ("micro VC" OR "seed fund" OR "angel fund" OR "venture fund") '
          '("first close" OR "final close" OR "new fund" OR "launches fund" OR "raises fund") '
          '(consumer OR D2C OR foodtech OR FMCG)'},
    # sector seed deals (startup named; we extract the investor)
    {"signal": "news_seed_deal",
     "q": 'India (seed OR "pre-seed") funding '
          '(foodtech OR "cloud kitchen" OR D2C OR "consumer tech" OR consumer OR hyperlocal OR tiffin OR FMCG)'},
    # named angels / HNIs writing angel cheques into consumer/food (LinkedIn-first)
    {"signal": "angel_scout",
     "q": 'India ("angel round" OR "angel investor" OR "angel investment" OR HNI OR "family office") '
          '(D2C OR consumer OR foodtech OR "cloud kitchen" OR FMCG OR "consumer brand")'},
]


def _news_rss_url(query):
    from urllib.parse import quote
    return (f"https://news.google.com/rss/search?q={quote(query)}"
            "&hl=en-IN&gl=IN&ceid=IN:en")


def from_news_rss(limit_per_feed=20):
    """Pull recent funding headlines, then extract the investor firm from each
    via a single batched Gemini call per feed."""
    out = []
    for feed in NEWS_FEEDS:
        try:
            parsed = feedparser.parse(_news_rss_url(feed["q"]))
        except Exception:
            continue
        entries = parsed.entries[:limit_per_feed]
        if not entries:
            continue
        # Build a numbered headline list for batched extraction
        lines = []
        meta = []
        for i, e in enumerate(entries):
            title = (e.get("title") or "").strip()
            if not title:
                continue
            lines.append(f"{i}. {title}")
            meta.append({
                "url": e.get("link", ""),
                "date": _to_date(e.get("published", "")),
                "title": title,
            })
        if not lines:
            continue

        prompt = (
            "From each Indian startup-funding headline below, extract the INVESTOR "
            "firm(s) and the startup. Headlines are numbered.\n\n"
            "Return ONLY a JSON array; one object per headline that names a real "
            "investor (skip headlines with no identifiable investor):\n"
            '[{"i": <number>, "investor": "Fund/Investor name", '
            '"startup": "startup name or empty", '
            '"is_fund_launch": true/false}]\n\n'
            "Rules: investor = the VC/PE/angel/fund (NOT the startup). If a fund is "
            "launching/closing a new fund, set is_fund_launch true and investor = that "
            "fund. If multiple investors, emit multiple objects with the same i.\n\n"
            + "\n".join(lines)
        )
        extracted = _gemini_extract(prompt) or []
        for obj in extracted if isinstance(extracted, list) else []:
            try:
                i = int(obj.get("i"))
                inv = (obj.get("investor") or "").strip()
                if not inv or i < 0 or i >= len(meta):
                    continue
                m = meta[i]
                out.append({
                    "firm": inv,
                    "signal_type": "news_fund_close" if obj.get("is_fund_launch") else feed["signal"],
                    "trigger_text": m["title"],
                    "source_url": m["url"],
                    "date": m["date"],
                    "portfolio_co": (obj.get("startup") or "").strip(),
                    "round": "", "amount": "", "sector_hint": "",
                })
            except Exception:
                continue
        time.sleep(0.3)
    return out


def _to_date(published):
    """Best-effort RSS pubDate → YYYY-MM-DD."""
    if not published:
        return ""
    try:
        import email.utils as eut
        dt = eut.parsedate_to_datetime(published)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# B. Gemini-grounded thesis queries — high-fit funds with built-in trigger
# ──────────────────────────────────────────────────────────────────────────────
THESIS_QUERIES = [
    "List Indian micro-VCs, solo GPs, angel syndicates, or individual angels that "
    "have invested in home-food, cloud-kitchen, tiffin, food-delivery, D2C-food, or "
    "consumer-tech startups in the last 18 months. EXCLUDE celebrity investors and "
    "top-brand, heavily-oversubscribed funds. For each give the name and the specific portfolio company.",

    "List Indian seed / pre-seed micro-VCs, solo GPs, or angel syndicates that "
    "announced a NEW fund or fresh close in the last 12 months and back consumer / "
    "consumer-tech / foodtech / D2C / FMCG. Prefer smaller, reachable, lesser-known "
    "funds over marquee names. Give the fund name and any recent deal.",
]


def from_gemini_thesis():
    """Ask Gemini (Google-grounded) targeted analyst questions; parse fund + portfolio."""
    out = []
    for q in THESIS_QUERIES:
        prompt = (
            q + "\n\nReturn ONLY a JSON array:\n"
            '[{"investor": "fund name", "portfolio_co": "company or empty", '
            '"note": "one short phrase on why (sector/stage/recency)"}]\n'
            "Only real, currently-active India investors. If unsure, omit."
        )
        text, _, _ = _gemini(prompt)
        m = re.search(r"\[[\s\S]*\]", text or "")
        if not m:
            continue
        try:
            arr = json.loads(m.group())
        except Exception:
            continue
        for o in arr if isinstance(arr, list) else []:
            inv = (o.get("investor") or "").strip()
            if not inv:
                continue
            out.append({
                "firm": inv,
                "signal_type": "thesis",
                "trigger_text": (o.get("note") or "").strip()
                                or f"Invested in {o.get('portfolio_co','')}".strip(),
                "source_url": "", "date": "",
                "portfolio_co": (o.get("portfolio_co") or "").strip(),
                "round": "", "amount": "", "sector_hint": "",
            })
        time.sleep(0.3)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# B2. Named-angel / HNI scout — the LinkedIn-first people source
# Surfaces INDIVIDUAL angels/HNIs (people, not funds) so enrichment can lock their
# personal LinkedIn profile. Explicitly excludes celebrity/marquee names.
# ──────────────────────────────────────────────────────────────────────────────
ANGEL_SCOUT_QUERIES = [
    "List NAMED individual angel investors or HNIs based in India who have "
    "personally written angel or seed cheques into D2C, consumer-tech, foodtech, "
    "FMCG, or consumer-brand startups in the last ~18 months and are ACTIVE on "
    "LinkedIn. Prefer operators and founders-turned-angels, syndicate leads, and "
    "first-cheque angels who are genuinely reachable. STRICTLY EXCLUDE celebrity / "
    "TV-show investors and partners at top-brand, heavily-oversubscribed funds. For each give the "
    "person's full name and one startup they backed.",

    "List lesser-known Indian angel investors and HNIs (NOT celebrities) who back "
    "early-stage consumer, food, or D2C founders and are active on LinkedIn today. "
    "Give each person's name and a recent portfolio company.",
]


def from_angel_scout():
    """Google-grounded scout for reachable, named India-based angels/HNIs in
    consumer/food/D2C. Returns candidates whose 'firm' is the person's name."""
    out = []
    for q in ANGEL_SCOUT_QUERIES:
        prompt = (
            q + "\n\nReturn ONLY a JSON array:\n"
            '[{"name": "person full name", "portfolio_co": "startup or empty", '
            '"note": "one short phrase (sector / why reachable)"}]\n'
            "Only real, currently-active, India-based individual angels who are NOT "
            "celebrities/marquee investors. If unsure, omit."
        )
        text, _, _ = _gemini(prompt)
        m = re.search(r"\[[\s\S]*\]", text or "")
        if not m:
            continue
        try:
            arr = json.loads(m.group())
        except Exception:
            continue
        for o in arr if isinstance(arr, list) else []:
            nm = (o.get("name") or "").strip()
            if not nm or len(nm) > 60:
                continue
            out.append({
                "firm": nm,
                "signal_type": "angel_scout",
                "trigger_text": (o.get("note") or "").strip()
                                or f"Angel in {o.get('portfolio_co','')}".strip(),
                "source_url": "", "date": "",
                "portfolio_co": (o.get("portfolio_co") or "").strip(),
                "round": "angel", "amount": "", "sector_hint": "consumer/food",
            })
        time.sleep(0.3)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# C. Portfolio look-alike expansion — co-investors in food-tech winners
# ──────────────────────────────────────────────────────────────────────────────
LOOKALIKE_COMPANIES = [
    "Rebel Foods", "Country Delight", "Curefoods", "The Good Bug", "EatFit",
    "Blue Tokai Coffee", "Slurrp Farm", "The Whole Truth Foods", "Sleepy Owl Coffee",
    "Wow Momo", "Hocco Ice Cream", "Zoff Foods",
]


def from_lookalike(companies=None, per_company=1):
    """For known food-tech companies, surface their (early-stage) investors."""
    out = []
    for co in (companies or LOOKALIKE_COMPANIES)[:8]:
        prompt = (
            f"Who are the early-stage / seed investors in the Indian food/consumer "
            f"startup '{co}'? Return ONLY a JSON array of fund names: "
            '[{"investor": "fund name"}]. Only real investors; if unknown, [].'
        )
        text, _, _ = _gemini(prompt)
        m = re.search(r"\[[\s\S]*\]", text or "")
        if not m:
            continue
        try:
            arr = json.loads(m.group())
        except Exception:
            continue
        for o in arr if isinstance(arr, list) else []:
            inv = (o.get("investor") or "").strip()
            if inv:
                out.append({
                    "firm": inv,
                    "signal_type": "lookalike",
                    "trigger_text": f"Co-investor in {co} (food/consumer)",
                    "source_url": "", "date": "",
                    "portfolio_co": co,
                    "round": "", "amount": "", "sector_hint": "",
                })
        time.sleep(0.3)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# D. Static reference + discovery corpus — InvestorFinder funding CSVs (gated)
# ──────────────────────────────────────────────────────────────────────────────
INVESTORFINDER_CSVS = [
    "https://raw.githubusercontent.com/jjf2009/InvestorFinder/main/data/india_funding_2026.csv",
    "https://raw.githubusercontent.com/jjf2009/InvestorFinder/main/data/india_funding_2025.csv",
]
_BAD_INVESTORS = (
    "undisclosed", "family offices", "angel investors", "investors", "n/a", "",
    "high-net-worth individuals", "hnis", "various", "others",
)


def from_static_corpus(max_rows_per_file=2000):
    """InvestorFinder funding CSVs → recent SEED/PRE-SEED consumer-food deals.
    Each becomes a high-signal candidate: recent + thesis-matched."""
    import csv, io
    out = []
    for url in INVESTORFINDER_CSVS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code != 200:
                continue
            reader = csv.DictReader(io.StringIO(r.text))
            for n, row in enumerate(reader):
                if n >= max_rows_per_file:
                    break
                inv = (row.get("investor") or "").strip()
                if not inv or inv.lower() in _BAD_INVESTORS:
                    continue
                rnd = (row.get("round") or "").lower()
                if not ("seed" in rnd or "pre" in rnd or "angel" in rnd):
                    continue  # stage gate at source — seed/pre-seed/angel only
                startup = (row.get("startup_name") or "").strip()
                dom = (row.get("domain") or "").strip()
                blob = (startup + " " + dom).lower()
                if not any(k in blob for k in FOOD_KEYWORDS):
                    continue  # sector gate at source — consumer/food only
                out.append({
                    "firm": inv,
                    "signal_type": "static_deal",
                    "trigger_text": f"Backed {startup} ({row.get('round','')}) — {dom}".strip(),
                    "source_url": url,
                    "date": (row.get("scraped_at") or row.get("date") or "").strip(),
                    "portfolio_co": startup,
                    "round": (row.get("round") or "").strip(),
                    "amount": (row.get("amount_usd") or "").strip(),
                    "sector_hint": dom,
                })
        except Exception:
            continue
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrated collection
# ──────────────────────────────────────────────────────────────────────────────
def collect_all(use_news=True, use_thesis=True, use_static=True, use_lookalike=True,
                use_angel_scout=True):
    """Run all enabled adapters IN PARALLEL; return the combined raw candidate
    list. Each adapter is independent (separate network/Gemini calls), so running
    them concurrently cuts discovery wall-time to roughly the slowest single
    source instead of the sum of all sources."""
    from concurrent.futures import ThreadPoolExecutor

    adapters = []
    if use_news:         adapters.append(("news", from_news_rss))
    if use_static:       adapters.append(("static", from_static_corpus))
    if use_thesis:       adapters.append(("thesis", from_gemini_thesis))
    if use_lookalike:    adapters.append(("lookalike", from_lookalike))
    if use_angel_scout:  adapters.append(("angel_scout", from_angel_scout))
    if not adapters:
        return []

    def _run(item):
        name, fn = item
        try:
            return fn() or []
        except Exception as e:
            print(f"[lead_sources] {name}: {e}")
            return []

    cands = []
    with ThreadPoolExecutor(max_workers=len(adapters)) as ex:
        for part in ex.map(_run, adapters):
            cands += part
    return cands
