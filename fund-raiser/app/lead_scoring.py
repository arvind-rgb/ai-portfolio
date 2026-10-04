"""
Lead SCORING + GATING for the getLeads engine.

Two-phase scoring (for efficiency):
  • cheap_prescore(): deterministic, no LLM — ranks raw candidates from signal
    metadata so we only spend LLM calls on a shortlist.
  • final_score(): combines the signal score with the grounded classify_investor
    result (stage/sector/recency), applies hard gates, and assigns a tier.

Canonicalization merges the same firm appearing across multiple signals.
"""
import re
from datetime import datetime

# Tokens stripped to canonicalize a firm name into a comparison key.
_SUFFIXES = {
    "ventures", "venture", "capital", "cap", "partners", "partner", "advisors",
    "advisor", "fund", "funds", "group", "associates", "investments",
    "investment", "vc", "pe", "llp", "pvt", "ltd", "the", "india", "fund",
    "management", "co", "company", "network", "syndicate",
}
# Known aliases → canonical display name.
_ALIASES = {
    # e.g. a fund that rebranded: old name -> current display name (fictional)
    "oldname capital india": "NewName Partners",
}

FOOD_KEYWORDS = (
    "food", "kitchen", "tiffin", "meal", "snack", "beverage", "dining",
    "restaurant", "grocery", "dairy", "fmcg", "qsr", "nutrition",
    "cloud kitchen", "home food", "cook", "bakery", "coffee", "tea",
    "spice", "sweets", "confection", "d2c",
)
CONSUMER_KEYWORDS = ("consumer", "d2c", "retail", "brand", "lifestyle",
                     "consumer tech", "consumer internet", "cpg", "packaged")

# Sector tags that satisfy the refined mandate: angels/HNIs investing in India
# D2C / consumer-tech / food. An angel must fit at least one of these to qualify.
CONSUMER_FIT_TAGS = (
    "consumer", "d2c", "food", "foodtech", "fmcg", "cpg", "consumer tech",
    "consumer internet", "retail", "hyperlocal", "cloud kitchen", "beverage",
    "nutrition", "qsr", "grocery", "lifestyle", "brand",
)

# ── Marquee / celebrity / top-brand investors ────────────────────────────────
# So oversubscribed with warm inbound that a COLD LinkedIn seed pitch realistically
# won't convert — the user asked to skip these and focus on reachable angels.
# Matched as case-insensitive substrings on the firm/person name. Freely editable.
# Public-repo note: the production list holds ~50 real celebrity angels and
# top-brand funds. It is replaced here with fictional examples of each kind.
MARQUEE_INVESTORS = (
    # celebrity / TV-show / unicorn-founder angels (fictional examples)
    "famous founder angel", "tv show shark", "unicorn founder fund",
    # top-brand funds that flood with inbound (fictional examples)
    "megafund capital", "global growth partners", "tier-one ventures",
)


def is_marquee_name(name):
    """True if a firm/person name matches the marquee blocklist (cold outreach
    to them realistically won't convert)."""
    n = (name or "").lower()
    return any(m in n for m in MARQUEE_INVESTORS)


# Generic, non-specific "investor" phrases that news/thesis extraction sometimes
# emits as a name (e.g. "Angel investors", "HNIs", "Undisclosed"). They aren't a
# real person or firm — never worth a classify/enrich slot.
_GENERIC_NONENTITIES = (
    "undisclosed", "n/a", "na", "various", "others", "other", "investors",
    "angel investor", "angel investors", "angels", "high-net-worth", "high net worth",
    "hni", "hnis", "family office", "family offices", "syndicate", "syndicates",
    "group of angels", "several", "multiple", "existing investors", "strategic investors",
    "unknown", "tbd", "consortium",
)


def is_generic_name(name):
    """True if a name is a generic non-entity (not a real person/firm to pursue)."""
    n = re.sub(r"[\(\)]", " ", (name or "").lower()).strip()
    if not n:
        return True
    if n in _GENERIC_NONENTITIES:
        return True
    # phrase forms like "high-net-worth individuals (HNIs)" / "a group of angel investors"
    return any(g in n for g in (
        "high-net-worth", "high net worth", "hnis", "angel investor",
        "family office", "undisclosed", "existing investor", "group of angel"))


