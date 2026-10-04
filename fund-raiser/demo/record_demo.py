"""Record the Fund Raiser demo against the sanitized copy on :5150 (fake data).
All non-localhost traffic is aborted; send / OAuth / lead-sourcing endpoints are
blocked; the one live AI call shown (template rewrite) is stubbed."""
import json, time, os, shutil
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5150"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "rec")   
shutil.rmtree(OUT, ignore_errors=True)

INIT = r"""
(() => {
  const css = `
  #__cap{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2147483647;
    max-width:1080px;width:calc(100% - 120px);background:rgba(52,28,61,.96);color:#fff;
    font:500 17px/1.45 Poppins,Roboto,Arial,sans-serif;padding:14px 22px;border-radius:12px;
    box-shadow:0 8px 30px rgba(0,0,0,.35);border-left:6px solid #FFA70B;transition:opacity .35s;
    pointer-events:none}
  #__cap b{color:#FFA70B;font-weight:700;margin-right:8px}
  #__cur{position:fixed;width:18px;height:18px;border-radius:50%;background:rgba(255,167,11,.55);
    border:2px solid #341C3D;z-index:2147483647;pointer-events:none;transform:translate(-50%,-50%);
    left:-50px;top:-50px;transition:width .12s,height .12s}
  #__cur.down{width:28px;height:28px;background:rgba(255,167,11,.85)}`;
  function mount(){
    if (document.getElementById('__cap')) return;
    const s=document.createElement('style'); s.textContent=css; document.head.appendChild(s);
    const c=document.createElement('div'); c.id='__cap'; document.body.appendChild(c);
    const k=document.createElement('div'); k.id='__cur'; document.body.appendChild(k);
    const saved = sessionStorage.getItem('__cap');
    if (saved) c.innerHTML = saved; else c.style.opacity = 0;
    const p = sessionStorage.getItem('__curpos');
    if (p) { const [x,y]=p.split(','); k.style.left=x+'px'; k.style.top=y+'px'; }
    document.addEventListener('mousemove', e => { k.style.left=e.clientX+'px'; k.style.top=e.clientY+'px';
      sessionStorage.setItem('__curpos', e.clientX+','+e.clientY); }, true);
    document.addEventListener('mousedown', () => k.classList.add('down'), true);
    document.addEventListener('mouseup', () => k.classList.remove('down'), true);
  }
  window.__setCap = (html) => { sessionStorage.setItem('__cap', html); mount();
    const c=document.getElementById('__cap'); c.style.opacity=0;
    setTimeout(()=>{ c.innerHTML=html; c.style.opacity=1; }, 200); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
"""

# Anything that could send, authenticate, scrape or spend tokens is refused.
BLOCK = ("/email/send", "/api/refresh", "/api/dispatch", "/api/bulk-send", "/send-email",
         "/api/gmail/auth", "/api/gmail/callback", "/api/gmail/credentials", "/api/sync-status",
         "/api/check-bounce", "/enrich", "/recent", "/linkedin/mark", "/classify-rejections",
         "/draft-email")

AI_REWRITE = ("Hi {investor_name} — I'm the founder of Bhookle, the \"Airbnb of home-cooked food.\" "
              "Bootstrapped to [X]K+ meals with [N] home chefs and [X]% repeat. We're raising ₹[X] Cr "
              "to open [City A] & [City B] and I'd love to connect before it closes.")


