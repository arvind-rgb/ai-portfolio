"""
Bhookle enrichment engine — Gemini-first, with hard anti-guess gates.

Design goals (learnt the hard way):
  • Pick the BEST contact for Bhookle — someone who does D2C / consumer /
    food / early-stage deals — not just any partner.
  • Find a real email through a CASCADE, mirroring how a human searches:
        1. person-specific email (natural-language query, like a Google search)
        2. a personal email (gmail etc.) ONLY if it clearly belongs to that
           person (their name is in the address) — e.g. <firstname><lastname>.work@<personal-provider>
        3. a generic company inbox (info@/contact@) — worst-case but still useful
        4. scrape the firm's own /contact page for a generic inbox
  • Never invent an email: every accepted address must pass accept_email().
  • Verify a company is actually an INVESTOR before it ever becomes a lead.
  • Clean / validate LinkedIn URLs (the source of the wrong-URL bug).

All network calls are best-effort; everything degrades to "" rather than guessing.
"""
import os
import re
import json
import requests
from bs4 import BeautifulSoup

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + GEMINI_MODEL + ":generateContent"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
LI_IN_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+")
LI_CO_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9\-_%]+")

PERSONAL_PROVIDERS = (
    "gmail.com", "yahoo.com", "yahoo.in", "hotmail.com", "outlook.com",
    "icloud.com", "rediffmail.com", "proton.me", "protonmail.com",
)
GENERIC_LOCALPARTS = (
    "info", "contact", "hello", "hi", "team", "connect", "deals", "pitch",
    "pitches", "partnerships", "ir", "invest", "enquiries", "enquiry",
    "inquiries", "reachus", "reach", "office", "mail", "general",
)
# Role inboxes that are NOT a specific person — never accept these as a named
# person's address (but they may serve as a generic fallback).
_ROLE_LOCALPARTS = (
    "media.relations", "media", "pr", "press", "careers", "jobs", "hr",
    "recruiting", "marketing", "support", "help", "sales", "billing",
    "legal", "compliance", "admin", "webmaster", "newsletter",
)
EMAIL_JUNK = (
    "example.com", "yourdomain", "sentry", "wixpress", "no-reply", "noreply",
    "postmaster", "abuse@", "mailer-daemon", "schema.org", "googlemail",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    "@2x", "@3x", "domain.com", "email.com", "test.com",
)
# Template / placeholder local-parts that Gemini sometimes emits to illustrate
# a firm's email format (e.g. "firstname@some-fund.com"). NEVER real — reject.
_PLACEHOLDER_LOCALS = {
    "firstname", "lastname", "first", "last", "name", "fullname", "yourname",
    "first.last", "firstname.lastname", "f.last", "firstinitiallastname",
    "email", "username", "user", "abc", "xyz", "johndoe", "john.doe", "jane.doe",
    "someone", "person", "yourenail", "youremail", "your.email", "sample",
}
# Tokens stripped when computing a firm's "core" name (only if >1 token remains)
_FIRM_STOPWORDS = {
    "ventures", "venture", "capital", "cap", "partners", "partner", "advisors",
    "advisor", "fund", "funds", "group", "associates", "investments",
    "investment", "vc", "pe", "llp", "pvt", "ltd", "the", "india", "global",
    "network", "angels", "angel", "co", "company",
}


# ─────────────────────────────────────────────────────────────────────────────
# Gemini call
# ─────────────────────────────────────────────────────────────────────────────
def _gemini(prompt, timeout=30):
    """Call Gemini 2.5 Flash with Google Search grounding.
    Returns (text, grounded_domains[], grounded_urls[])."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return "", [], []
    try:
        r = requests.post(
            GEMINI_URL + "?key=" + key,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return "", [], []
        data = r.json()
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
        gm = cand.get("groundingMetadata") or {}
        domains, urls = set(), []
        for ch in gm.get("groundingChunks") or []:
            w = ch.get("web") or {}
            uri = w.get("uri") or ""
            if uri:
                urls.append(uri)
            d = (w.get("domain") or "").lower()
            if d.startswith("www."):
                d = d[4:]
            if not d:
                m = re.search(r"([a-z0-9\-]+\.[a-z]{2,})", (w.get("title") or "").lower())
                if m:
                    d = m.group(1)
            if d:
                domains.add(d)
        return text, list(domains), urls
    except Exception:
        return "", [], []


# ─────────────────────────────────────────────────────────────────────────────
# Name / domain matching helpers
# ─────────────────────────────────────────────────────────────────────────────
def firm_core(firm_name):
    """'Alpha Wave Ventures' -> 'alphawave'; 'VentureSouq' -> 'venturesouq'."""
    raw = re.sub(r"[^a-z0-9\s]", " ", (firm_name or "").lower())
    toks = [t for t in raw.split() if t]
    sig = [t for t in toks if t not in _FIRM_STOPWORDS]
    if not sig:                       # all tokens were stopwords (e.g. single word)
        sig = toks
    return "".join(sig)


def name_tokens(person):
    return [t for t in re.sub(r"[^a-z\s]", " ", (person or "").lower()).split() if len(t) >= 3]


def _strip_tld(domain):
    d = domain.lower()
    if d.startswith("www."):
        d = d[4:]
    parts = d.split(".")
    return "".join(parts[:-1]) if len(parts) >= 2 else d


def domain_matches_firm(domain, firm_name):
    """Relaxed: does this email domain plausibly belong to the firm?"""
    stem = re.sub(r"[^a-z0-9]", "", _strip_tld(domain))
    core = firm_core(firm_name)
    if not stem or not core:
        return False
    if stem.startswith(core[:6]) or core.startswith(stem[:6]):
        return True
    # any significant firm token (>=4 chars) appears in the domain stem
    for t in core_tokens(firm_name):
        if len(t) >= 4 and t in stem:
            return True
    return False


def core_tokens(firm_name):
    raw = re.sub(r"[^a-z0-9\s]", " ", (firm_name or "").lower())
    toks = [t for t in raw.split() if t and t not in _FIRM_STOPWORDS]
    return toks or [t for t in raw.split() if t]


def clean_linkedin(url):
    """Trim trailing punctuation / validate it's a real LinkedIn URL."""
    if not url:
        return ""
    url = url.strip().rstrip(".,;)/ ").strip()
    m = LI_IN_RE.match(url) or LI_CO_RE.match(url)
    return m.group(0) if m else (url if "linkedin.com/" in url else "")


