"""
Scrapes Indian food-tech funding news from public sources, then uses Claude
to extract structured investment-lead data.
"""

import os
import json
import time
import requests
from bs4 import BeautifulSoup
import anthropic

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

NEWS_SOURCES = [
    {
        "name": "YourStory FoodTech",
        "url": "https://yourstory.com/search?q=foodtech+funding+india",
        "selector": "article, .story-card, .post-card",
    },
    {
        "name": "Entrackr",
        "url": "https://entrackr.com/category/funding/",
        "selector": "article, .post",
    },
    {
        "name": "Inc42 FoodTech",
        "url": "https://inc42.com/buzz/?s=foodtech+funding",
        "selector": "article, .inc42-post-card",
    },
    {
        "name": "Economic Times Startups",
        "url": "https://economictimes.indiatimes.com/small-biz/startups/newsbuzz?q=food+tech+startup+funding",
        "selector": ".eachStory, article",
    },
]

# Public-repo note: the original seed list named real investors. It has been
# replaced with fictional placeholders; run seed_demo.py for a full demo DB.
SEED_DATA = [
    {
        "investor_name": "Example Seed Partners",
        "investor_type": "Micro VC",
        "invested_company": "Demo Tiffin Co",
        "investment_amount": "$1M",
        "round_type": "Seed",
        "sector": "Home Food",
        "deal_date": "2026-Q1",
        "key_contact": "Jane Placeholder",
        "email": "jane@example.com",
        "linkedin": "https://www.linkedin.com/in/example-jane-placeholder/",
        "source_url": "https://example.com/news/demo-tiffin-seed",
    },
]


def fetch_page(url: str, timeout: int = 10):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"[scraper] Failed to fetch {url}: {e}")
        return None


def extract_article_text(html: str, selector: str):
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(selector)[:10]
    texts = []
    for item in items:
        text = item.get_text(separator=" ", strip=True)
        if len(text) > 100:
            texts.append(text[:2000])
    return texts


def parse_with_claude(articles, source: str):
    """Use Claude to extract structured investment data from raw article text."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[scraper] ANTHROPIC_API_KEY not set — skipping LLM extraction")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    combined = "\n\n---\n\n".join(articles[:5])

    prompt = f"""You are an investment research analyst. Extract food-tech funding deals in India from the following news snippets.

Return a JSON array of objects. Each object must have exactly these keys:
- investor_name: Name of VC/PE/Angel firm or person
- investor_type: one of "VC", "PE", "Angel", "Angel Network", "Family Office", "Corporate VC"
- invested_company: startup that received funding
- investment_amount: e.g. "$10M" or "₹50 Cr" — use "Undisclosed" if not mentioned
- round_type: e.g. "Seed", "Series A", "Series B", "Pre-IPO" etc.
- sector: food-tech sub-sector e.g. "Cloud Kitchen", "Food Delivery", "Agritech", "D2C Snacks"
- deal_date: approximate date or quarter e.g. "2025-Q1" or "Jan 2025"
- key_contact: most senior/relevant person at the investor firm mentioned
- email: their email if mentioned, otherwise ""
- linkedin: their LinkedIn URL if inferrable, otherwise ""
- source_url: leave as "{source}"

Source: {source}

News snippets:
{combined}

