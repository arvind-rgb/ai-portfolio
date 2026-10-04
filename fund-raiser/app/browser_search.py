"""
Headless-Chrome Google search — used as the middle tier of the email cascade.

Why this exists: the Gemini API's Google-Search grounding is more conservative
than the consumer google.com "AI Overview". Running a real headless browser from
the user's machine (residential IP) reproduces the AI-Overview result that a
human sees — which is how the user manually found emails the API missed.

Reuse ONE GoogleBrowser across many queries (launch cost ~1-2s). Everything is
best-effort; on any failure it returns "" so callers fall through gracefully.
"""
import os
import re
import time
from contextlib import contextmanager

try:
    from playwright.sync_api import sync_playwright
    _HAVE_PW = True
except Exception:
    _HAVE_PW = False

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class GoogleBrowser:
    def __init__(self, headless=True, li_at=None):
        self.headless = headless
        # LinkedIn session cookie (optional). Enables the Contact-info overlay.
        self.li_at = li_at or os.getenv("LINKEDIN_LI_AT")
        self._pw = None
        self._browser = None
        self._ctx = None

    def __enter__(self):
        if not _HAVE_PW:
            return self
        self._pw = sync_playwright().start()
        # Launch args that strip the headless-automation fingerprint that
        # LinkedIn's bot-detection keys off of.
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._ctx = self._browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
            locale="en-US",
            timezone_id="Asia/Kolkata",
            viewport={"width": 1280, "height": 1600},
        )
        # Hide navigator.webdriver and a few other automation tells.
        try:
            self._ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome={runtime:{}};"
                "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
                "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
            )
        except Exception:
            pass
        cookies = [
            {"name": "CONSENT", "value": "YES+", "domain": ".google.com", "path": "/"},
            {"name": "SOCS", "value": "CAI", "domain": ".google.com", "path": "/"},
        ]
        if self.li_at:
            cookies.append({"name": "li_at", "value": self.li_at,
                            "domain": ".linkedin.com", "path": "/"})
        try:
            self._ctx.add_cookies(cookies)
        except Exception:
            pass
        return self

    @property
    def has_linkedin_auth(self):
        return bool(self.li_at)

    def __exit__(self, *a):
        for closer in (self._ctx, self._browser):
            try:
                if closer: closer.close()
            except Exception:
                pass
        try:
            if self._pw: self._pw.stop()
        except Exception:
            pass

    def search_text(self, query, wait_ms=2600):
        """Run a google.com search and return the rendered page's visible text
        (including the AI Overview once it streams in). Returns '' on failure."""
        if not self._ctx:
            return ""
        page = None
        try:
            page = self._ctx.new_page()
            url = ("https://www.google.com/search?hl=en&gl=us&q="
                   + query.replace(" ", "+"))
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            # If a consent page slipped through, try to accept it.
            try:
                btn = page.query_selector(
                    "button:has-text('Accept all'), button:has-text('I agree'), "
                    "form[action*='consent'] button")
                if btn:
                    btn.click()
                    page.wait_for_timeout(800)
            except Exception:
                pass
            # Let the AI Overview / results stream in.
            page.wait_for_timeout(wait_ms)
            # Best-effort: expand "Show more" on the AI Overview if present.
            try:
                more = page.query_selector(
                    "div[aria-label*='Show more'], div[role='button']:has-text('Show more')")
                if more:
                    more.click()
                    page.wait_for_timeout(900)
            except Exception:
                pass
            return page.inner_text("body")
        except Exception:
            return ""
        finally:
            try:
                if page: page.close()
            except Exception:
                pass

    def search_html(self, query, wait_ms=2200):
        """Like search_text, but returns the full rendered HTML (so result
        link hrefs — e.g. linkedin.com/in/… URLs — are available)."""
        if not self._ctx:
            return ""
        page = None
        try:
            page = self._ctx.new_page()
            url = ("https://www.google.com/search?hl=en&gl=us&q="
                   + query.replace(" ", "+"))
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            try:
                btn = page.query_selector(
                    "button:has-text('Accept all'), button:has-text('I agree'), "
                    "form[action*='consent'] button")
                if btn:
                    btn.click(); page.wait_for_timeout(700)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            return page.content()
        except Exception:
            return ""
        finally:
            try:
                if page: page.close()
            except Exception:
                pass


    # ── LinkedIn ─────────────────────────────────────────────────────────────
    def linkedin_emails(self, profile_url, person=None):
        """Scrape a LinkedIn profile for any email address, from:
            (a) the public About / bio text + embedded JSON (no login needed), and
            (b) the structured 'Contact info' overlay (needs the li_at cookie).
        Returns a de-duped list of emails found (caller applies its own gate)."""
        if not self._ctx or not profile_url:
            return []
        profile_url = profile_url.strip().rstrip("/")
        if "linkedin.com/in/" not in profile_url:
            return []  # only personal profiles have an email field

        found, seen = [], set()

        def grab(html_or_text):
            for e in _EMAIL_RE.findall(html_or_text or ""):
                el = e.strip().lower().rstrip(".")
                if el not in seen:
                    seen.add(el)
                    found.append(el)

        page = None
        try:
            page = self._ctx.new_page()
            # (a) Public profile page — About section + embedded JSON
            page.goto(profile_url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(2200)
            try:
                for a in page.query_selector_all("a[href^='mailto:']"):
                    grab((a.get_attribute("href") or "").replace("mailto:", ""))
            except Exception:
                pass
            grab(page.inner_text("body"))
            grab(page.content())  # JSON-LD / embedded data often holds the email

            # (b) Contact-info modal — CLICK the link (the overlay URL just
            #     redirects). Only meaningful when authenticated.
            if self.li_at:
                try:
                    link = (page.query_selector("a[href$='/overlay/contact-info/']")
                            or page.query_selector("#top-card-text-details-contact-info")
                            or page.query_selector("a:has-text('Contact info')"))
                    if link:
                        link.click()
                        # wait for the modal to render
                        try:
                            page.wait_for_selector(".artdeco-modal, [aria-label*='Contact info']",
                                                   timeout=5000)
                        except Exception:
                            pass
                        page.wait_for_timeout(1200)
                        modal = (page.query_selector("[aria-label*='Contact info']")
                                 or page.query_selector(".artdeco-modal__content")
                                 or page.query_selector(".artdeco-modal"))
                        if modal:
                            try:
                                for a in modal.query_selector_all("a[href^='mailto:']"):
                                    grab((a.get_attribute("href") or "").replace("mailto:", ""))
                            except Exception:
                                pass
                            grab(modal.inner_text())
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                if page: page.close()
            except Exception:
                pass

        return found

    def linkedin_people_search(self, name, context="", wait_ms=3500, max_results=6):
        """Authenticated LinkedIn People search → list of REAL, resolvable /in/
        profile URLs for the top results (no fabrication, no 404s). Needs a valid
        li_at cookie. Best-effort; returns [] on any failure or if not authed.

        `context` (e.g. the firm / a portfolio company) is appended to the query to
        land on the PRECISE person, not just anyone with that name. Kept light (one
        page load + a short lazy-load scroll) so a fetch's handful of these stays
        within human-like usage."""
        if not self._ctx or not self.li_at or not name:
            return []
        from urllib.parse import quote
        kw = quote(f"{name} {context}".strip())
        page = None
        try:
            page = self._ctx.new_page()
            page.goto(
                "https://www.linkedin.com/search/results/people/?keywords=" + kw,
                timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            # Result cards lazy-load — nudge them in.
            try:
                for _ in range(2):
                    page.mouse.wheel(0, 1400); page.wait_for_timeout(900)
            except Exception:
                pass

            urls, seen = [], set()

            def _add(slug):
                slug = (slug or "").split("?")[0].split("/")[0]
                if not slug:
                    return
                u = "https://www.linkedin.com/in/" + slug
                if u not in seen:
                    seen.add(u); urls.append(u)

            # Result links are usually RELATIVE ("/in/slug?..."), so match the slug,
            # not a full URL, then rebuild the canonical profile URL.
            for a in page.query_selector_all("a[href*='/in/']"):
                m = re.search(r"/in/([A-Za-z0-9\-_%]+)", a.get_attribute("href") or "")
                if m:
                    _add(m.group(1))
                if len(urls) >= max_results:
                    break
            if not urls:                      # fallback: scan the rendered HTML
                for m in re.finditer(r"/in/([A-Za-z0-9\-_%]+)", page.content()):
                    _add(m.group(1))
                    if len(urls) >= max_results:
                        break
            return urls
        except Exception:
            return []
        finally:
            try:
                if page: page.close()
            except Exception:
                pass

    def linkedin_company_people(self, firm_name, keywords="", max_results=8):
        """Find people AT a firm the way a human does: open the firm's LinkedIn
        COMPANY page → People tab → read the employee cards.

        This is far more reliable than guessing a person's name, because the
        company page is authoritative about who actually works there. Optional
        `keywords` filters the People tab (e.g. "partner", "consumer").

        Returns [{name, headline, url}] — real profiles only. Needs a valid li_at.
        """
        if not self._ctx or not self.li_at or not firm_name:
            return []
        from urllib.parse import quote
        page = None
        try:
            page = self._ctx.new_page()
            # 1. Locate the company page via LinkedIn's own company search.
            page.goto("https://www.linkedin.com/search/results/companies/?keywords="
                      + quote(firm_name), timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            m = re.search(r"/company/([A-Za-z0-9\-_%\.]+)", page.content() or "")
            if not m:
                return []
            slug = m.group(1)

            # 2. Open its People tab (optionally keyword-filtered).
            url = f"https://www.linkedin.com/company/{slug}/people/"
            if keywords:
                url += "?keywords=" + quote(keywords)
            page.goto(url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            for _ in range(2):                     # employee cards lazy-load
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(1200)

            out, seen = [], set()
            for card in page.query_selector_all(
                    "li.org-people-profile-card__profile-card-spacing, li.grid, div.org-people-profile-card"):
                try:
                    a = card.query_selector("a[href*='/in/']")
                    if not a:
                        continue
                    mm = re.search(r"/in/([A-Za-z0-9\-_%]+)", a.get_attribute("href") or "")
                    if not mm:
                        continue
                    slug_p = mm.group(1)
                    if slug_p in seen:
                        continue
                    seen.add(slug_p)
                    txt = [t.strip() for t in (card.inner_text() or "").split("\n") if t.strip()]
                    out.append({
                        "name": txt[0] if txt else "",
                        "headline": txt[1] if len(txt) > 1 else "",
                        "url": "https://www.linkedin.com/in/" + slug_p,
                    })
                    if len(out) >= max_results:
                        break
                except Exception:
                    continue
            return out
        except Exception:
            return []
        finally:
            try:
                if page: page.close()
            except Exception:
                pass

    def linkedin_session_ok(self):
        """Quick check that the li_at cookie is valid (not logged out)."""
        if not self._ctx or not self.li_at:
            return False
        page = None
        try:
            page = self._ctx.new_page()
            page.goto("https://www.linkedin.com/feed/", timeout=15000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            url = page.url
            # logged-in feed stays on /feed; logged-out bounces to /login or /authwall
            return "/feed" in url and "login" not in url and "authwall" not in url
        except Exception:
            return False
        finally:
            try:
                if page: page.close()
            except Exception:
                pass


@contextmanager
def google_browser(headless=True, li_at=None):
    gb = GoogleBrowser(headless=headless, li_at=li_at)
    try:
        gb.__enter__()
        yield gb
    finally:
        gb.__exit__()


def available():
    return _HAVE_PW