# ─────────────────────────────────────────────────────────────────────────────
# Email acceptance — the anti-guess gate
# ─────────────────────────────────────────────────────────────────────────────
def accept_email(email, firm_name, person=None, allow_generic=True):
    """Return a cleaned email if acceptable, else ''. Never guesses."""
    if not email:
        return ""
    el = email.strip().lower().rstrip(".")
    if not EMAIL_RE.fullmatch(el):
        return ""
    if any(j in el for j in EMAIL_JUNK):
        return ""
    if el.count("@") != 1:
        return ""
    local, dom = el.split("@", 1)

    # Reject illustrative template addresses (firstname@, first.last@, …)
    if local in _PLACEHOLDER_LOCALS:
        return ""

    # Personal mailbox provider (gmail etc.) — accept ONLY if it clearly belongs
    # to the named person (their name appears in the local part).
    if any(dom.endswith(p) for p in PERSONAL_PROVIDERS):
        if person:
            lp = re.sub(r"[^a-z0-9]", "", local)
            for t in name_tokens(person):
                if t in lp:
                    return el
        return ""

    # Role inboxes (media@, pr@, careers@…): never a specific person. Allow only
    # as an explicit generic fallback, never when we asked for a named person.
    if local in _ROLE_LOCALPARTS or local.split(".")[0] in _ROLE_LOCALPARTS:
        if allow_generic and not person and domain_matches_firm(dom, firm_name):
            return el
        return ""

    # Generic inbox (info@/contact@…): accept only if domain matches the firm.
    if local in GENERIC_LOCALPARTS:
        if allow_generic and domain_matches_firm(dom, firm_name):
            return el
        return ""

    # Normal corporate address: accept if its domain matches the firm.
    if domain_matches_firm(dom, firm_name):
        return el
    return ""


def _all_emails(text):
    out, seen = [], set()
    for e in EMAIL_RE.findall(text or ""):
        el = e.strip().lower().rstrip(".")
        if el not in seen:
            seen.add(el)
            out.append(el)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 1. Company verification — is this actually an investor?
# ─────────────────────────────────────────────────────────────────────────────
def verify_investor(firm_name):
    """Return {is_investor, type, invests_consumer, reason}. Strict."""
    prompt = (
        f'Is "{firm_name}" PRIMARILY an investment firm — i.e. its main business '
        "is deploying capital into startups as a VC, PE fund, angel network, "
        "family office, or accelerator? Use Google Search to check.\n\n"
        "Return ONLY this JSON:\n"
        '{"is_investor": true/false, "type": "VC|PE|Angel|Angel Network|'
        'Family Office|Accelerator|Corporate VC|", '
        '"invests_consumer": true/false, "reason": "one short sentence"}\n\n'
        "Be STRICT. Set is_investor=false for:\n"
        "- operating companies that merely make occasional strategic investments "
        "(e.g. a food-delivery, e-commerce, or SaaS company) — their primary "
        "business is NOT investing;\n"
        "- pure lenders / NBFCs / banks / venture-debt providers;\n"
        "- farming, manufacturing, consultancies, law firms, service businesses.\n"
        "Only set type='Corporate VC' if the company runs a DEDICATED, named "
        "venture fund/arm whose job is equity investing. When unsure → false."
    )
    text, _, _ = _gemini(prompt)
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return {"is_investor": False, "type": "", "invests_consumer": False,
                "reason": "no response"}
    try:
        d = json.loads(m.group())
        return {
            "is_investor": bool(d.get("is_investor")),
            "type": (d.get("type") or "").strip(),
            "invests_consumer": bool(d.get("invests_consumer")),
            "reason": (d.get("reason") or "").strip(),
        }
    except Exception:
        return {"is_investor": False, "type": "", "invests_consumer": False,
                "reason": "parse error"}