def has_consumer_fit(cls):
    """True if the grounded classification shows a consumer / D2C / food / FMCG /
    consumer-tech focus — the sectors Bhookle needs an angel to actually back."""
    if cls.get("invests_consumer_food"):
        return True
    tags = " ".join(cls.get("sector_tags") or []).lower()
    return any(t in tags for t in CONSUMER_FIT_TAGS)

SEED_STAGES = ("pre-seed", "preseed", "pre seed", "seed", "angel")
GROWTH_STAGES = ("growth", "late", "series-c", "series c", "series-d", "series d",
                 "series-e", "buyout", "pre-ipo", "pre ipo")

# First-cheque writer types — the archetypes that put in the very first external
# capital (angels and angel-like micro-vehicles), as opposed to institutional VC
# / PE / family-office / growth funds. Used by the "angels only" gate.
ANGEL_TYPES = ("angel", "angel network", "syndicate", "solo gp", "solo-gp",
               "scout", "micro-vc", "micro vc")
# Check-size bands consistent with a first / seed cheque (small, early).
FIRST_CHEQUE_BANDS = ("<$500k", "$500k-2m")


# ──────────────────────────────────────────────────────────────────────────────
# Canonicalization & dedup
# ──────────────────────────────────────────────────────────────────────────────
def norm_key(name):
    raw = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    alias = _ALIASES.get(raw.strip())
    if alias:
        raw = re.sub(r"[^a-z0-9\s]", " ", alias.lower())
    toks = [t for t in raw.split() if t and t not in _SUFFIXES]
    return "".join(toks) or re.sub(r"[^a-z0-9]", "", (name or "").lower())


def canonical_name(name):
    raw = (name or "").strip()
    alias = _ALIASES.get(re.sub(r"[^a-z0-9\s]", " ", raw.lower()).strip())
    return alias or raw


def merge_candidates(cands):
    """Group raw candidates by canonical key; aggregate signals + triggers."""
    merged = {}
    for c in cands:
        if not (c.get("firm") or "").strip():
            continue
        k = norm_key(c["firm"])
        if not k:
            continue
        if k not in merged:
            merged[k] = {
                "firm": canonical_name(c["firm"]),
                "signals": set(),
                "triggers": [],
                "portfolio_cos": set(),
                "dates": [],
                "rounds": set(),
                "amounts": [],
                "sector_hints": set(),
                "source_urls": [],
            }
        m = merged[k]
        m["signals"].add(c.get("signal_type", ""))
        if c.get("trigger_text"):
            m["triggers"].append(c["trigger_text"])
        if c.get("portfolio_co"):
            m["portfolio_cos"].add(c["portfolio_co"])
        if c.get("date"):
            m["dates"].append(c["date"])
        if c.get("round"):
            m["rounds"].add(c["round"])
        if c.get("amount"):
            m["amounts"].append(c["amount"])
        if c.get("sector_hint"):
            m["sector_hints"].add(c["sector_hint"])
        if c.get("source_url"):
            m["source_urls"].append(c["source_url"])
    # finalize
    out = []
    for k, m in merged.items():
        m["key"] = k
        m["signals"] = {s for s in m["signals"] if s}
        m["latest_date"] = max(m["dates"]) if m["dates"] else ""
        out.append(m)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — cheap deterministic pre-score (no LLM)
# ──────────────────────────────────────────────────────────────────────────────
def _blob(m):
    return " ".join(list(m["portfolio_cos"]) + list(m["sector_hints"]) + m["triggers"]).lower()


def _is_recent(date_str, months=12):
    if not date_str:
        return False
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            d = datetime.strptime(date_str[:10], fmt)
            return (datetime.utcnow() - d).days <= months * 31
        except Exception:
            continue
    return False


