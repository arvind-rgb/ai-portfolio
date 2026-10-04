"""
getLeads orchestrator — turns raw multi-source signals into a ranked, gated,
scored shortlist of investor leads. Enrichment (contact discovery) is done by
the caller (app.py) using enrich_engine.smart_enrich on the survivors.

Pipeline:  DISCOVER → CANONICALIZE/DEDUP → SUPPRESS → CHEAP-PRESCORE → SHORTLIST
           → CLASSIFY+GATE → FINAL-SCORE → RANK → return top-N

Returns dicts ready to persist as InvestmentLead (minus contact fields):
  {investor_name, investor_type, invested_company, sector, deal_date, source_url,
   confidence_score, priority_tier, trigger_signals, action_item, signal_date,
   _classify}   # _classify kept for the caller if useful
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

import lead_sources
import lead_scoring as ls
from enrich_engine import classify_investor

# firm norm_key → classify_investor() result, per server process. Grounded
# classifications are stable within a session; this makes back-to-back fetch
# passes skip re-classifying the same rediscovered firms.
_CLASSIFY_CACHE = {}


def get_leads(limit=15, shortlist=30, existing_names=None,
              existing_with_status=None,
              progress=None, sources=None, angels_only=True, relax=0):
    """Discover + score + rank.

    existing_names        = ALL investor names in the DB (any status) — these
                            are suppressed so we never re-discover them as fresh.
    existing_with_status  = {norm_key: status} map — used to annotate a candidate
                            as 'already contacted' if it exists under a non-New
                            status (e.g. 'Reached Out', 'Not Interested') so we
                            skip it rather than treating it as a fresh lead.
                            Any candidate matching a 'Not Interested' lead is
                            hard-dropped so a fetch batch never re-surfaces a firm
                            already rejected.
    progress              = optional callable(stage, dict) for live status updates.
    sources               = optional dict of which adapters to run.
    angels_only           = when True (default), only seed-stage angel / first-
                            cheque investors survive the gate — VCs, PE, family
                            offices and growth funds are dropped.
    """
    def emit(stage, **kw):
        if progress:
            try: progress(stage, kw)
            except Exception: pass

    sources = sources or {}
    # ── DISCOVER ──
    raw = lead_sources.collect_all(
        use_news=sources.get("news", True),
        use_thesis=sources.get("thesis", True),
        use_static=sources.get("static", True),
        use_lookalike=sources.get("lookalike", True),
        use_angel_scout=sources.get("angel_scout", True),
    )
    emit("discovered", count=len(raw))

    # ── CANONICALIZE / DEDUP ──
    merged = ls.merge_candidates(raw)
    emit("deduped", count=len(merged))

    # ── SUPPRESS ──
    # Suppress ALL known firms (any status) — "Is Already There?" check.
    # This covers:
    #   - leads already in the DB as New (would just be re-added)
    #   - leads already Reached Out / Engaged / Not Interested / No Response
    #     (don't re-open them as fresh; they have history)
    existing_keys = {ls.norm_key(n) for n in (existing_names or [])}
    already_status = existing_with_status or {}  # norm_key → status

    # Drop generic non-entities ("Angel investors", "HNIs", "Undisclosed", …) — they
    # are extraction noise, not a real person/firm to pursue.
    merged = [m for m in merged if not ls.is_generic_name(m["firm"])]

    suppressed_existing, suppressed_contacted, suppressed_not_interested = 0, 0, 0
    filtered = []
    for m in merged:
        if m["key"] in existing_keys:
            status = already_status.get(m["key"], "")
            if status == "Not Interested":
                # Never re-surface a firm we already marked Not Interested.
                suppressed_not_interested += 1
            elif status and status not in ("New", ""):
                suppressed_contacted += 1
            else:
                suppressed_existing += 1
            continue
        filtered.append(m)
    merged = filtered

    # ── DROP MARQUEE / CELEBRITY / TOP-BRAND names ──
    # Cold LinkedIn outreach to these realistically won't convert (the user asked
    # to skip the super-popular investors). Matched on the firm/person name.
    if angels_only:
        kept, suppressed_marquee = [], 0
        for m in merged:
            if ls.is_marquee_name(m["firm"]):
                suppressed_marquee += 1
            else:
                kept.append(m)
        merged = kept
    else:
        suppressed_marquee = 0

    emit("suppressed", count=len(merged),
         already_in_db=suppressed_existing,
         already_contacted=suppressed_contacted,
         already_not_interested=suppressed_not_interested,
         marquee=suppressed_marquee)

    # ── CHEAP PRE-SCORE + rank → shortlist ──
    for m in merged:
        m["_pre"] = ls.cheap_prescore(m)
    merged.sort(key=lambda m: m["_pre"], reverse=True)
    short = merged[:shortlist]
    emit("shortlisted", count=len(short))

    # ── CLASSIFY (grounded, parallel) + HARD GATES ──
    # Cross-run cache: consecutive passes rediscover largely the same firms, and
    # a grounded classification doesn't change within a session — so cache by
    # firm-key and make repeat passes' qualify phase near-instant.
    def classify_one(m):
        cached = _CLASSIFY_CACHE.get(m["key"])
        if cached is not None:
            return m, cached
        cls = classify_investor(m["firm"])
        if cls.get("is_investor") or cls.get("reason") not in ("no/parse error",):
            _CLASSIFY_CACHE[m["key"]] = cls   # don't cache transient API failures
        return m, cls

    qualified = []
    done = 0
    # More workers → faster qualification. These are Gemini-grounded HTTP calls
    # (I/O-bound), so we can safely fan out well beyond CPU count.
    classify_workers = min(16, max(2, len(short)))
    with ThreadPoolExecutor(max_workers=classify_workers) as ex:
        futs = {ex.submit(classify_one, m): m for m in short}
        for fut in as_completed(futs):
            done += 1
            emit("classifying", done=done, total=len(short))
            try:
                m, cls = fut.result()
            except Exception:
                continue
            ok, why = ls.passes_gates(cls, angels_only=angels_only, relax=relax)
            if not ok:
                continue
            # RECENCY is a must in relaxed passes: widening the type requirement
            # must not let in dormant funds. Accept either grounded recent activity
            # or a fresh signal date on the merged candidate.
            if relax >= 1 and not (cls.get("recent_activity")
                                   or ls._is_recent(m.get("latest_date", ""))):
                continue
            score, tier, signals = ls.final_score(m, cls)
            score_cut = 40 if relax >= 2 else 45   # slightly deeper pool at relax 2
            if score < score_cut:  # drop Tier 3
                continue
            qualified.append({
                "investor_name": m["firm"],
                "investor_type": cls.get("type", "") or "VC",
                "invested_company": next(iter(m["portfolio_cos"]), "") or "—",
                "sector": ", ".join(sorted(m["sector_hints"]))[:200],
                "deal_date": m["latest_date"],
                "signal_date": m["latest_date"],
                "source_url": (m["source_urls"][0] if m["source_urls"] else ""),
                "confidence_score": score,
                "priority_tier": tier,
                "trigger_signals": " ; ".join(dict.fromkeys(signals + m["triggers"][:2])),
                "action_item": ls.action_item(m, cls, score),
                "_classify": cls,
            })

    # ── RANK → top N ──
    qualified.sort(key=lambda d: d["confidence_score"], reverse=True)
    emit("scored", count=len(qualified))
    return qualified[:limit]