# Domains whose reporting we treat as citable evidence of a real investment.
CREDIBLE_EVIDENCE_DOMAINS = (
    "entrackr.com", "inc42.com", "yourstory.com", "techcrunch.com", "livemint.com",
    "economictimes.indiatimes.com", "business-standard.com", "moneycontrol.com",
    "vccircle.com", "tracxn.com", "crunchbase.com", "indianretailer.com",
    "financialexpress.com", "forbesindia.com", "startupstorymedia.com",
    "indianstartupnews.com", "ipocentral.in", "medial.app", "snackfax.com",
    "entrepreneur.com", "cnbctv18.com", "thehindubusinessline.com", "afaqs.com",
    "storyboard18.com", "siliconindia.com", "dealstreetasia.com", "pitchbook.com",
    "thewire.in", "thehindu.com", "indianexpress.com", "timesofindia.indiatimes.com",
    "ndtv.com", "news18.com", "hindustantimes.com", "theprint.in", "scroll.in",
    "business-today.in", "businesstoday.in", "fortuneindia.com", "outlookbusiness.com",
    "vcbay.news", "startuppedia.in", "techstory.in", "cbinsights.com", "dealroom.co",
    "startupindia.gov.in", "prnewswire.com", "businesswire.com", "zeebiz.com",
    "financialexpress.com", "morningcontext.com", "bwdisrupt.com", "bweducation.com",
)


# Low-value pages that are NOT evidence of a specific deal: SEO listicles,
# "top N angel investors" roundups, directories and content farms. A domain
# allowlist proved too brittle (grounding cites a different outlet each run, and
# legitimate ones like PTI kept getting rejected), so we deny junk instead.
JUNK_EVIDENCE_PATTERNS = (
    "/top-", "top-angel", "best-angel", "/listicle", "list-of-", "/directory",
    "angel-investors-in-india", "top-investors", "/tag/", "/category/",
    "quora.com", "reddit.com", "medium.com/@", "linkedin.com/pulse",
    "facebook.com", "instagram.com", "youtube.com", "pinterest.",
    "wikipedia.org", "slideshare", "scribd", "coursehero",
)


def _is_credible(url):
    """Is this URL usable as evidence of a specific investment?

    Credible = a resolvable article URL that is NOT an SEO listicle/directory.
    Known news/database domains additionally count as high confidence.
    """
    u = (url or "").lower()
    if not u.startswith("http"):
        return False
    if any(p in u for p in JUNK_EVIDENCE_PATTERNS):
        return False
    if any(d in u for d in CREDIBLE_EVIDENCE_DOMAINS):
        return True
    # Unknown-but-real outlet: require an article-shaped path (not a bare
    # homepage), which filters out generic landing/aggregator pages.
    from urllib.parse import urlparse
    p = urlparse(u)
    return bool(p.netloc) and len(p.path.strip("/")) > 12


def _resolve_grounding_url(url, timeout=8):
    """Gemini cites sources as opaque vertexaisearch grounding-redirect links.
    Follow the redirect to recover the REAL publisher URL, so evidence is both
    credibility-checkable and clickable by the founder. Returns '' on failure."""
    u = (url or "").strip()
    if not u:
        return ""
    if "vertexaisearch" not in u and "grounding-api-redirect" not in u:
        return u                       # already a real URL
    try:
        r = requests.get(u, headers=HEADERS, timeout=timeout, allow_redirects=True)
        final = r.url or ""
        return "" if "vertexaisearch" in final else final
    except Exception:
        return ""