def cheap_prescore(m):
    """0-100ish heuristic from signals alone — used to shortlist before LLM calls."""
    score = 0
    blob = _blob(m)
    sigs = m["signals"]

    # signal-type intent
    # angel_scout ranks TOP: these are named, reachable angels/HNIs that match the
    # mandate — funds mostly fail the angels-only gate, so we don't want them
    # crowding the shortlist ahead of real angel candidates.
    if "angel_scout" in sigs:       score += 34   # a NAMED reachable angel/HNI (LinkedIn-first)
    if "news_fund_close" in sigs:   score += 30   # fresh dry powder
    if "static_deal" in sigs:       score += 20   # real recent seed deal on file
    if "news_seed_deal" in sigs:    score += 18
    if "thesis" in sigs:            score += 15
    if "lookalike" in sigs:         score += 10
    if len(sigs) >= 2:              score += 12   # corroborated across sources

    # sector fit
    if any(k in blob for k in FOOD_KEYWORDS):      score += 20
    elif any(k in blob for k in CONSUMER_KEYWORDS): score += 10

    # stage fit (from round text we already have)
    rounds = " ".join(m["rounds"]).lower()
    if any(s in rounds for s in SEED_STAGES):      score += 15

    # recency
    if _is_recent(m["latest_date"]):               score += 10

    return score


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — hard gates + final score (uses classify_investor result)
# ──────────────────────────────────────────────────────────────────────────────
def is_first_cheque_angel(cls):
    """True if this investor is an ANGEL-type first-cheque writer at seed stage.

    Requires all three to hold from the grounded classification:
      • an angel-family type (angel / angel network / syndicate / solo GP /
        scout / micro-VC) — not an institutional VC / PE / family office;
      • writes the FIRST external cheque (writes_first_cheque, or a small
        first-cheque check band as a fallback signal);
      • has a pre-seed / seed / angel stage focus.
    """
    t = (cls.get("type") or "").lower().strip()
    is_angel = any(a in t for a in ANGEL_TYPES) if t else False

    band = (cls.get("check_size_band") or "").lower().strip()
    first_cheque = bool(cls.get("writes_first_cheque")) or band in FIRST_CHEQUE_BANDS

    stages = cls.get("stage_focus") or []
    has_seed = any(any(s in st for s in SEED_STAGES) for st in stages)

    return is_angel and first_cheque and has_seed


def passes_gates(cls, angels_only=False, relax=0):
    """Hard drops BEFORE final scoring. cls = classify_investor() output.

    angels_only=True restricts survivors to the outreach mandate. `relax` widens
    the TYPE requirement only — the four musts (small cheques, early stage, D2C
    fit, not-marquee) always hold:
      relax=0  strict: first-cheque ANGEL-family investors at seed stage
      relax=1  any EARLY fund/investor (seed/pre-seed) writing SMALL cheques
      relax=2  as 1, but an unknown cheque-band is tolerated (classifier often
               can't find the band for small funds)
    """
    if not cls.get("is_investor"):
        return False, "not an investor"
    if not cls.get("geo_india"):
        return False, "not India-active"
    stages = cls.get("stage_focus") or []
    has_seed = any(any(s in st for s in SEED_STAGES) for st in stages)
    only_growth = stages and all(any(g in st for g in GROWTH_STAGES) for st in stages)
    if only_growth and not has_seed:
        return False, "growth/PE only — no seed program"
    if angels_only:
        if cls.get("is_marquee"):
            return False, "marquee/oversubscribed — cold outreach won't convert"
        if not has_consumer_fit(cls):
            return False, "not focused on D2C / consumer-tech / food"
        if relax == 0:
            if not is_first_cheque_angel(cls):
                return False, "not a seed-stage first-cheque angel"
        else:
            if not has_seed:
                return False, "no seed / pre-seed program"
            band = (cls.get("check_size_band") or "").lower().strip()
            small = bool(cls.get("writes_first_cheque")) or band in FIRST_CHEQUE_BANDS
            if relax >= 2:
                small = small or band == ""      # unknown band tolerated
            if not small:
                return False, "cheque size too large for a seed round"
    return True, ""