def router(route):
    url = route.request.url
    if not url.startswith(BASE):
        return route.abort()
    if any(b in url for b in BLOCK):
        print("BLOCKED", url)
        return route.fulfill(status=403, body='{"error":"blocked in demo"}', content_type="application/json")
    if url.endswith("/api/templates/ai-improve"):
        time.sleep(2.2)   # feels like a real model call; no model is called
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"subject": "", "body": AI_REWRITE}))
    if route.request.method == "POST" and url.endswith("/linkedin"):
        time.sleep(1.6)   # show the "Personalising in your voice…" state
    if url.endswith("/email/compose"):
        time.sleep(1.4)
    return route.continue_()


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                              record_video_dir=OUT, record_video_size={"width": 1280, "height": 720})
    ctx.add_init_script(INIT)
    ctx.route("**/*", router)
    page = ctx.new_page()
    W = page.wait_for_timeout

    def cap(step, text):
        page.evaluate("h => window.__setCap(h)", f"<b>{step}</b>{text}")

    def move_to(loc, click=False):
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y, steps=25)
        W(350)
        if click:
            loc.click()

    def smooth_scroll(dy, steps=30, pause=25):
        for _ in range(steps):
            page.mouse.wheel(0, dy / steps); W(pause)

    def nav(url):
        page.goto(url); page.wait_for_load_state("networkidle")

    nav(BASE + "/")
    page.mouse.move(640, 360)
    cap("Fund Raiser", "An AI-assisted investor-outreach tracker I built to run Bhookle's seed raise. "
        "All investors in this demo are fictional.")
    W(5000)

    # 1 — leads list
    cap("1 · Leads", "Every lead is scored 0–100 and tiered by an AI gate: India-based angels writing "
        "first cheques in consumer / food. VCs, marquee names and anyone already contacted are filtered out.")
    move_to(page.locator(".score-badge").first); W(3000)
    move_to(page.locator(".lead-trigger").first); W(2000)
    cap("1 · Leads", "Each row shows WHY it matched (the trigger signal), a suggested outreach angle, "
        "and a link to the source article that verifies the investment.")
    move_to(page.locator(".lead-action").first); W(2200)
    move_to(page.locator(".lead-evidence").first); W(2500)
    smooth_scroll(700, 40); W(1500); smooth_scroll(-700, 30); W(600)

    # 2 — filters & search
    cap("2 · Filters", "Pipeline chips filter by stage and tier — here, only Tier 1 (high-intent) leads.")
    move_to(page.locator("a.stat-chip.t1"), click=True); page.wait_for_load_state("networkidle"); W(2800)
    cap("2 · Filters", "…or only the investors who have replied and are now Engaged.")
    move_to(page.locator("a.stat-chip.s-engaged"), click=True); page.wait_for_load_state("networkidle"); W(2800)
    nav(BASE + "/")
    cap("2 · Search", "Free-text search across investor, portfolio company, contact and sector.")
    move_to(page.locator("input.search-input"), click=True)
    page.locator("input.search-input").type("tiffin", delay=140); W(500)
    page.keyboard.press("Enter"); page.wait_for_load_state("networkidle"); W(2800)

    # 3 — lead detail / not interested
    nav(BASE + "/?status=Not Interested")
    cap("3 · Lead detail", "Passed investors are tagged with a reason (Claude classifies the notes into "
        "Thesis / Portfolio / Traction misfit) so the re-engagement email can address it.")
    W(400)
    move_to(page.locator(".rejection-select").first); W(2800)
    move_to(page.locator(".notes-ta").first); W(2200)

    # 4 — AI LinkedIn draft
    nav(BASE + "/")
    cap("4 · AI LinkedIn draft", "Claude rewrites my approved base copy for this investor, hooked on a "
        "verified fact (their Tiffin Demo Co cheque). With no verified fact, it falls back to the base copy rather than invent one.")
    row = page.locator("tr", has_text="Asha Example").first
    move_to(row.locator(".btn-linkedin-msg"), click=True)
    page.locator("#li-form").wait_for(state="visible"); W(4500)
    cap("4 · AI LinkedIn draft", "Two formats: a ≤300-char connection note and a full DM, pre-composed in "
        "parallel when the lead is fetched. LinkedIn has no send API, so I paste and send it myself.")
    move_to(page.locator("button.li-type-btn[data-type=dm]"), click=True); W(1200)
    move_to(page.locator("#li-body")); W(3000)
    page.locator("#li-body").evaluate("e => e.scrollTo({top: e.scrollHeight, behavior: 'smooth'})"); W(2500)
    move_to(page.locator("#linkedinModal .modal-foot .btn-ghost"), click=True); W(900)

    # 5 — AI email draft
    cap("5 · AI email draft", "Same engine for email: personalised subject + body, pitch deck attached. "
        "Real sends go through Gmail with a review step and throttling. Sending is disabled in this demo.")
    move_to(row.locator(".btn-email-send"), click=True)
    page.locator("#em-form").wait_for(state="visible"); W(3800)
    move_to(page.locator("#em-body")); W(1500)
    page.locator("#em-body").evaluate("e => e.scrollTo({top: e.scrollHeight, behavior: 'smooth'})"); W(2800)
    move_to(page.locator("#emailModal .modal-foot .btn-ghost"), click=True); W(900)

    # 6 — templates + AI rewrite (stubbed)
    cap("6 · Templates", "The base templates are mine, in my voice. 'Write with AI' tightens a rough draft "
        "without changing the tone. (Response stubbed here, no API key used.)")
    move_to(page.get_by_role("button", name="LinkedIn Templates"), click=True)
    page.locator("#tab-final").wait_for(state="visible"); W(2800)
    move_to(page.locator("#tab-ai-btn"), click=True); W(4000)
    move_to(page.locator("#tab-final")); W(2800)
    move_to(page.locator("#templatesModal .modal-close"), click=True); W(900)

    # 7 — get more leads pipeline
    cap("7 · Get More Leads", "Sourcing pipeline: news RSS + Gemini-grounded scouting → angels-only gate "
        "(~1 in 8 pass) → marquee blocklist → person-vs-firm enrichment → layered dedup. It never guesses a LinkedIn URL.")
    move_to(page.locator("#refreshBtn"), click=True); W(6500)
    move_to(page.locator("#getLeadsModal button", has_text="Cancel"), click=True); W(900)

    # 8 — report
    cap("8 · Outreach report", "Every send, reply and bounce is an append-only event, which gives a live "
        "funnel: contacted, delivered, engaged, and sends per day.")
    move_to(page.get_by_role("button", name="Report"), click=True); W(3000)
    page.evaluate("""() => { const b = document.querySelector('#reportModal .modal-body') ||
                         document.querySelector('#reportModal .modal');
                         if (b) b.scrollTo({top: b.scrollHeight, behavior: 'smooth'}); }""")
    W(4500)
    move_to(page.locator("#reportModal .modal-close"), click=True); W(700)

    cap("Fund Raiser", "Flask + SQLite · Claude for personalisation & classification · Gemini for grounded "
        "discovery · a human approves every send.")
    W(5500)

    video = page.video
    ctx.close(); browser.close()
    print("VIDEO", video.path())