def verify_lead_evidence(investor_name, portfolio_co=""):
    """HARD verification gate — the anti-hallucination core of lead sourcing.

    Proves, with a citable source, that `investor_name` really invested in
    `portfolio_co`, AND that the company is genuinely consumer / D2C / food.
    This is what kills the two failure modes that wasted the founder's time:
      • invented investments (a cybersecurity firm labelled a 'food thesis match')
      • investors who don't actually exist / can't be tied to any real deal

    Returns:
      {verified, evidence_url, evidence_note, company_sector, is_consumer_food,
       investor_role, reason}
    Defaults to verified=False on ANY doubt — an unverified lead never ships.
    """
    if not investor_name:
        return {"verified": False, "reason": "no investor name", "evidence_url": "",
                "evidence_note": "", "company_sector": "", "is_consumer_food": False,
                "investor_role": ""}

    co = (portfolio_co or "").strip().strip("—-")
    subject = (f'the investment by "{investor_name}" in the startup "{co}"' if co
               else f'a recent startup investment made by "{investor_name}"')
    prompt = (
        f"Using Google Search, verify {subject}.\n\n"
        "I need to confirm this is a REAL, REPORTED investment before contacting them. "
        "Search for news coverage or a funding database entry that names BOTH the "
        "investor and the startup.\n\n"
        "Also determine what sector the startup ACTUALLY operates in — do not assume.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "verified": true/false,        // a real source names this investor in this deal\n'
        '  "evidence_url": "the single best source URL, or empty",\n'
        '  "evidence_note": "one factual sentence: who invested in what, which round, when",\n'
        '  "company_sector": "the startup\'s ACTUAL sector, e.g. cybersecurity / D2C food / fintech",\n'
        '  "is_consumer_food": true/false,  // is that sector consumer, D2C, food, FMCG or retail?\n'
        '  "investor_role": "how they invested, e.g. led the seed round / angel participant",\n'
        '  "reason": "one short sentence"\n'
        "}\n\n"
        "CRITICAL RULES:\n"
        "- Set verified=false if you cannot find a source that names this specific "
        "investor. Do NOT infer from the investor merely being 'active' or 'well known'.\n"
        "- Do NOT substitute a similarly-named investor or a different company.\n"
        "- company_sector must be the company's REAL business. If the startup is "
        "cybersecurity/SaaS/deeptech, say so plainly and set is_consumer_food=false, "
        "even if you were told otherwise.\n"
        "- When unsure → verified=false. A false negative is fine; a false positive "
        "wastes a founder's time."
    )
    text, _domains, urls = _gemini(prompt, timeout=40)
    m = re.search(r"\{[\s\S]*\}", text or "")
    fail = {"verified": False, "evidence_url": "", "evidence_note": "",
            "company_sector": "", "is_consumer_food": False, "investor_role": "",
            "reason": "no/unparseable response"}
    if not m:
        return fail
    try:
        d = json.loads(m.group())
    except Exception:
        return fail

    claimed = bool(d.get("verified"))
    ev_url = (d.get("evidence_url") or "").strip()
    note = (d.get("evidence_note") or "").strip()

    # ── Anti-hallucination gates ──
    # 1. The model must claim verification AND give a note.
    if not (claimed and note):
        return {**fail, "reason": (d.get("reason") or "not verified by source")}
    # 2. There must be REAL grounding evidence behind the answer. Gemini cites
    #    sources as opaque redirects, so resolve them to real publisher URLs and
    #    require at least one from a credible outlet.
    citable = ""
    for cand in [ev_url] + list(urls or [])[:4]:
        real = _resolve_grounding_url(cand)
        if real and _is_credible(real):
            citable = real
            break
        if real and not citable:
            citable = real            # keep a resolved URL as a weaker fallback
    if not citable:
        return {**fail, "reason": "no source URL could be resolved"}
    if not _is_credible(citable):
        return {**fail, "reason": f"source not from a recognised outlet ({citable[:60]})"}
    # 3. The evidence sentence must actually name the investor (guards the
    #    'asked about X, got a story about Y' substitution failure).
    if not _hook_names_firm(note, investor_name):
        return {**fail, "reason": "evidence does not name this investor"}

    # 4. Decide consumer/food fit from the REPORTED SECTOR TEXT, not the model's
    #    boolean — it flip-flops (it called D2C lingerie "not consumer"). The
    #    sector string it extracts is reliable; the judgement on it is not.
    sector_txt = (d.get("company_sector") or "").strip()
    blob = (sector_txt + " " + note).lower()
    CONSUMER_WORDS = (
        "consumer", "d2c", "dtc", "direct-to-consumer", "retail", "fmcg", "cpg",
        "food", "beverage", "snack", "nutrition", "wellness", "grocery", "qsr",
        "restaurant", "kitchen", "cafe", "apparel", "fashion", "beauty",
        "personal care", "lifestyle", "brand", "e-commerce", "ecommerce",
        # consumer categories that aren't food but are the same buyer/GTM motion
        "jewelry", "jewellery", "marketplace", "footwear", "home care", "skincare",
        "cosmetics", "toys", "furniture", "pet", "baby", "innerwear", "wearable",
        "supplement", "protein", "coffee", "tea", "dairy", "bakery", "confection",
    )
    NON_CONSUMER_WORDS = ("cybersecurity", "saas", "b2b software", "deeptech",
                          "semiconductor", "defence", "defense", "enterprise software")
    is_cf = bool(d.get("is_consumer_food")) or any(w in blob for w in CONSUMER_WORDS)
    if any(w in blob for w in NON_CONSUMER_WORDS) and not any(
            w in blob for w in ("food", "consumer", "d2c", "retail", "fmcg")):
        is_cf = False

    return {
        "verified": True,
        "evidence_url": citable,
        "evidence_note": note[:400],
        "company_sector": sector_txt,
        "is_consumer_food": is_cf,
        "investor_role": (d.get("investor_role") or "").strip(),
        "reason": (d.get("reason") or "").strip(),
    }