def final_score(m, cls):
    """0-100 transparent score with the four-bucket matrix (+ penalties)."""
    sectors = " ".join(cls.get("sector_tags") or []).lower()
    stages = cls.get("stage_focus") or []
    signals = []
    score = 0

    # ── Thesis / Sector fit (35) ──
    # VERIFIED signal only. Two sources are trusted:
    #   (a) a REAL portfolio company name that is itself food/consumer, and
    #   (b) a FOCUSED grounded classification (classify_investor).
    # We do NOT use the free-text `sector_hints` blob (stored sector strings are
    # often wrong, e.g. a firm mislabeled "Home Food / Food Tech"). And we ignore
    # a classification that lists too many sectors — a huge "everything" list is a
    # hallucinated guess, not a real thesis, so it must not assert a hard fit.
    sector_tags = cls.get("sector_tags") or []
    focused = 1 <= len(sector_tags) <= 8          # loosened from 6
    portfolio_blob = " ".join(m.get("portfolio_cos") or []).lower()
    food_hit = (any(k in portfolio_blob for k in FOOD_KEYWORDS)
                or (focused and "food" in sectors))
    consumer_hit = (any(k in portfolio_blob for k in CONSUMER_KEYWORDS)
                    or (focused and cls.get("invests_consumer_food"))
                    or (focused and any(k in sectors for k in ("consumer", "d2c"))))
    # Softer signal: consumer evidence from a BROAD (unfocused) classification —
    # lower confidence, partial credit, never asserted as a hard "thesis match".
    soft_consumer = (not consumer_hit) and (
        bool(cls.get("invests_consumer_food"))
        or any(k in sectors for k in ("consumer", "d2c", "fmcg")))

    if consumer_hit:
        score += 15; signals.append("Invests in consumer/D2C")
    elif soft_consumer:
        score += 8;  signals.append("Likely consumer/D2C focus")
    if food_hit:
        score += 20
        pc = next(iter(m["portfolio_cos"]), "")
        signals.append(f"Food/D2C-food thesis match" + (f" (backed {pc})" if pc else ""))

    # ── Stage fit (25) ──
    has_seed = any(any(s in st for s in SEED_STAGES) for st in stages)
    multistage_seed = has_seed and len(stages) > 1
    if has_seed and not multistage_seed:
        score += 25; signals.append("Writes seed / pre-seed checks")
    elif multistage_seed:
        score += 18; signals.append("Multi-stage with a seed program")
    elif has_seed:
        score += 18

    # ── Recency / dry powder (25) ──
    if "news_fund_close" in m["signals"]:
        score += 25; signals.append("Just closed a new fund (fresh dry powder)")
    elif "static_deal" in m["signals"] and _is_recent(m["latest_date"], 6):
        score += 22; signals.append("Recent consumer/food seed deal (<6mo)")
    elif cls.get("recent_activity") or _is_recent(m["latest_date"], 12):
        score += 10; signals.append("Active in last 12 months")

    # ── Accessibility (15) — type-based; refined post-enrichment ──
    t = (cls.get("type") or "").lower()
    if any(x in t for x in ("angel", "solo", "syndicate", "micro")):
        score += 8; signals.append("Angel/solo-GP/syndicate — higher reply odds")

    # ── Penalty: oversized cheques for a seed startup ──
    if cls.get("check_size_band") == ">$10M" and not has_seed:
        score -= 15; signals.append("⚠ Large-cheque fund — may be too late-stage")

    score = max(0, min(100, score))
    tier = ("Tier 1 [High Intent]" if score >= 70
            else "Tier 2 [Niche Fit]" if score >= 45
            else "Tier 3 [Low]")
    return score, tier, signals


def action_item(m, cls, score):
    """Suggested outreach angle, surfacing the warmest trigger."""
    pc = next(iter(m["portfolio_cos"]), "")
    if "news_fund_close" in m["signals"]:
        return ("Reach out now — they just raised a fund and are actively deploying. "
                "Lead with Bhookle's traction + that you fit their new mandate.")
    if pc:
        return (f"Warm angle: reference their investment in {pc} — position Bhookle "
                "as a complementary bet in home-food/D2C.")
    if cls.get("invests_consumer_food"):
        return "Lead with consumer/D2C fit and Bhookle's category thesis."
    return "Standard intro — lead with traction and the home-food opportunity."