Return only valid JSON array, no markdown fences."""

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        print(f"[scraper] Claude extraction error: {e}")
        return []


EXTRA_SEARCH_URLS = [
    "https://entrackr.com/category/funding/",
    "https://inc42.com/tag/funding/",
    "https://yourstory.com/tag/funding",
]

# Public-repo note: real fallback leads replaced with a fictional placeholder.
FALLBACK_LEADS = [
    {"investor_name": "Sample Angel Collective", "investor_type": "Angel Network",
     "invested_company": "Demo Snacks", "investment_amount": "₹2Cr", "round_type": "Seed",
     "sector": "D2C Snacks", "deal_date": "2026-Q1", "key_contact": "John Placeholder",
     "email": "", "linkedin": "https://www.linkedin.com/in/example-john-placeholder/",
     "source_url": "https://example.com/news/demo-snacks"},
]


def scrape_live():
    """Attempt live scraping; always returns minimum 20 leads."""
    all_deals = []
    all_sources = NEWS_SOURCES + [{"url": u, "selector": "article,.post"} for u in EXTRA_SEARCH_URLS]
    for source in all_sources:
        html = fetch_page(source["url"])
        if not html:
            continue
        articles = extract_article_text(html, source.get("selector", "article"))
        if not articles:
            continue
        deals = parse_with_claude(articles, source["url"])
        all_deals.extend(deals)
        time.sleep(0.8)
        if len(all_deals) >= 25:
            break

    # Always pad to at least 20 with curated fallback leads
    existing = {d.get("investor_name", "").lower() for d in all_deals}
    for lead in FALLBACK_LEADS:
        if len(all_deals) >= 20:
            break
        if lead["investor_name"].lower() not in existing:
            all_deals.append(lead)
            existing.add(lead["investor_name"].lower())

    return all_deals[:30]


def fetch_recent_investments(investor_name, api_key):
    """Use Claude to produce a short recent-investments summary for one investor."""
    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": (
                f"You are a knowledgeable Indian startup ecosystem expert. "
                f"List up to 3 known portfolio companies or investments by '{investor_name}' (any sector, India focus). "
                f"Include amount if you know it, otherwise just the company name. "
                f"Format exactly as: 'Company A ($Xm), Company B, Company C (₹Xcr)'. "
                f"If you genuinely have no information about this investor, reply only: Data unavailable. "
                f"No explanations, no caveats, just the comma-separated list or 'Data unavailable'."
            )}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return ""


import re as _re

# Emails / domains that are never a real investor contact — junk to discard.
_EMAIL_JUNK = (
    "example.com", "sentry.io", "wixpress.com", "godaddy.com", "domain.com",
    "yourdomain", "email.com", "test.com", "sentry-next", "wix.com", "schema.org",
    "@2x", "@3x", "react", "babel", "googlemail", "no-reply", "noreply",
    "privacy", "abuse@", "postmaster", "mailer-daemon", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".webp", ".css", ".js", "sentry.wixpress",
)
_EMAIL_RE = _re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LINKEDIN_IN_RE = _re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+")
_LINKEDIN_CO_RE = _re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9\-_%]+")


def _clean_emails(found):
    """Filter a raw set of regex-matched emails down to plausible real contacts."""
    out = []
    seen = set()
    for e in found:
        el = e.strip().lower().rstrip(".")
        if el in seen:
            continue
        if any(j in el for j in _EMAIL_JUNK):
            continue
        # discard things that are clearly not addresses (e.g. tracking pixels)
        if len(el) > 64 or el.count("@") != 1:
            continue
        local, _, dom = el.partition("@")
        if not local or "." not in dom:
            continue
        seen.add(el)
        out.append(el)
    return out


def find_verified_contact(investor_name, investor_type, api_key):
    """
    Crawl the open web + the firm's own site to find a REAL contact for an
    investor. Emails are extracted ONLY via regex from actual page content —
    the LLM is used purely to RANK / associate the discovered data and is never
    allowed to invent an address (enforced in Python after it responds).

    Returns a single dict:
      {name, title, email, linkedin, email_verified, linkedin_verified, sources}
    Any field the crawl could not verify is returned as "".
    """
    def safe_get(url, timeout=6):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            pass
        return ""

    found_emails = []          # real emails scraped from pages
    found_linkedins_in = []    # personal profile URLs
    found_linkedins_co = []    # company URLs
    context_snippets = []      # text for the LLM to reason over
    sources = []               # where we looked / found things
    discovered_domains = []    # firm websites we found via DDG (not slug guesses)
    candidate_names = []       # person names found on directory pages
    page_emails = set()        # emails seen on REAL fetched pages (not Gemini)
    grounded_domains = set()   # domains cited by Gemini search-grounding

    def harvest(html, src, is_real_page=True):
        """Extract emails/linkedins from `html`. If is_real_page=True, the
        emails are treated as verified-from-a-real-page. If False (e.g. Gemini
        synthesized answer), they go in the pool but must later pass a
        domain-grounding check before being accepted."""
        if not html:
            return
        emails_here = _EMAIL_RE.findall(html)
        found_emails.extend(emails_here)
        if is_real_page:
            for e in emails_here:
                page_emails.add(e.strip().lower().rstrip("."))
        found_linkedins_in.extend(_LINKEDIN_IN_RE.findall(html))
        found_linkedins_co.extend(_LINKEDIN_CO_RE.findall(html))

    def parse_result_links(html, limit=4):
        """Extract destination URLs from a Bing or DDG HTML results page."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            urls = []
            # Bing: result links live in <li class="b_algo"> <h2><a href="...">
            for a in soup.select("li.b_algo h2 a, .b_algo h2 a"):
                href = a.get("href", "")
                if href.startswith("http") and "bing.com" not in href and href not in urls:
                    urls.append(href)
                if len(urls) >= limit:
                    break
            # DDG fallback parsing
            if not urls:
                for a in soup.select(".result__url, a.result__a, .result__title a")[: limit * 3]:
                    href = a.get("href", "")
                    m = _re.search(r"uddg=([^&]+)", href)
                    if m:
                        href = requests.utils.unquote(m.group(1))
                    if href.startswith("http") and "duckduckgo" not in href and href not in urls:
                        urls.append(href)
                    if len(urls) >= limit:
                        break
            return urls
        except Exception:
            return []

    def gemini_grounded(query):
        """Ask Gemini with Google Search grounding (= AI Overview behavior).
        Returns (answer_text, grounding_source_urls[]). Empty if not configured / fails."""
        g_key = os.getenv("GEMINI_API_KEY")
        if not g_key:
            return "", []
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "gemini-2.5-flash:generateContent?key=" + g_key)
            payload = {
                "contents": [{"parts": [{"text": query}]}],
                "tools": [{"google_search": {}}],
            }
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code != 200:
                if r.status_code in (403, 429):
                    print(f"[gemini_grounded] quota/auth error {r.status_code}")
                return "", []
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            # answer text
            parts = (cand.get("content") or {}).get("parts") or []
            text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
            # grounding source URLs (real URLs Gemini cited)
            gm = cand.get("groundingMetadata") or {}
            chunks = gm.get("groundingChunks") or []
            src_urls = []
            for ch in chunks:
                w = ch.get("web") or {}
                u = w.get("uri") or ""
                if u and u not in src_urls:
                    src_urls.append(u)
            return text, src_urls
        except Exception as e:
            print(f"[gemini_grounded] error: {e}")
            return "", []

    def web_search(query):
        """Run a web search. Strategy:
           1) Gemini 2.5 Flash + Google Search grounding (if GEMINI_API_KEY set) — AI-Overview-grade
           2) Bing HTML (fallback)
           3) DDG HTML (last resort, often blocks our IP)
        Returns (text_blob, snippets[], result_urls[])."""
        # 1) Gemini with Google Search grounding — preferred when configured
        if os.getenv("GEMINI_API_KEY"):
            ans, src_urls = gemini_grounded(query)
            if ans or src_urls:
                # Treat the Gemini answer itself as a high-signal snippet, and
                # return its cited source URLs as the result links to follow.
                return ans, ([ans] if ans else []), src_urls

        # 2) Bing HTML fallback
        try:
            url = "https://www.bing.com/search?q=" + requests.utils.quote(query)
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200 and len(r.text) > 1000:
                soup = BeautifulSoup(r.text, "html.parser")
                snips = [t.get_text(" ", strip=True)[:300]
                         for t in soup.select("li.b_algo .b_caption p, li.b_algo h2")[:8]]
                urls  = [a.get("href","") for a in soup.select("li.b_algo h2 a")
                         if a.get("href","").startswith("http")]
                return r.text, [s for s in snips if s], urls[:8]
        except Exception:
            pass

        # 3) DDG HTML last resort
        try:
            url = "https://html.duckduckgo.com/html/?q=" + requests.utils.quote(query)
            r = requests.get(url, headers=HEADERS, timeout=6)
            if r.status_code == 200 and r.text:
                soup = BeautifulSoup(r.text, "html.parser")
                snips = [t.get_text(" ", strip=True)[:300]
                         for t in soup.select(".result__body, .result__snippet, .result__title")[:6]]
                return r.text, [s for s in snips if s], []
        except Exception:
            pass

        return "", [], []

    # ── 1. Web search via DuckDuckGo — follow top result links into pages ────
    # Why follow links? DDG snippets alone don't contain full emails — the
    # actual address usually lives ON the destination page (ContactOut,
    # RocketReach, the firm's own /team page, etc). The earlier crawl only
    # scraped DDG snippets and missed partner addresses that live on /team pages.
    firm_queries = [
        f'"{investor_name}" India partner email contact',
        f'"{investor_name}" team linkedin.com/in',
        f'"{investor_name}" contact us email',
        f'"{investor_name}" official website',  # surfaces the real domain
        f'site:indianvcs.com "{investor_name}"',
        f'site:openvc.app "{investor_name}"',
        f'site:ventureintelligence.com "{investor_name}"',
        f'site:crunchbase.com "{investor_name}" people',
        f'site:wellfound.com "{investor_name}"',
        f'site:rocketreach.co "{investor_name}"',
        f'site:contactout.com "{investor_name}"',
        f'site:signalhire.com "{investor_name}"',
    ]
    using_gemini = bool(os.getenv("GEMINI_API_KEY"))
    for q in firm_queries:
        html, snips, urls = web_search(q)
        if not html:
            continue
        # Gemini's response is a synthesized blob — treat as low-trust for email
        # extraction (its domain must later appear in grounded source URLs).
        harvest(html, q, is_real_page=not using_gemini)
        context_snippets.extend(snips)
        # Track grounded domains from Gemini's cited sources
        if using_gemini:
            from urllib.parse import urlparse as _up
            for u in urls:
                try:
                    d = _up(u).netloc.lower().lstrip("www.")
                    if d: grounded_domains.add(d)
                except Exception: pass

        # Use URLs returned by the search API directly; fall back to HTML parse.
        result_links = urls[:2] if urls else parse_result_links(html, limit=2)
        for link in result_links:
            try:
                # remember firm-looking domains we discover (not slug guesses)
                from urllib.parse import urlparse
                host = urlparse(link).netloc.lower().lstrip("www.")
                if host and host not in discovered_domains and not any(
                    x in host for x in ("duckduckgo", "google", "linkedin", "twitter", "facebook")
                ):
                    discovered_domains.append(host)
                page_html = safe_get(link, timeout=6)
                if page_html and len(page_html) > 400:
                    harvest(page_html, link)
                    sources.append(link)
                    try:
                        soup2 = BeautifulSoup(page_html, "html.parser")
                        context_snippets.append(f"[{link}] " + soup2.get_text(" ", strip=True)[:1500])
                    except Exception:
                        pass
            except Exception:
                pass

    # ── 2. India-focused open investor directories (no auth required) ────────
    slug_dash = _re.sub(r"[^a-z0-9]+", "-", investor_name.lower()).strip("-")
    slug_plain = _re.sub(r"[^a-z0-9]", "", investor_name.lower())
    directory_urls = [
        # IndianVCs.com — public firm profile pages
        f"https://www.indianvcs.com/firms/{slug_dash}",
        f"https://www.indianvcs.com/funds/{slug_dash}",
        # OpenVC India — public firm pages (try a couple of common URL shapes)
        f"https://www.openvc.app/profile/{slug_dash}",
        f"https://www.openvc.app/funds/{slug_dash}",
    ]
    for u in directory_urls:
        html = safe_get(u, timeout=6)
        if html and len(html) > 400:
            harvest(html, u)
            sources.append(u)
            try:
                soup = BeautifulSoup(html, "html.parser")
                context_snippets.append(f"[{u}] " + soup.get_text(" ", strip=True)[:1500])
            except Exception:
                pass

    # ── 3. The firm's own website — use REAL discovered domains FIRST,
    #       then fall back to slug guesses if nothing was discovered. ─────────
    slug = slug_plain
    candidate_roots = []
    for host in discovered_domains[:5]:
        candidate_roots.append(f"https://{host}")
    # always also try slug guesses as a fallback (cheap, may hit)
    candidate_roots.extend([
        f"https://www.{slug}.com", f"https://www.{slug}.in",
        f"https://{slug}.vc", f"https://www.{slug}.co",
        f"https://www.{slug}cap.com",        # e.g. examplecap.com
        f"https://www.{slug}advisors.com",   # e.g. exampleadvisors.com
        f"https://www.{slug}capital.com",
        f"https://www.{slug}ventures.com",
    ])
    # de-dupe while preserving order
    seen_roots = set()
    candidate_roots = [r for r in candidate_roots if not (r in seen_roots or seen_roots.add(r))]

    hit_count = 0
    for root in candidate_roots:
        hit = False
        for path in ["", "/contact", "/team", "/people", "/about", "/our-team", "/contact-us"]:
            html = safe_get(root + path, timeout=5)
            if html and len(html) > 400:
                harvest(html, root + path)
                if root not in sources:
                    sources.append(root)
                hit = True
                try:
                    soup = BeautifulSoup(html, "html.parser")
                    context_snippets.append(f"[{root+path}] " + soup.get_text(" ", strip=True)[:1500])
                except Exception:
                    pass
        if hit:
            hit_count += 1
            if hit_count >= 2:  # cover up to 2 real domains (e.g. main + advisors)
                break

    # ── 4. Person-targeted second pass ──────────────────────────────────────
    # After layer 1-3 we usually know one or two candidate people. Ask DDG
    # for THEIR email specifically and follow the result links. This is what
    # a human would do — "find email of <person> at <firm>" — and is the
    # single biggest recall fix.
    cand_people = []
    if found_linkedins_in:
        for li in found_linkedins_in[:3]:
            # extract the slug from /in/<slug> as a poor-man's name
            m = _re.search(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", li)
            if m:
                handle = m.group(1).replace("-", " ").replace("_", " ").title()
                if handle not in cand_people:
                    cand_people.append(handle)
    # also pull "Name Surname" patterns from snippets that mention common titles
    for snip in context_snippets[:25]:
        for m in _re.finditer(r"([A-Z][a-z]+\s+[A-Z][a-z]+)\s*(?:[—,–|·\-])?\s*(?:Managing\s+)?(?:Partner|Principal|Founder|Director|Vice\s+President)", snip):
            n = m.group(1).strip()
            if n not in cand_people and len(cand_people) < 4:
                cand_people.append(n)

    for person in cand_people[:3]:
        person_queries = [
            f'"{person}" "{investor_name}" email',
            f'find email of {person} from {investor_name}',
            f'"{person}" {investor_name} contact',
        ]
        for q in person_queries:
            html, snips, urls = web_search(q)
            if not html:
                continue
            harvest(html, q, is_real_page=not using_gemini)
            for s in snips:
                context_snippets.append(f"[person:{person}] " + s)
            if using_gemini:
                from urllib.parse import urlparse as _up
                for u in urls:
                    try:
                        d = _up(u).netloc.lower().lstrip("www.")
                        if d: grounded_domains.add(d)
                    except Exception: pass
            # follow into the top destination page — this is where people-data
            # sites (RocketReach, ContactOut, Bruker, SignalHire) actually
            # publish the email in the public HTML.
            result_links = urls[:2] if urls else parse_result_links(html, limit=2)
            for link in result_links:
                page_html = safe_get(link, timeout=6)
                if page_html and len(page_html) > 400:
                    harvest(page_html, link)
                    if link not in sources:
                        sources.append(link)
                    try:
                        soup2 = BeautifulSoup(page_html, "html.parser")
                        context_snippets.append(f"[{link}] " + soup2.get_text(" ", strip=True)[:1200])
                    except Exception:
                        pass

    # ── 3. Clean + dedupe the discovered data ────────────────────────────────
    emails = _clean_emails(found_emails)
    # ── No-guess gate: an email is acceptable only if it either (a) appeared
    # on a REAL fetched page, or (b) its domain is in Gemini's cited grounding
    # sources. This blocks Gemini from inventing emails at unrelated domains.
    if grounded_domains or page_emails:
        emails = [
            e for e in emails
            if e in page_emails
            or any(d == e.split("@", 1)[1] or e.split("@", 1)[1].endswith("." + d)
                   for d in grounded_domains)
        ]
    # prefer emails whose domain matches the firm slug (most likely the real firm)
    emails.sort(key=lambda e: 0 if slug[:6] in e.split("@")[1].replace(".", "") else 1)
    linkedins_in = list(dict.fromkeys(found_linkedins_in))
    linkedins_co = list(dict.fromkeys(found_linkedins_co))

    result = {
        "name": "", "title": "", "email": "", "linkedin": "",
        "email_verified": False, "linkedin_verified": False, "sources": sources,
    }

    # If we found nothing at all on the web, give up honestly (no guessing).
    if not emails and not linkedins_in and not linkedins_co:
        return result

    # ── 4. Ask Claude ONLY to associate the discovered data with a person ────
    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""You are helping match real, scraped web data to the best contact at an Indian investment firm.

Firm: "{investor_name}" ({investor_type or 'investment firm'})
Goal: find the best person to contact about a D2C / food-tech startup.

I have ALREADY crawled the web. Use ONLY the data below — do NOT invent anything.

EMAILS found on their pages (pick the most relevant, or "" if none belong to this firm / are a real person or team inbox):
{json.dumps(emails[:15], indent=2) if emails else "(none found)"}

PERSONAL LinkedIn profiles found:
{json.dumps(linkedins_in[:15], indent=2) if linkedins_in else "(none found)"}

COMPANY LinkedIn pages found:
{json.dumps(linkedins_co[:5], indent=2) if linkedins_co else "(none found)"}

Page text snippets (for identifying a name/title):
{chr(10).join(context_snippets)[:3500]}

Return ONLY valid JSON, no other text:
{{
  "name": "person's full name if identifiable from the snippets, else \\"\\"",
  "title": "their role if stated, else \\"\\"",
  "email": "EXACTLY one of the emails listed above, or \\"\\" — never make one up",
  "linkedin": "EXACTLY one of the LinkedIn URLs listed above (prefer a personal /in/ profile, else the /company/ page), or \\"\\""
}}"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        m = _re.search(r"\{[\s\S]*\}", text)
        if m:
            data = json.loads(m.group())
            result["name"] = (data.get("name") or "").strip()
            result["title"] = (data.get("title") or "").strip()

            # ── HARD GUARANTEE: email must be one we actually scraped ────────
            cand_email = (data.get("email") or "").strip().lower()
            if cand_email and cand_email in emails:
                result["email"] = cand_email
                result["email_verified"] = True

            # ── linkedin must also be from the discovered set ────────────────
            cand_li = (data.get("linkedin") or "").strip()
            if cand_li and cand_li in (linkedins_in + linkedins_co):
                result["linkedin"] = cand_li
                result["linkedin_verified"] = True
    except Exception as e:
        print(f"[find_verified_contact] Claude error: {e}")

    # Fallbacks that still never guess: if the LLM declined but we found exactly
    # one strong candidate, use it directly.
    if not result["email"] and len(emails) == 1:
        result["email"] = emails[0]
        result["email_verified"] = True
    if not result["linkedin"]:
        if len(linkedins_in) == 1:
            result["linkedin"] = linkedins_in[0]
            result["linkedin_verified"] = True
        elif not linkedins_in and len(linkedins_co) == 1:
            result["linkedin"] = linkedins_co[0]
            result["linkedin_verified"] = True

    return result


def generate_email_draft(investor_name, investor_type, invested_company, sector, template_subject, template_body, api_key):
    """
    Use Claude Sonnet to write a personalised outreach email for a specific investor,
    strictly preserving the founder's tone and style from the provided template.
    Returns {"subject": "...", "body": "..."} or None on failure.
    """
    import re
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are helping Arvind (founder of Bhookle – a food-tech platform for cloud kitchens "
            "and D2C food brands in India) write personalised investor outreach emails.\n\n"
            f"Investor being contacted:\n"
            f"- Name: {investor_name}\n"
            f"- Type: {investor_type or 'Investor'}\n"
            f"- Notable portfolio company: {invested_company or 'a food-tech startup'} "
            f"(sector: {sector or 'food tech'})\n\n"
            "Arvind's real email template — PRESERVE his exact tone, voice, sentence length, "
            "energy and writing style:\n"
            f"SUBJECT: {template_subject}\n"
            "BODY:\n"
            f"{template_body}\n\n"
            f"Write a personalised version of this email specifically for {investor_name}.\n\n"
            "STRICT rules:\n"
            "1. Keep Arvind's exact voice — same casual/formal level, same rhythm, same energy\n"
            f"2. Naturally reference their investment in {invested_company or investor_type} where it fits\n"
            "3. Same length as the template — do NOT add extra paragraphs or generic filler\n"
            "4. Do NOT use clichés like 'I hope this finds you well' unless Arvind does in the template\n"
            "5. The Bhookle pitch must remain as sharp as the original\n\n"
            "Return ONLY valid JSON — no markdown, no explanation:\n"
            '{{"subject": "email subject here", "body": "email body here (use \\n for line breaks)"}}'
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        print(f"[generate_email_draft] Error: {e}")
        return None


STAGE_BRIEFS = {
    "new": (
        "FIRST-TOUCH intro to an investor who has never heard from Arvind. Goal: "
        "earn a 15-minute call. Hook in the first line, one sharp Bhookle line, a "
        "single clear ask. Warm, confident, not needy."
    ),
    "didnt_respond": (
        "BREAKUP / last-touch to an investor who never responded after follow-ups. "
        "Brief, gracious, zero pressure. Leave the door open for later. This is the "
        "final email in the thread."
    ),
    "not_interested": (
        "RE-ENGAGEMENT to an investor who previously passed — usually on scale, "
        "timing or stage fit, not the idea. Open by respectfully acknowledging the "
        "earlier pass, then lead with a concrete GROWTH milestone that addresses why "
        "they passed (traction, revenue, scale). Confident, not pushy: 'circumstances "
        "have changed, thought it was worth another look.' Easy, low-pressure ask."
    ),
    "generic": "A clean, general-purpose investor outreach email.",
}


def improve_template(raw_subject, raw_body, stage, api_key):
    """AI template maker. Takes Arvind's pasted rough draft and rewrites it into a
    tighter, stage-appropriate REUSABLE template that strictly preserves his
    voice. Keeps {investor_name} / {invested_company} merge
    placeholders so the per-lead personalizer can fill them later — it does NOT
    personalize to a specific investor here.
    Returns {"subject","body","word_count"} or None on failure.
    """
    import re
    brief = STAGE_BRIEFS.get(stage, STAGE_BRIEFS["generic"])
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are helping Arvind (founder of Bhookle — a food-tech platform for "
            "cloud kitchens and D2C food brands in India) polish a REUSABLE investor "
            "outreach email template.\n\n"
            f"This template is for the lifecycle stage: {stage}.\n"
            f"Stage intent: {brief}\n\n"
            "Arvind's rough draft — PRESERVE his exact tone, voice, vocabulary, "
            "sentence rhythm and energy. Improve clarity and punch, do NOT corporate-ify it:\n"
            f"SUBJECT: {raw_subject}\n"
            "BODY:\n"
            f"{raw_body}\n\n"
            "Rules:\n"
            "1. Keep it a TEMPLATE: use {investor_name} and {invested_company} as merge "
            "placeholders where they belong — do NOT invent a specific investor.\n"
            "2. Keep it tight and skimmable — as long as it needs to be, never padded. "
            "No artificial word limit.\n"
            "3. No clichés ('I hope this finds you well', 'circling back') unless Arvind used them.\n"
            "4. Exactly one clear call-to-action appropriate to the stage.\n"
            "5. Keep Arvind's voice — this should read like he wrote it on a good day, "
            "not like a template generator.\n\n"
            "Return ONLY valid JSON, no markdown:\n"
            '{"subject": "...", "body": "... (use \\n for line breaks)"}'
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        out = json.loads(match.group())
        body = out.get("body", "") or ""
        return {
            "subject": out.get("subject") or raw_subject or "",
            "body": body,
            "word_count": len(body.split()),
        }
    except Exception as e:
        print(f"[improve_template] Error: {e}")
        return None


REJECTION_REASONS = [
    "Portfolio Misfit",     # they already backed a competitor / adjacent bet
    "Thesis Misfit",        # space doesn't fit their stated focus
    "Traction Concerns",    # want more revenue / users / growth proof
    "Scalability Concerns", # doubts on unit economics, market size, ops scaling
    "Never responded",      # auto-set when "Reached Out Again" ages out without reply
    "Others",               # timing, founder fit, no specific reason
]


def classify_rejection_reason(investor_name, notes, api_key):
    """Read the founder's free-text notes about why an investor passed and
    classify into one of REJECTION_REASONS. Returns dict:
       {"reason": str, "confidence": int, "evidence": str}
    Falls back to {"reason":"Others","confidence":0,"evidence":""} if Claude
    fails or the notes are too thin to classify.
    """
    import re
    notes = (notes or "").strip()
    fallback = {"reason": "Others", "confidence": 0, "evidence": ""}
    if not notes:
        return fallback

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You're classifying WHY an investor passed on Bhookle (a food-tech / "
            "cloud-kitchen startup in India), based on the founder's free-form "
            "notes about the rejection.\n\n"
            f'Investor: "{investor_name}"\n'
            f"Notes:\n\"\"\"\n{notes}\n\"\"\"\n\n"
            "Pick ONE category — read the notes carefully and only commit to a "
            "specific one when there's clear textual signal. When in doubt → Others.\n\n"
            "• Portfolio Misfit — they already invested in a competitor or adjacent "
            "bet (e.g., 'already backed Swiggy in this space', 'have a similar deal').\n"
            "• Thesis Misfit — the space / business model isn't part of their fund's "
            "focus (e.g., 'we only do SaaS', 'too consumer for them', 'B2B-only').\n"
            "• Traction Concerns — they want more revenue, users, retention or growth "
            "proof first (e.g., 'come back at $X MRR', 'show 6 months retention').\n"
            "• Scalability Concerns — doubts about unit economics, margins, or "
            "ability to scale beyond a niche (e.g., 'doesn't scale past 5 cities', "
            "'margins look thin', 'TAM too small').\n"
            "• Others — timing, founder fit, no specific reason, or unclear notes.\n\n"
            "Return ONLY JSON:\n"
            '{"reason":"Portfolio Misfit|Thesis Misfit|Traction Concerns|Scalability Concerns|Others",'
            '"confidence":0-100,'
            '"evidence":"one short phrase QUOTED from the notes that justifies the pick, '
            'or empty string if Others"}'
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return fallback
        out = json.loads(m.group())
        reason = (out.get("reason") or "").strip()
        if reason not in REJECTION_REASONS:
            reason = "Others"
        return {
            "reason": reason,
            "confidence": int(out.get("confidence", 0) or 0),
            "evidence": (out.get("evidence") or "").strip(),
        }
    except Exception as e:
        print(f"[classify_rejection_reason] {investor_name}: {e}")
        return fallback


def greeting_name(ctx):
    """Who the email is addressed to. Prefer the actual contact PERSON's first name
    (key_contact), fall back to the firm, then a neutral 'there'. Fixes greeting an
    email 'Hi <Firm>,' when we know the person (e.g. 'Hi Jane,')."""
    contact = (ctx.get("key_contact") or "").split(",")[0].strip()
    if contact and contact.lower() not in ("team", "the team", "investor relations", "ir"):
        return contact.split()[0]            # first name only
    firm = (ctx.get("investor_name") or "").strip()
    return firm or "there"


def _merge_placeholders(text, ctx):
    """Deterministic merge — the safe fallback when we won't risk AI personalisation.

    Fills {investor_name}. For {invested_company}: fills it only when a REAL
    portfolio company is known; otherwise DROPS the whole paragraph that mentions
    it rather than emitting generic filler like 'your portfolio'. Also strips any
    leftover [author-choice] brackets (e.g. '[retention / community / ...]')."""
    import re
    if not text:
        return text or ""
    name = greeting_name(ctx)
    co = (ctx.get("invested_company") or "").strip()
    has_co = bool(co) and co not in ("—", "-") and "bhookle" not in co.lower()

    out = text.replace("{investor_name}", name)
    if has_co:
        out = out.replace("{invested_company}", co)
    else:
        # No real company → remove the paragraph(s) referencing it, never "your portfolio".
        paras = re.split(r"\n\s*\n", out)
        kept = [p for p in paras if "{invested_company}" not in p]
        out = "\n\n".join(kept) if kept else out.replace("{invested_company}", "").strip()
    # Remove unfilled author-choice brackets like "[a / b / c]".
    out = re.sub(r"\s*\[[^\]\n]*\]", "", out)
    return out.strip()


def personalize_email(ctx, template_subject, template_body, api_key, news_hook=""):
    """Confidence-GATED per-lead personalisation (anti-guess, mirrors the enrich
    engine's 'never invent' rule applied to copy).

    ctx keys: investor_name, investor_type, invested_company, sector,
              recent_investments, trigger_signals, action_item.

    Returns {subject, body, personalized: bool, confidence: int, basis: str}.
    If there's no specific verified fact, or the model isn't confident, it returns
    the LOCKED template with only {investor_name}/{invested_company} merged — never
    a fabricated 'you did X' line.
    """
    import re
    generic_subject = _merge_placeholders(template_subject, ctx) or (template_subject or "")
    generic_body    = _merge_placeholders(template_body, ctx)

    # CONCRETE, CHECKABLE facts only. We deliberately do NOT use `sector`,
    # `trigger_signals`, or `action_item` here: those are soft, model-inferred
    # classifications (often wrong — e.g. a firm mislabeled "food tech") and
    # asserting them to an investor as fact is the exact anti-guess failure we
    # must avoid. Only a real portfolio company, real recent deals, or a
    # grounded news hook (evidence-backed) may drive personalisation.
    facts, strong = [], False
    co = (ctx.get("invested_company") or "").strip()
    if co and co not in ("—", "-") and "bhookle" not in co.lower():
        facts.append(f"A specific portfolio company they actually backed: {co}"); strong = True
    if (ctx.get("recent_investments") or "").strip():
        facts.append(f"Specific recent investments on record: {ctx['recent_investments']}"); strong = True
    if (news_hook or "").strip():
        facts.append(f"Recent verified, source-grounded development: {news_hook}"); strong = True

    # Nothing specific to ground on → don't even ask the model. Use the template.
    if not strong:
        return {"subject": generic_subject, "body": generic_body, "personalized": False,
                "confidence": 0,
                "basis": "No specific verified detail about this investor — sent your locked template as-is."}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        greet = greeting_name(ctx)
        prompt = (
            "You personalise investor outreach for Arvind, founder of Bhookle "
            "(food-tech for cloud kitchens & D2C food brands in India).\n\n"
            f"Firm: {ctx.get('investor_name','')}"
            + (f" ({ctx.get('investor_type')})" if ctx.get('investor_type') else "") + "\n"
            f"Address the email to this person: {greet}\n\n"
            "The ONLY verified facts you may reference — do NOT invent anything beyond these. "
            "In particular you have NO information about their sector/thesis focus, so NEVER "
            "claim what sectors they invest in:\n"
            + "\n".join(f"- {f}" for f in facts) + "\n\n"
            "Arvind's approved template — preserve his EXACT voice, tone, rhythm and length:\n"
            f"SUBJECT: {template_subject}\n"
            "BODY:\n"
            f"{template_body}\n\n"
            "Task:\n"
            f"1. Replace {{investor_name}} with the addressee's name: {greet}\n"
            "2. {invested_company}: fill it ONLY if a specific portfolio company is in the facts "
            "above. If no real company is given, DELETE the entire sentence that mentions it — "
            "do NOT keep the placeholder and NEVER write generic stand-ins like 'your portfolio', "
            "'your fund', or 'your firm'.\n"
            "3. Resolve any author-choice brackets like '[a / b / c]' into ONE clean phrase that "
            "fits the facts; never leave square brackets in the output.\n"
            "4. Add AT MOST ONE short, specific personalisation sentence that references a REAL "
            "fact above (e.g. 'saw you backed X', 'given your focus on Y'). It must be truthful "
            "and specific — NEVER generic flattery, NEVER invented.\n"
            "5. If the facts are too thin to personalise truthfully, do NOT force it: keep the "
            "template clean (still applying rules 1-3) and set personalized=false.\n\n"
            "Return ONLY JSON:\n"
            '{"subject":"...","body":"... (\\n for line breaks)","personalized":true/false,'
            '"confidence":0-100,"basis":"one short line naming the exact fact you used, or why you couldn\'t"}'
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        out = json.loads(m.group()) if m else {}
        conf = int(out.get("confidence", 0) or 0)
        basis = (out.get("basis") or "").strip()
        # Hard gate: only accept personalisation if the model is confident AND grounded.
        if bool(out.get("personalized")) and conf >= 60 and basis and out.get("body"):
            return {"subject": out.get("subject") or generic_subject,
                    "body": out["body"], "personalized": True,
                    "confidence": conf, "basis": basis}
        return {"subject": generic_subject, "body": generic_body, "personalized": False,
                "confidence": conf,
                "basis": basis or "Not confident enough to personalise — used your locked template."}
    except Exception as e:
        print(f"[personalize_email] Error: {e}")
        return {"subject": generic_subject, "body": generic_body, "personalized": False,
                "confidence": 0, "basis": "Personalisation unavailable — used your locked template."}


LINKEDIN_CONNECT_MAX = 300   # LinkedIn's hard cap on a connection-request note


def compose_linkedin(ctx, connect_template, dm_template, api_key, news_hook=""):
    """Compose two LinkedIn outreach messages for one lead, personalised under the
    same anti-guess gate as personalize_email (never invent a fact about them):

      • connect_note — a connection-request note, hard-capped at 300 chars
      • dm           — a full direct message / InMail (no practical length cap)

    ctx keys mirror personalize_email: investor_name, investor_type,
    invested_company, recent_investments, key_contact, trigger_signals, action_item.

    Returns {connect_note, dm, personalized: bool, confidence: int, basis: str}.
    With no verified specific fact — or if the model isn't confident — it returns
    the base templates with only {investor_name}/{invested_company} merged.
    """
    import re

    def _cap_connect(text):
        """Guarantee the connect note respects LinkedIn's 300-char limit."""
        t = (text or "").strip()
        if len(t) <= LINKEDIN_CONNECT_MAX:
            return t
        cut = t[:LINKEDIN_CONNECT_MAX]
        # trim back to a word boundary so we don't slice mid-word
        if " " in cut:
            cut = cut[:cut.rfind(" ")]
        return cut.rstrip(" ,;—-") + "…"

    generic_connect = _cap_connect(_merge_placeholders(connect_template, ctx))
    generic_dm      = _merge_placeholders(dm_template, ctx)

    # Same CONCRETE, CHECKABLE facts gate as personalize_email — no soft
    # sector/thesis guesses, only a real portfolio company / recent deals / a
    # grounded news hook may drive personalisation.
    facts, strong = [], False
    co = (ctx.get("invested_company") or "").strip()
    if co and co not in ("—", "-") and "bhookle" not in co.lower():
        facts.append(f"A specific portfolio company they actually backed: {co}"); strong = True
    if (ctx.get("recent_investments") or "").strip():
        facts.append(f"Specific recent investments on record: {ctx['recent_investments']}"); strong = True
    if (news_hook or "").strip():
        facts.append(f"Recent verified, source-grounded development: {news_hook}"); strong = True

    if not strong:
        return {"connect_note": generic_connect, "dm": generic_dm, "personalized": False,
                "confidence": 0,
                "basis": "No specific verified detail about this investor — used your base LinkedIn copy as-is."}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        greet = greeting_name(ctx)
        prompt = (
            "You personalise LinkedIn outreach for Arvind, founder of Bhookle "
            "(home-cooked-food marketplace in India — the 'Airbnb of home food').\n\n"
            f"Person being contacted: {greet}"
            + (f" at {ctx.get('investor_name','')}" if ctx.get('investor_name') else "")
            + (f" ({ctx.get('investor_type')})" if ctx.get('investor_type') else "") + "\n\n"
            "The ONLY verified facts you may reference — do NOT invent anything beyond these. "
            "You have NO information about their sector/thesis focus, so NEVER claim what "
            "sectors they invest in:\n"
            + "\n".join(f"- {f}" for f in facts) + "\n\n"
            "Arvind's approved base messages — preserve his EXACT voice, tone and rhythm:\n"
            f"CONNECTION NOTE (must stay <= {LINKEDIN_CONNECT_MAX - 20} characters):\n{connect_template}\n\n"
            f"DIRECT MESSAGE:\n{dm_template}\n\n"
            "Task — produce BOTH messages, personalised for this person:\n"
            f"1. Replace {{investor_name}} with the addressee's name: {greet}\n"
            "2. {invested_company}: fill ONLY if a specific portfolio company is in the facts "
            "above; if none, DELETE the sentence that mentions it — never keep the placeholder "
            "and never write 'your portfolio'/'your fund'/'your firm'.\n"
            "3. Add AT MOST ONE short, specific, TRUE personalisation line referencing a real "
            "fact above (e.g. 'saw you backed X'). Never generic flattery, never invented.\n"
            f"4. The connection note MUST be <= {LINKEDIN_CONNECT_MAX - 20} characters. Count carefully.\n"
            "5. If the facts are too thin to personalise truthfully, keep the base copy clean "
            "(still applying rules 1-2) and set PERSONALIZED to no.\n\n"
            # A delimited format, NOT JSON: the DM is multi-line prose with quotes
            # and rupee symbols, which routinely broke json.loads() and silently
            # dropped every lead to base copy.
            "Return EXACTLY this format, nothing else (no JSON, no markdown fences):\n"
            "===CONNECT===\n"
            "<the connection note, one paragraph>\n"
            "===DM===\n"
            "<the direct message, line breaks allowed>\n"
            "===META===\n"
            "PERSONALIZED: yes|no\n"
            "CONFIDENCE: <0-100>\n"
            "BASIS: <one short line naming the exact fact you used, or why you couldn't>"
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        def _section(name, nxt):
            m = re.search(rf"==={name}===\s*(.*?)\s*(?====(?:{nxt})===|$)", text, re.DOTALL)
            return (m.group(1).strip() if m else "")

        connect = _section("CONNECT", "DM|META")
        dm      = _section("DM", "META")
        meta    = _section("META", "ZZZ")
        pers  = bool(re.search(r"PERSONALIZED:\s*yes", meta, re.I))
        cm    = re.search(r"CONFIDENCE:\s*(\d+)", meta, re.I)
        conf  = int(cm.group(1)) if cm else 0
        bm    = re.search(r"BASIS:\s*(.+)", meta)
        basis = (bm.group(1).strip() if bm else "")
        if pers and conf >= 60 and basis and dm:
            return {"connect_note": _cap_connect(connect or generic_connect),
                    "dm": dm, "personalized": True,
                    "confidence": conf, "basis": basis}
        return {"connect_note": generic_connect, "dm": generic_dm, "personalized": False,
                "confidence": conf,
                "basis": basis or "Not confident enough to personalise — used your base LinkedIn copy."}
    except Exception as e:
        print(f"[compose_linkedin] Error: {e}")
        return {"connect_note": generic_connect, "dm": generic_dm, "personalized": False,
                "confidence": 0, "basis": "Personalisation unavailable — used your base LinkedIn copy."}


def get_seed_data():
    return SEED_DATA