def _hook_names_firm(hook, firm_name):
    """True only if the hook text plausibly refers to THIS firm — a significant
    token (>=4 chars) of the firm name must appear in the hook. Guards against a
    misattributed development (e.g. asked 'Firm A Ventures', got 'Firm B Capital')."""
    hl = re.sub(r"[^a-z0-9]", "", (hook or "").lower())
    if not hl:
        return False
    sig = [re.sub(r"[^a-z0-9]", "", t) for t in core_tokens(firm_name)]
    sig = [t for t in sig if len(t) >= 4]
    if not sig:                       # short / stopword-only name → require the whole name
        full = re.sub(r"[^a-z0-9]", "", (firm_name or "").lower())
        return bool(full) and full in hl
    return any(t in hl for t in sig)


def recent_news_hook(firm_name):
    """One recent (~last 9 months), specific, VERIFIABLE development about this
    investor or their fund, usable as an outreach hook (new fund close, notable
    new investment, public thesis statement, award, expansion). Google-grounded;
    returns '' unless the model is confident AND there's grounding evidence.
    Anti-guess: no evidence URLs → no hook."""
    prompt = (
        f'Using Google Search, find ONE recent (last ~9 months), specific, verifiable '
        f'development about the investor named EXACTLY "{firm_name}" or its fund — e.g. a '
        f'new fund close, a notable new portfolio investment, a public statement of thesis, '
        f'an award, or an expansion. It must be factual, recent, and about THIS EXACT firm.\n\n'
        f'CRITICAL: If you cannot find a development about "{firm_name}" itself, return an '
        f'EMPTY hook. Do NOT substitute news about a similarly-named or different company — '
        f'that is worse than no hook. The hook sentence MUST name "{firm_name}".\n\n'
        'Return ONLY JSON: {"hook":"one factual sentence that names the firm, or empty '
        'string","confident":true/false}.'
    )
    # Keep the full grounding time — never trade hook quality for speed. The review
    # flow hides this latency by drafting leads in parallel ahead of your review,
    # so a slow lookup finishes in its own lane instead of blocking you.
    text, _domains, urls = _gemini(prompt)
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return ""
    try:
        d = json.loads(m.group())
        hook = (d.get("hook") or "").strip()
        # Anti-guess: require confidence + grounding evidence AND that the hook is
        # actually ABOUT this firm (a significant token of the name appears in it).
        # This rejects the "asked for Firm A Ventures, got Firm B Capital" failure.
        if d.get("confident") and hook and urls and _hook_names_firm(hook, firm_name):
            return hook
    except Exception:
        pass
    return ""


def classify_investor(firm_name):
    """Richer one-call classification for the getLeads scorer. Returns:
       {is_investor, type, stage_focus[], sector_tags[], geo_india,
        invests_consumer_food, check_size_band, recent_activity, reason}
    All Google-grounded. Defaults are conservative (gate-out) on failure."""
    prompt = (
        f'Classify the Indian-market investor "{firm_name}" for a SEED-stage '
        "D2C/food-tech startup. Use Google Search.\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "is_investor": true/false,            // primary business is investing in startups\n'
        '  "type": "VC|PE|Angel|Angel Network|Family Office|Accelerator|Corporate VC|Micro-VC|Solo GP|Syndicate|",\n'
        '  "stage_focus": ["pre-seed","seed","series-a","growth","late"],  // stages they write checks at\n'
        '  "sector_tags": ["consumer","d2c","foodtech","fintech",...],      // their focus sectors\n'
        '  "geo_india": true/false,             // actively invests in India\n'
        '  "invests_consumer_food": true/false, // backs consumer / D2C / food / FMCG\n'
        '  "check_size_band": "<$500K|$500K-2M|$2-10M|>$10M|",\n'
        '  "writes_first_cheque": true/false,   // writes the FIRST external cheque (angel / pre-seed / first money in), NOT only follow-on or later rounds\n'
        '  "is_marquee": true/false,            // celebrity/Shark-Tank/unicorn-founder angel, OR a top-brand oversubscribed fund flooded with warm inbound — a COLD outreach realistically won\'t convert\n'
        '  "recent_activity": true/false,       // visibly active in the last ~12 months\n'
        '  "reason": "one short sentence"\n'
        "}\n\n"
        "Set writes_first_cheque=true ONLY for investors who lead or join the very "
        "first round — angels, angel networks, syndicates, solo GPs, scouts, and "
        "pre-seed/seed micro-funds that are the first institutional money in. Set it "
        "false for funds that only come in at Series A+ or as follow-on/growth capital.\n\n"
        "Set is_marquee=true for household-name celebrity investors, Shark-Tank judges, "
        "unicorn founders investing as angels, and partners at top-brand funds "
        "(the household-name, heavily-oversubscribed funds) — people so flooded with warm intros that a cold pitch is ignored. "
        "Set false for lesser-known, reachable micro-VCs, solo GPs, syndicates and HNIs.\n\n"
        "Be STRICT on is_investor=false: operating companies, lenders/NBFCs/banks, "
        "venture-debt, farming, manufacturing, consultancies, services. When unsure → false."
    )
    text, _, _ = _gemini(prompt)
    m = re.search(r"\{[\s\S]*\}", text or "")
    fallback = {"is_investor": False, "type": "", "stage_focus": [], "sector_tags": [],
                "geo_india": False, "invests_consumer_food": False,
                "check_size_band": "", "writes_first_cheque": False,
                "is_marquee": False, "recent_activity": False, "reason": "no/parse error"}
    if not m:
        return fallback
    try:
        d = json.loads(m.group())
        return {
            "is_investor": bool(d.get("is_investor")),
            "type": (d.get("type") or "").strip(),
            "stage_focus": [str(s).lower().strip() for s in (d.get("stage_focus") or [])],
            "sector_tags": [str(s).lower().strip() for s in (d.get("sector_tags") or [])],
            "geo_india": bool(d.get("geo_india")),
            "invests_consumer_food": bool(d.get("invests_consumer_food")),
            "check_size_band": (d.get("check_size_band") or "").strip(),
            "writes_first_cheque": bool(d.get("writes_first_cheque")),
            "is_marquee": bool(d.get("is_marquee")),
            "recent_activity": bool(d.get("recent_activity")),
            "reason": (d.get("reason") or "").strip(),
        }
    except Exception:
        return fallback


# ─────────────────────────────────────────────────────────────────────────────
# 2. Best-contact discovery (D2C / consumer / early-stage fit)
# ─────────────────────────────────────────────────────────────────────────────
def best_contacts(firm_name, max_n=2):
    """Identify the best 1-2 people to pitch Bhookle to at this firm."""
    prompt = (
        "I am the founder of Bhookle, an Indian D2C / food-tech / cloud-kitchen "
        f"startup raising early-stage capital. At the investment firm \"{firm_name}\", "
        f"identify the {max_n} BEST people for me to contact.\n\n"
        "Strongly PREFER people who focus on: consumer, D2C, food / F&B, FMCG, "
        "retail, or early-stage / seed deals. Prefer Partners, Principals, "
        "Founders, or Investment Leads — not analysts or back-office staff.\n\n"
        "Use Google Search. Return ONLY a JSON array (most relevant first):\n"
        '[{"name": "Full Name", "title": "their role", '
        '"linkedin": "https://linkedin.com/in/handle or empty"}]\n\n'
        "Only real, currently-employed people. If you cannot confidently identify "
        "anyone, return []."
    )
    text, _, _ = _gemini(prompt)
    m = re.search(r"\[[\s\S]*\]", text or "")
    if not m:
        return []
    try:
        arr = json.loads(m.group())
    except Exception:
        return []
    out = []
    for c in arr if isinstance(arr, list) else []:
        if not isinstance(c, dict):
            continue
        nm = (c.get("name") or "").strip()
        if not nm or len(nm) > 60:
            continue
        out.append({
            "name": nm,
            "title": (c.get("title") or "").strip(),
            "linkedin": clean_linkedin(c.get("linkedin") or ""),
        })
        if len(out) >= max_n:
            break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Email cascade
# ─────────────────────────────────────────────────────────────────────────────
def _li_slug_matches_person(url, person):
    """True if a /in/<slug> URL plausibly belongs to `person` (name overlap)."""
    m = re.search(r"/in/([A-Za-z0-9\-_%]+)", url or "")
    if not m:
        return False
    slug = m.group(1).lower().replace("-", "").replace("_", "")
    toks = name_tokens(person)
    if not toks:
        return False
    hits = sum(1 for t in toks if t in slug)
    # require the first name (or at least one token) to appear in the slug
    return hits >= 1


def find_linkedin_profile(person, firm_name, browser):
    """Find a person's LinkedIn /in/ profile URL via headless Google — the same
    1-second lookup a human does ('jatin desai inflexor'). Validates the slug
    against the person's name so we don't grab the wrong individual.
    Returns a clean URL or ''."""
    if browser is None or not person:
        return ""
    # NOTE: LinkedIn hard-blocks automated /search/ access (redirect loop) even
    # with a valid li_at cookie — do NOT try to search LinkedIn from here. The
    # compose flow instead opens a precise name+company search in the user's own
    # logged-in browser. Below: Google result hrefs (may be bot-limited).
    for q in (f"{person} {firm_name} linkedin",
              f"{person} {firm_name} linkedin profile"):
        html = browser.search_html(q)
        if not html:
            continue
        # collect candidate /in/ URLs from result hrefs
        cands = []
        for m in LI_IN_RE.finditer(html):
            u = clean_linkedin(m.group(0))
            if u and u not in cands:
                cands.append(u)
        # prefer one whose slug matches the person's name
        for u in cands:
            if _li_slug_matches_person(u, person):
                return u
        # otherwise take the first /in/ result (Google ranks the right one top)
        if cands:
            return cands[0]
    return ""


def find_company_linkedin(firm_name, browser):
    """Find a firm's LinkedIn /company/ URL via headless Google. Returns '' if none."""
    if browser is None:
        return ""
    html = browser.search_html(f"{firm_name} linkedin company page")
    for m in LI_CO_RE.finditer(html or ""):
        u = clean_linkedin(m.group(0))
        if u:
            return u
    return ""


def email_for_person(person, firm_name, browser=None, linkedin_url=None,
                      allow_auth_li=False):
    """Cascade for one person's real email (corporate or name-matched personal):
        1. Gemini API grounding (fast, cheap)
        2. Headless Google AI Overview  (browser; high recall — reads LinkedIn
           About/Contact-info indirectly via Google, no direct LinkedIn hit)
        3. Authenticated LinkedIn About + Contact-info  (ON-DEMAND only:
           allow_auth_li=True, gentle/throttled — never in bulk loops)
    Returns '' if nothing passes the anti-guess gate."""
    first = (person.split()[0] if person else "").strip(".")

    # 1. Gemini API
    for q in (
        f"whats the email of {person} {firm_name}",
        f"What is the email address of {person} from {firm_name}?",
        f"{person} {firm_name} email contact linkedin about section",
    ):
        text, _, _ = _gemini(q)
        for e in _all_emails(text):
            ok = accept_email(e, firm_name, person=person, allow_generic=False)
            if ok:
                return ok

    # 2. Headless Google AI Overview (safe — does not touch LinkedIn directly)
    if browser is not None:
        for q in (
            f"whats the email of {person} {firm_name}",
            f"email address of {first} {firm_name} linkedin contact info",
        ):
            txt = browser.search_text(q)
            for e in _all_emails(txt):
                ok = accept_email(e, firm_name, person=person, allow_generic=False)
                if ok:
                    return ok

    # 3. Authenticated LinkedIn — ON-DEMAND only, last resort
    if allow_auth_li and browser is not None and linkedin_url:
        try:
            for e in browser.linkedin_emails(linkedin_url, person=person):
                ok = accept_email(e, firm_name, person=person, allow_generic=False)
                if ok:
                    return ok
        except Exception:
            pass

    return ""


def generic_email(firm_name, browser=None):
    """Worst-case: a generic company inbox — firm website, then Google/Gemini."""
    # scrape the firm's own contact/about pages
    core = firm_core(firm_name)
    roots = [f"https://www.{core}.com", f"https://www.{core}.in",
             f"https://{core}.vc", f"https://www.{core}.co",
             f"https://www.{core}vc.com", f"https://www.{core}capital.com"]
    for root in roots:
        for path in ("/contact", "/contact-us", "/about", ""):
            try:
                r = requests.get(root + path, headers=HEADERS, timeout=5)
                if r.status_code == 200 and len(r.text) > 300:
                    for e in _all_emails(r.text):
                        if e.split("@", 1)[0] in GENERIC_LOCALPARTS:
                            ok = accept_email(e, firm_name, allow_generic=True)
                            if ok:
                                return ok
            except Exception:
                pass
    # headless Google
    if browser is not None:
        txt = browser.search_text(f"{firm_name} contact email info")
        for e in _all_emails(txt):
            if e.split("@", 1)[0] in GENERIC_LOCALPARTS:
                ok = accept_email(e, firm_name, allow_generic=True)
                if ok:
                    return ok
    # Gemini
    for q in (
        f"What is the general contact or info email address of {firm_name}?",
        f"{firm_name} contact us email info@",
    ):
        text, _, _ = _gemini(q)
        for e in _all_emails(text):
            ok = accept_email(e, firm_name, allow_generic=True)
            if ok:
                return ok
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 4. Top-level: enrich one firm into ready-to-save contact data
# ─────────────────────────────────────────────────────────────────────────────
_FIRM_SUFFIX_HINTS = (
    "ventures", "venture", "capital", "partners", "fund", "funds", "advisors",
    "associates", "syndicate", "network", "angels", "llp", "holdings", "group",
    "company", "collective", "management", "ventures.", "vc", "pe",
)


def looks_like_individual(name, investor_type=""):
    """Heuristic: is this candidate a PERSON (individual angel/HNI) rather than a
    firm? People need person-mode enrichment (find THEIR profile), not firm-mode
    (find people AT the firm). True for 2-3 word names with no firm suffix."""
    n = (name or "").strip()
    if not n:
        return False
    low = n.lower()
    if any(s in low.split() or s in low for s in _FIRM_SUFFIX_HINTS):
        return False
    words = [w for w in re.split(r"\s+", n) if w]
    if not (2 <= len(words) <= 3):
        return False
    # a name of capitalised words that isn't a firm → treat as a person
    itype = (investor_type or "").lower()
    if itype in ("vc", "pe", "family office", "accelerator", "angel network",
                 "corporate vc", "micro-vc", "syndicate"):
        return False
    return True


def enrich_person(name, browser=None, allow_auth_li=False, context=""):
    """Person-mode enrichment: lock an INDIVIDUAL angel/HNI's own LinkedIn /in/
    profile from REAL results (authenticated LinkedIn search when available; never
    a fabricated URL), plus an email if findable. `context` (a portfolio company or
    firm) sharpens the search to the PRECISE person — 'Emmanuel Suraj Krvvy' beats
    'Emmanuel Suraj'. The lead is still usable on the verified name alone.
    Returns the same shape as smart_enrich."""
    ctx = (context or "").strip()
    if ctx in ("", "—", "-") or "bhookle" in ctx.lower():
        ctx = "angel investor India"
    li = ""
    if browser is not None:
        li = find_linkedin_profile(name, ctx, browser)
    li = clean_linkedin(li)
    em = email_for_person(name, "", browser=browser, linkedin_url=li,
                          allow_auth_li=allow_auth_li)
    contacts = [{"name": name, "email": em, "linkedin": li}]
    return {
        "contacts": contacts,
        "used_team": False,
        "any_email": bool(em),
        "any_contact": bool(li or em),
    }


_DECISION_ROLE_HINTS = ("partner", "principal", "founder", "managing", "general partner",
                        "gp", "director", "investor", "vice president", "vp", "head")
_CONSUMER_ROLE_HINTS = ("consumer", "d2c", "food", "brand", "retail", "cpg", "fmcg")


def contacts_from_company_page(firm_name, browser):
    """Find the right person the way a human does — open the firm's LinkedIn
    COMPANY page, read its People tab, and pick decision-makers (partners /
    founders / principals), preferring anyone whose headline mentions consumer
    or food. Returns [{name, title, linkedin}] with REAL profile URLs.

    This is the authoritative source for 'who works here', so it runs BEFORE any
    name-based guessing.
    """
    if browser is None or not getattr(browser, "has_linkedin_auth", False):
        return []
    people = []
    for kw in ("partner", ""):          # try a filtered pass, then unfiltered
        people = browser.linkedin_company_people(firm_name, keywords=kw) or []
        if people:
            break
    if not people:
        return []

    def rank(p):
        h = (p.get("headline") or "").lower()
        score = 0
        if any(k in h for k in _CONSUMER_ROLE_HINTS):
            score -= 2                   # consumer/food focus wins
        if any(k in h for k in _DECISION_ROLE_HINTS):
            score -= 1                   # decision-maker beats analyst
        return score

    out = []
    for p in sorted(people, key=rank):
        if not p.get("name") or not p.get("url"):
            continue
        out.append({"name": p["name"], "title": p.get("headline", ""),
                    "linkedin": clean_linkedin(p["url"])})
    return out


def smart_enrich(firm_name, want=2, browser=None, allow_auth_li=False):
    """Full pipeline for one firm.
    Pass a GoogleBrowser via `browser` to enable the headless-Google tier.
    Set allow_auth_li=True ONLY for single on-demand enrichment (uses
    authenticated LinkedIn as a last resort).

    Returns:
      {contacts: [{name,email,linkedin}], used_team, any_email, any_contact}
    """
    # Tier 0: the firm's own LinkedIn People tab — authoritative on who works
    # there, and it yields REAL profile URLs. Only falls through to LLM-suggested
    # names when the company page gives us nothing.
    page_people = contacts_from_company_page(firm_name, browser)
    if page_people:
        results = [{"name": p["name"], "email": "", "linkedin": p["linkedin"],
                    "title": p.get("title", "")} for p in page_people[:want]]
        for r in results:
            r["email"] = email_for_person(r["name"], firm_name, browser=browser,
                                          linkedin_url=r["linkedin"],
                                          allow_auth_li=allow_auth_li)
        any_email = any(r["email"] for r in results)
        if not any_email:
            g = generic_email(firm_name, browser=browser)
            if g:
                results[0]["email"] = g
                any_email = True
        return {"contacts": results, "used_team": False, "any_email": any_email,
                "any_contact": True}

    contacts = best_contacts(firm_name, max_n=want)
    results = []
    for c in contacts:
        # 1. LOCK the LinkedIn profile first (Google-verified beats Gemini's
        #    guess — fixes the wrong-URL bug AND helps the email lookup).
        li = c.get("linkedin") or ""
        if browser is not None:
            google_li = find_linkedin_profile(c["name"], firm_name, browser)
            # prefer a name-matched Google result; fall back to Gemini's value
            if google_li and _li_slug_matches_person(google_li, c["name"]):
                li = google_li
            elif not li and google_li:
                li = google_li
        li = clean_linkedin(li)

        # 2. Now find the email, handing the locked LinkedIn to the auth tier.
        em = email_for_person(c["name"], firm_name, browser=browser,
                              linkedin_url=li, allow_auth_li=allow_auth_li)
        results.append({"name": c["name"], "email": em, "linkedin": li})

    any_email = any(r["email"] for r in results)
    used_team = False

    # No personal email → generic company inbox (worst-case, still actionable).
    if not any_email:
        g = generic_email(firm_name, browser=browser)
        if g:
            if results:
                results[0]["email"] = g
            else:
                co_li = find_company_linkedin(firm_name, browser) if browser else ""
                results = [{"name": "Team", "email": g, "linkedin": co_li}]
                used_team = True
            any_email = True

    any_contact = any((r["name"] or r["email"] or r["linkedin"]) for r in results)
    return {
        "contacts": results,
        "used_team": used_team,
        "any_email": any_email,
        "any_contact": any_contact,
    }
