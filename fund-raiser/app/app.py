import os
import re
import csv
import io
import uuid
import base64
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders as email_encoders
from flask import Flask, render_template, request, jsonify, Response, redirect, session
from dotenv import load_dotenv
from database import db, InvestmentLead, EmailTemplate, OutreachEvent
from scraper import (get_seed_data, scrape_live, fetch_recent_investments,
                     find_verified_contact, generate_email_draft, improve_template,
                     personalize_email, compose_linkedin, LINKEDIN_CONNECT_MAX,
                     classify_rejection_reason, REJECTION_REASONS)
from enrich_engine import (smart_enrich, enrich_person, looks_like_individual,
                           verify_investor, verify_lead_evidence, clean_linkedin)
from browser_search import google_browser, available as browser_available
from getleads_engine import get_leads as engine_get_leads

load_dotenv(override=True)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URI", "sqlite:///investment_leads.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")

db.init_app(app)


# ── SQLite concurrency ───────────────────────────────────────────────────────
# The review flow now drafts several leads in parallel, each caching its grounded
# news hook with a quick write. Plain SQLite serialises writers and fails fast
# with "database is locked"; WAL mode + a busy timeout let concurrent readers and
# writers coexist instead of stalling the UI. No-op on non-SQLite engines.
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _SA_Engine
import sqlite3 as _sqlite3


@_sa_event.listens_for(_SA_Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _rec):
    if isinstance(dbapi_conn, _sqlite3.Connection):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")   # wait up to 5s for a lock, don't error
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


# ── Jinja filter: render a stored UTC datetime in IST (the user is in India) ──
from datetime import timedelta as _timedelta

@app.after_request
def _no_cache_html(resp):
    """The single-page UI has no content-hash and changes often, so never let the
    browser serve a stale index.html (the recurring 'why am I seeing the old
    thing' bug). Static assets (logo, etc.) keep their normal caching."""
    try:
        if resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
    except Exception:
        pass
    return resp


@app.template_filter("ist")
def _ist(dt, fmt="%d %b %Y, %I:%M %p"):
    """created_at/updated_at are stored as naive UTC (datetime.utcnow). Shift to
    IST (UTC+5:30) for display so 'when was this added' reads correctly."""
    if not dt:
        return ""
    try:
        return (dt + _timedelta(hours=5, minutes=30)).strftime(fmt)
    except Exception:
        return ""

# ── Gmail send: SMTP + App Password (same mechanism as the other Bhookle
#    marketing tools — GMAIL_USER / GMAIL_APP_PASSWORD in .env). No OAuth. ──────
GMAIL_USER         = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = (os.getenv("GMAIL_APP_PASSWORD", "") or "").replace(" ", "")  # Google shows it with spaces

# Legacy OAuth constants kept only so the old (now-unused) auth routes still import.
GMAIL_SCOPES   = ["https://www.googleapis.com/auth/gmail.send"]
GMAIL_TOKEN    = os.path.join(os.path.dirname(__file__), "gmail_token.json")
GMAIL_CREDS    = os.path.join(os.path.dirname(__file__), "credentials.json")
GMAIL_REDIRECT = "http://localhost:5050/api/gmail/callback"


def _gmail_ready():
    """Sending is configured when we have a Gmail address + an app password."""
    return bool(GMAIL_USER and GMAIL_APP_PASSWORD)

# What the RECIPIENT sees as the attachment filename when a template has no
# display name stored. On disk the file keeps its UUID name.
DEFAULT_ATTACHMENT_NAME = "BhooklePitchAug.pdf"

ATTACHMENTS_DIR = os.path.join(os.path.dirname(__file__), "static", "attachments")
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)


def _gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    if not os.path.exists(GMAIL_TOKEN):
        raise RuntimeError("gmail_not_connected")
    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN, GMAIL_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GMAIL_TOKEN, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _make_message_id(lead_id):
    """A unique, thread-matchable Message-ID we stamp on each outgoing email.
    Replies carry this in their References/In-Reply-To headers → precise matching."""
    domain = (GMAIL_USER.split("@", 1)[1] if "@" in GMAIL_USER else "bhookle.com")
    return f"<bhookle-{lead_id}-{uuid.uuid4().hex}@{domain}>"


def _log_event(lead_id, event_type, status_at=None, status_to=None,
               template_stage=None, to_email=None, subject=None,
               message_id=None, detail=None):
    """Append a row to the outreach event log."""
    db.session.add(OutreachEvent(
        lead_id=lead_id, event_type=event_type, status_at=status_at,
        status_to=status_to, template_stage=template_stage, to_email=to_email,
        subject=(subject or "")[:500], message_id=message_id,
        detail=(detail or "")[:300]))


def _build_mime(to, subject, body, attachment_path=None, message_id=None,
                attachment_name=None):
    msg = MIMEMultipart()
    msg["From"]    = GMAIL_USER
    msg["To"]      = to
    msg["Subject"] = subject
    if message_id:
        msg["Message-ID"] = message_id
    msg.attach(MIMEText(body, "plain"))
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        email_encoders.encode_base64(part)
        # Files are stored on disk under a UUID name to prevent collisions and
        # path traversal — but the RECIPIENT must never see that. Send the
        # friendly display name instead (falling back to a sane default).
        shown = (attachment_name or "").strip() or DEFAULT_ATTACHMENT_NAME
        if "." not in shown:                       # keep the real extension
            shown += os.path.splitext(attachment_path)[1] or ".pdf"
        part.add_header("Content-Disposition", "attachment", filename=shown)
        msg.attach(part)
    return msg


def _send_via_gmail(to, subject, body, attachment_path=None, message_id=None,
                    attachment_name=None):
    """Send via Gmail SMTP using an App Password (smtp.gmail.com:465)."""
    import smtplib
    if not _gmail_ready():
        raise RuntimeError("gmail_not_connected")
    msg = _build_mime(to, subject, body, attachment_path, message_id=message_id,
                      attachment_name=attachment_name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [to], msg.as_string())


def _next_reached_out_status(prev_status):
    """Decide which 'in flight' bucket a freshly-sent lead belongs to.

    Forward path (New → first contact): -> "Reached Out"
    Backward path (re-engaging a Didn't Respond or Not Interested lead):
        -> "Reached Out Again"

    The two buckets diverge on the 5-day sync rule:
      Reached Out       + 5d → Didn't Respond
      Reached Out Again + 5d → Not Interested (reason: "Never responded")
    """
    if prev_status in ("Didn't Respond", "Not Interested"):
        return "Reached Out Again"
    return "Reached Out"


def _mark_sent(lead):
    today = date.today().strftime("%d %b %Y")
    note  = f"Email sent on {today}"
    lead.notes  = (lead.notes.rstrip() + f"\n{note}") if lead.notes else note
    lead.status = _next_reached_out_status(lead.status)


def _mark_linkedin_sent(lead, kind):
    """Record that a LinkedIn connection request / DM went out.

    Deliberately does NOT change lead.status: the founder works each lead across
    BOTH channels (LinkedIn + email) and moves it to 'Reached Out' by hand once
    both are done. Auto-advancing on the first touch hid the second one."""
    today = date.today().strftime("%d %b %Y")
    label = "connection request" if kind == "connect" else "message"
    note  = f"LinkedIn {label} sent on {today}"
    lead.notes = (lead.notes.rstrip() + f"\n{note}") if lead.notes else note


def _ensure_schema():
    """Idempotent mini-migration. db.create_all() adds missing TABLES but never
    new COLUMNS on a table that already exists, so columns introduced later
    (e.g. email_templates.stage / .locked) must be ALTERed in by hand. Safe to
    run on every boot; only ALTERs what's actually missing. Works on SQLite and
    Postgres."""
    from sqlalchemy import inspect as _inspect, text as _text
    insp = _inspect(db.engine)
    bool_default = "FALSE" if db.engine.dialect.name == "postgresql" else "0"
    wanted = {
        "email_templates": [
            ("stage",  "VARCHAR(40) DEFAULT 'generic'"),
            ("locked", f"BOOLEAN DEFAULT {bool_default}"),
        ],
        "investment_leads": [
            # Cached grounded news hook so personalisation is STABLE across re-composes.
            # NULL = never looked up; "" = looked up, found nothing; text = the hook.
            ("cached_news_hook", "TEXT"),
            # Classification of WHY a "Not Interested" lead rejected — see
            # REJECTION_REASONS for the canonical values. NULL = never classified.
            ("rejection_reason", "VARCHAR(40)"),
            # Pre-composed LinkedIn messages (parallel compose right after fetch).
            ("cached_li_connect", "TEXT"),
            ("cached_li_dm", "TEXT"),
            ("cached_li_basis", "TEXT"),
            ("cached_li_personalized", f"BOOLEAN DEFAULT {bool_default}"),
            ("cached_em_subject", "TEXT"),
            ("cached_em_body", "TEXT"),
            ("cached_em_basis", "TEXT"),
            ("cached_em_personalized", f"BOOLEAN DEFAULT {bool_default}"),
            ("contact_headline", "VARCHAR(300)"),
            ("evidence_url", "VARCHAR(600)"),
            ("evidence_note", "TEXT"),
            ("verified", f"BOOLEAN DEFAULT {bool_default}"),
            ("email_only_retry", f"BOOLEAN DEFAULT {bool_default}"),
        ],
    }
    applied = 0
    for table, cols in wanted.items():
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols:
            if name not in existing:
                db.session.execute(_text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                applied += 1
    if applied:
        db.session.commit()
        print(f"[schema] applied {applied} column migration(s)")


def seed_db():
    if InvestmentLead.query.count() == 0:
        for d in get_seed_data():
            lead = InvestmentLead(**{k: v for k, v in d.items() if hasattr(InvestmentLead, k)})
            db.session.add(lead)
        db.session.commit()
        print(f"[app] Seeded {InvestmentLead.query.count()} leads")


@app.route("/")
def index():
    status_filter = request.args.get("status", "")
    search = request.args.get("search", "")
    investor_type_filter = request.args.get("investor_type", "")
    tier_filter = request.args.get("tier", "")   # "1" or "2"

    query = InvestmentLead.query
    if status_filter:
        query = query.filter(InvestmentLead.status == status_filter)
    if investor_type_filter:
        query = query.filter(InvestmentLead.investor_type == investor_type_filter)
    if tier_filter == "1":
        query = query.filter(InvestmentLead.priority_tier.like("Tier 1%"))
    elif tier_filter == "2":
        query = query.filter(InvestmentLead.priority_tier.like("Tier 2%"))
    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(
            InvestmentLead.investor_name.ilike(like),
            InvestmentLead.invested_company.ilike(like),
            InvestmentLead.key_contact.ilike(like),
            InvestmentLead.sector.ilike(like),
        ))

    leads = query.order_by(
        db.func.coalesce(InvestmentLead.confidence_score, -1).desc(),
        InvestmentLead.id.desc(),
    ).all()
    total = InvestmentLead.query.count()

    status_counts = {s: InvestmentLead.query.filter_by(status=s).count()
                     for s in ["New", "Reached Out", "Reached Out Again",
                               "Engaged", "Didn't Respond", "Not Interested"]}

    tier_counts = {
        "1": InvestmentLead.query.filter(InvestmentLead.priority_tier.like("Tier 1%")).count(),
        "2": InvestmentLead.query.filter(InvestmentLead.priority_tier.like("Tier 2%")).count(),
    }

    investor_types = [r[0] for r in db.session.query(InvestmentLead.investor_type).distinct().all() if r[0]]

    # Set of lead IDs that have ever bounced — used to render the red "Bounced"
    # tag in the row. We keep the tag persistent (not only while status is "New")
    # so the user can spot historically-problematic addresses at a glance.
    bounced_ids = {row[0] for row in
                   db.session.query(OutreachEvent.lead_id)
                             .filter(OutreachEvent.event_type == "bounce")
                             .distinct().all()}

    return render_template(
        "index.html",
        leads=leads, total=total,
        status_counts=status_counts,
        tier_counts=tier_counts,
        investor_types=sorted(investor_types),
        current_status=status_filter,
        current_type=investor_type_filter,
        current_tier=tier_filter,
        search=search,
        bounced_ids=bounced_ids,
        rejection_reasons=REJECTION_REASONS,
    )


@app.route("/api/lead/<int:lead_id>/status", methods=["PATCH"])
def update_status(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json()
    allowed = ["New", "Reached Out", "Reached Out Again",
               "Engaged", "Didn't Respond", "Not Interested"]
    if data.get("status") not in allowed:
        return jsonify({"error": "Invalid status"}), 400
    lead.status = data["status"]
    db.session.commit()
    return jsonify({"ok": True, "status": lead.status})


@app.route("/api/leads/bulk-status", methods=["POST"])
def bulk_status_change():
    """Bulk lifecycle override. Set multiple selected leads to the same status in
    one shot. Each transition is logged as a "status_change" event with
    detail="Bulk status change" so the audit trail explains where the move came
    from. Leads already in the target status are silently skipped.

    Body: {"lead_ids": [int, ...], "status": "New"|"Reached Out"|...}
    """
    data = request.get_json() or {}
    lead_ids = data.get("lead_ids") or []
    new_status = (data.get("status") or "").strip()
    allowed = ["New", "Reached Out", "Reached Out Again",
               "Engaged", "Didn't Respond", "Not Interested"]
    if new_status not in allowed:
        return jsonify({"error": "Invalid status"}), 400
    if not lead_ids:
        return jsonify({"error": "No leads selected"}), 400

    leads = InvestmentLead.query.filter(InvestmentLead.id.in_(lead_ids)).all()
    updated, skipped = 0, 0
    for lead in leads:
        if lead.status == new_status:
            skipped += 1
            continue
        _log_event(lead.id, "status_change", status_at=lead.status,
                   status_to=new_status, detail="Bulk status change")
        lead.status = new_status
        updated += 1
    db.session.commit()
    return jsonify({"ok": True, "updated": updated, "skipped": skipped,
                    "total": len(leads), "new_status": new_status})


@app.route("/api/lead/<int:lead_id>/contacts", methods=["PATCH"])
def update_contacts(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json()
    if 'names' in data:
        lead.key_contact = ','.join(n for n in data['names'] if n)
    if 'emails' in data:
        lead.email = ','.join(e for e in data['emails'] if e)
    if 'linkedins' in data:
        lead.linkedin = ','.join(l for l in data['linkedins'] if l)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/lead/<int:lead_id>/followup", methods=["PATCH"])
def update_followup(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json()
    lead.follow_up_date = data.get("follow_up_date", "")
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/lead/<int:lead_id>/notes", methods=["PATCH"])
def update_notes(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json()
    lead.notes = data.get("notes", "")
    db.session.commit()
    return jsonify({"ok": True})


def _merge_csv(existing, new_vals):
    """Append new comma-separated values onto an existing CSV string, de-duped."""
    ex = [v.strip() for v in existing.split(",") if v.strip()] if existing else []
    for v in new_vals:
        if v and v not in ex:
            ex.append(v)
    return ",".join(ex)


@app.route("/api/lead/<int:lead_id>/enrich", methods=["POST"])
def enrich_lead(lead_id):
    """On-demand single-lead enrichment. Uses the full cascade INCLUDING the
    authenticated LinkedIn tier (About + Contact-info) as a last resort —
    gentle/throttled, single profile, since this fires only on a manual click."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    firm = lead.investor_name
    existing_kc = (lead.key_contact or "").strip()
    existing_li = (lead.linkedin or "").split(",")[0].strip() if lead.linkedin else ""

    new_email = ""
    new_name = ""
    new_li = ""
    try:
        # authenticated browser (li_at from .env) — on-demand only
        with google_browser(headless=True) as gb:
            if existing_kc:
                # we already know the person — chase THEIR email (auth LinkedIn ok)
                from enrich_engine import email_for_person
                new_email = email_for_person(
                    existing_kc.split(",")[0].strip(), firm,
                    browser=gb, linkedin_url=existing_li, allow_auth_li=True)
            else:
                res = smart_enrich(firm, want=1, browser=gb, allow_auth_li=True)
                if res["contacts"]:
                    c = res["contacts"][0]
                    new_email, new_name, new_li = c["email"], c["name"], c["linkedin"]
    except Exception as e:
        print(f"[enrich_lead] {firm}: {e}")

    if new_name:
        lead.key_contact = _merge_csv(lead.key_contact, [new_name])
    if new_email:
        lead.email = _merge_csv(lead.email, [new_email])
    if new_li:
        lead.linkedin = _merge_csv(lead.linkedin, [clean_linkedin(new_li)])
    db.session.commit()

    return jsonify({
        "ok": True,
        "email": new_email, "linkedin": new_li, "name": new_name,
        "has_email": bool((lead.email or "").strip()),
        "has_linkedin": bool((lead.linkedin or "").strip()),
        "complete": bool((lead.email or "").strip()) and bool((lead.linkedin or "").strip()),
    })


_enrich_status = {"running": False, "done": 0, "total": 0, "enriched": 0, "missing": [], "current_lead": ""}

@app.route("/api/enrich/batch", methods=["POST"])
def enrich_batch():
    """Enrich only NEW-status leads. Find verified email + LinkedIn for each;
    report any that remain incomplete so they can be flagged for manual lookup."""
    global _enrich_status
    if _enrich_status["running"]:
        return jsonify({"ok": False, "message": "Already running…"}), 409
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 400

    # Only leads in the "New" state, that are still missing email and/or linkedin.
    with app.app_context():
        leads = InvestmentLead.query.filter(InvestmentLead.status == "New").all()
        lead_ids = [
            (l.id, l.investor_name, l.investor_type)
            for l in leads
            if not (l.email or "").strip() or not (l.linkedin or "").strip()
        ]

    _enrich_status = {"running": True, "done": 0, "total": len(lead_ids), "enriched": 0, "missing": [], "current_lead": ""}

    if not lead_ids:
        _enrich_status["running"] = False
        return jsonify({"ok": True, "total": 0, "message": "All New leads already have email + LinkedIn 🎉"})

    import threading
    def run():
        global _enrich_status
        with app.app_context():
            for lead_id, name, itype in lead_ids:
                _enrich_status["current_lead"] = name
                try:
                    c = find_verified_contact(name, itype, api_key)
                    lead = InvestmentLead.query.get(lead_id)
                    if lead:
                        if c.get("name"):
                            lead.key_contact = _merge_csv(lead.key_contact, [c["name"]])
                        if c.get("email"):
                            lead.email = _merge_csv(lead.email, [c["email"]])
                        if c.get("linkedin"):
                            lead.linkedin = _merge_csv(lead.linkedin, [c["linkedin"]])
                        db.session.commit()
                        if c.get("email") or c.get("linkedin"):
                            _enrich_status["enriched"] += 1
                        # Flag anything still incomplete for manual follow-up
                        has_e = bool((lead.email or "").strip())
                        has_l = bool((lead.linkedin or "").strip())
                        if not (has_e and has_l):
                            miss = []
                            if not has_e: miss.append("email")
                            if not has_l: miss.append("linkedin")
                            _enrich_status["missing"].append({
                                "id": lead.id, "name": lead.investor_name, "missing": miss,
                            })
                except Exception as e:
                    print(f"[enrich] {name}: {e}")
                    _enrich_status["missing"].append({"id": lead_id, "name": name, "missing": ["email", "linkedin"]})
                _enrich_status["done"] += 1
        _enrich_status["current_lead"] = ""
        _enrich_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "total": len(lead_ids), "message": f"Enriching {len(lead_ids)} New leads…"})


@app.route("/api/enrich/status")
def enrich_status():
    return jsonify(_enrich_status)


@app.route("/api/lead/<int:lead_id>/recent", methods=["POST"])
def enrich_recent(lead_id):
    """Fetch recent investments for a single lead via Claude."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 400
    result = fetch_recent_investments(lead.investor_name, api_key)
    if result and result != "Data unavailable":
        lead.recent_investments = result
        db.session.commit()
    return jsonify({"ok": True, "recent_investments": result})


@app.route("/api/lead", methods=["POST"])
def add_lead():
    data = request.get_json()
    if not data.get("investor_name"):
        return jsonify({"error": "investor_name is required"}), 400
    lead = InvestmentLead(
        investor_name=data.get("investor_name", ""),
        investor_type=data.get("investor_type", ""),
        invested_company=data.get("invested_company", "—"),
        investment_amount=data.get("investment_amount", ""),
        round_type=data.get("round_type", ""),
        sector=data.get("sector", ""),
        deal_date=data.get("deal_date", ""),
        key_contact=data.get("key_contact", ""),
        email=data.get("email", ""),
        linkedin=data.get("linkedin", ""),
        source_url=data.get("source_url", ""),
        status="New",
    )
    db.session.add(lead)
    db.session.commit()
    return jsonify({"ok": True, "id": lead.id}), 201


@app.route("/api/lead/<int:lead_id>", methods=["DELETE"])
def delete_lead(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    return jsonify({"ok": True})


_refresh_status = {"running": False, "phase": "", "discovered": 0, "shortlisted": 0,
                   "classify_done": 0, "classify_total": 0, "ranked": 0,
                   "done": 0, "total": 0, "added": 0, "skipped": 0,
                   "current": "", "skipped_firms": [],
                   "added_names": [],        # firm names actually saved → shown in success toast
                   "eta_seconds": None,      # estimated seconds remaining (enrichment phase)
                   "elapsed_seconds": 0,     # seconds since enrichment phase started
                   "workers": 0,             # parallel enrichment browsers in use
                   }

REFRESH_LIMIT_DEFAULT = 10   # default if not specified by user
REFRESH_LIMIT_MAX     = 50   # hard cap
# The angels-only gate (angel + first-cheque + seed + consumer-fit + not-marquee)
# is deliberately strict — only ~1 in 8-10 classified candidates survives. So we
# must classify a LARGE shortlist to end up with `limit` qualified leads. Floor of
# 40 guarantees enough headroom even for a small requested count; capped so a big
# request doesn't fire hundreds of grounded classify calls.
REFRESH_SHORTLIST_MULTIPLIER = 8
REFRESH_SHORTLIST_FLOOR = 40
REFRESH_SHORTLIST_CAP   = 120


@app.route("/api/refresh", methods=["POST"])
def refresh_leads():
    """Multi-source SOURCING engine. Discovers candidate investors (news RSS,
    Gemini thesis, static funding corpus, look-alike), canonicalizes, suppresses
    known firms, hard-gates + scores them (stage/sector/recency), then enriches
    only the top-ranked survivors with a real D2C contact before inserting.
    Runs in the background; poll /api/refresh/status."""
    global _refresh_status
    if _refresh_status["running"]:
        return jsonify({"ok": False, "message": "Already fetching leads…"}), 409

    body = request.get_json(silent=True) or {}
    user_limit = int(body.get("limit", REFRESH_LIMIT_DEFAULT))
    user_limit = max(1, min(user_limit, REFRESH_LIMIT_MAX))
    # Gate relaxation level (0 strict angels / 1 early small-cheque funds /
    # 2 unknown-band tolerated). The D2C + seed + recency + not-marquee musts
    # hold at every level — see lead_scoring.passes_gates.
    relax = max(0, min(2, int(body.get("relax", 0))))
    shortlist  = min(REFRESH_SHORTLIST_CAP,
                     max(REFRESH_SHORTLIST_FLOOR, user_limit * REFRESH_SHORTLIST_MULTIPLIER))

    _refresh_status = {"running": True, "phase": "discovering", "discovered": 0,
                       "shortlisted": 0, "classify_done": 0, "classify_total": 0,
                       "ranked": 0, "done": 0, "total": 0, "added": 0,
                       "skipped": 0, "current": "", "skipped_firms": [],
                       "already_in_db": 0, "already_contacted": 0,
                       "already_not_interested": 0, "marquee": 0,
                       "compose_done": 0, "compose_total": 0,
                       "added_names": [], "eta_seconds": None, "elapsed_seconds": 0,
                       "workers": 0}

    # existing names + status map for full cross-status suppression ("Is Already There?")
    with app.app_context():
        from lead_scoring import norm_key as _nk
        all_rows = db.session.query(InvestmentLead.investor_name, InvestmentLead.status).all()
        existing = [n for n, _ in all_rows]
        existing_with_status = {_nk(n): s for n, s in all_rows}

        # Belt-and-braces guard for the "Not Interested" set: besides the name
        # key match above, capture their contact emails + domains so a rejected
        # investor can't slip back in under a slightly different firm label once
        # enrichment discovers the same person/inbox.
        ni_rows = (db.session.query(InvestmentLead.investor_name, InvestmentLead.email)
                   .filter(InvestmentLead.status == "Not Interested").all())
        ni_name_keys = {_nk(n) for n, _ in ni_rows}
        ni_emails, ni_domains = set(), set()
        for _, em in ni_rows:
            for e in (em or "").replace(";", ",").split(","):
                e = e.strip().lower()
                if "@" in e:
                    ni_emails.add(e)
                    ni_domains.add(e.split("@", 1)[1])

        # "Never re-contact anyone — or any COMPANY — I've already reached out to."
        # A lead counts as contacted once it leaves 'New'. We capture, for every
        # contacted lead, the COMPANY (investor_name) + every PERSON (key_contact,
        # and investor_name itself for solo angels) + their LinkedIn handle, so a
        # discovered candidate that turns out to be the same person or the same
        # firm — even under a different label — is dropped post-enrichment.
        CONTACTED = {"Reached Out", "Reached Out Again", "Engaged",
                     "Didn't Respond", "Not Interested"}
        contacted_rows = (db.session.query(
            InvestmentLead.investor_name, InvestmentLead.key_contact,
            InvestmentLead.linkedin, InvestmentLead.status).all())
        contacted_person_keys, contacted_firm_keys, contacted_li = set(), set(), set()

        def _li_slug(url):
            m = re.search(r"/in/([^/?#\s]+)", (url or "").lower())
            return m.group(1).strip("-") if m else ""

        contacted_person_names = []   # raw names → fed to discovery suppression
        for name, kc, li, st in contacted_rows:
            if st not in CONTACTED:
                continue
            contacted_firm_keys.add(_nk(name))
            contacted_person_keys.add(_nk(name))            # solo angels: name == person
            contacted_person_names.append(name)
            for p in (kc or "").split(","):
                if p.strip():
                    contacted_person_keys.add(_nk(p))
                    contacted_person_names.append(p.strip())
            for u in (li or "").replace(";", ",").split(","):
                s = _li_slug(u)
                if s:
                    contacted_li.add(s)
        contacted_person_keys.discard("")
        contacted_firm_keys.discard("")

        # Suppress already-contacted PEOPLE at discovery too (not just post-enrich):
        # angel candidates surface as person-named firms, so feeding these names in
        # drops them before they waste a classify/enrich slot. Mark them contacted
        # so the funnel counts them correctly.
        existing = existing + contacted_person_names
        for nm in contacted_person_names:
            existing_with_status.setdefault(_nk(nm), "Reached Out")

    import threading
    def run():
        global _refresh_status
        import time as _time
        _qual_clock = {"start": None}   # wall-clock start of the qualifying phase

        def progress(stage, kw):
            if stage == "discovered":   _refresh_status["discovered"] = kw.get("count", 0)
            elif stage == "suppressed":
                _refresh_status["already_in_db"] = kw.get("already_in_db", 0)
                _refresh_status["already_contacted"] = kw.get("already_contacted", 0)
                _refresh_status["already_not_interested"] = kw.get("already_not_interested", 0)
                _refresh_status["marquee"] = kw.get("marquee", 0)
            elif stage == "shortlisted": _refresh_status["shortlisted"] = kw.get("count", 0)
            elif stage == "classifying":
                done  = kw.get("done", 0)
                total = kw.get("total", 0)
                _refresh_status["phase"] = "qualifying"
                _refresh_status["classify_done"] = done
                _refresh_status["classify_total"] = total
                # ── ETA for the qualifying phase ──
                # Start the clock on the first classified firm, then project the
                # remaining time from the average time-per-firm so far.
                if _qual_clock["start"] is None:
                    _qual_clock["start"] = _time.time()
                elapsed = _time.time() - _qual_clock["start"]
                if done > 0 and total > done and elapsed > 0:
                    avg = elapsed / done
                    _refresh_status["eta_seconds"] = round(avg * (total - done))
                else:
                    _refresh_status["eta_seconds"] = 0
            elif stage == "scored":
                _refresh_status["ranked"] = kw.get("count", 0)
                _refresh_status["eta_seconds"] = None   # reset before enrichment phase

        from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac
        _lock = threading.Lock()

        try:
            # ── Phase 1: discover + score + rank (no browser needed) ──
            ranked = engine_get_leads(limit=user_limit, shortlist=shortlist,
                                      existing_names=existing,
                                      existing_with_status=existing_with_status,
                                      progress=progress, relax=relax)
            _refresh_status["total"] = len(ranked)
            _refresh_status["phase"] = "enriching"
            enrich_start = _time.time()

            # ── Phase 2: parallel enrichment ──────────────────────────────────
            # NOTE: LinkedIn hard-blocks automated access to its /search/ endpoint
            # (redirect loop) even with a valid li_at cookie, so server-side profile
            # search is impossible. Instead, leads are stored with name + portfolio
            # company, and the compose flow opens a PRECISE name+company LinkedIn
            # search in the user's real (logged-in) browser — which LinkedIn allows.
            # The li_at cookie is still passed for what DOES work server-side:
            # reading a known profile's Contact-info overlay during enrichment.
            _li_at = (os.getenv("LINKEDIN_LI_AT", "") or "").strip()
            ENRICH_WORKERS = min(4, max(1, len(ranked)))  # parallel headless browsers
            _refresh_status["workers"] = ENRICH_WORKERS
            item_times = []   # rolling history of seconds-per-item for ETL

            def enrich_one(d, worker_id):
                """Run smart_enrich for one lead, return enriched dict or None."""
                t0 = _time.time()
                name = d["investor_name"]
                with google_browser(headless=True, li_at=_li_at) as gb:
                    try:
                        # PERSON-mode for individual angels/HNIs (find THEIR own /in/
                        # profile); FIRM-mode for funds/networks (find people AT them).
                        is_person = looks_like_individual(name, d.get("investor_type", ""))
                        if is_person:
                            # name + their portfolio company → precise LinkedIn match
                            res = enrich_person(name, browser=gb,
                                                context=d.get("invested_company", ""))
                        else:
                            res = smart_enrich(name, want=2, browser=gb)
                        # LinkedIn-FIRST but name-search-based: outreach opens a LinkedIn
                        # search for the contact's NAME, so a verified /in/ URL is a bonus,
                        # not a requirement. PREFER a real /in/ when we have one; otherwise
                        # keep the lead on the (grounded) name — for a PERSON candidate the
                        # name itself is the contact; for a FIRM we still need a named
                        # contact person to search for.
                        with_in = [c for c in res["contacts"]
                                   if c["name"] and "/in/" in (c["linkedin"] or "")]
                        if with_in:
                            usable = with_in
                        elif is_person:
                            usable = [c for c in res["contacts"] if c["name"]]
                        else:
                            usable = [c for c in res["contacts"]
                                      if c["name"] or c["email"]]
                        if not usable:
                            return d, None, f"{name} (no contact found)", _time.time() - t0

                        # Post-enrichment "Not Interested" guard: if the contact we
                        # just discovered points at an inbox/domain already on a
                        # rejected lead, drop it — the name key alone missed it.
                        emails = [c["email"].strip().lower() for c in usable if c["email"]]
                        if any(e in ni_emails or e.split("@", 1)[1] in ni_domains
                               for e in emails if "@" in e):
                            return d, None, f"{name} (already Not Interested)", _time.time() - t0

                        # "Already contacted" guard — never re-surface a PERSON or a
                        # COMPANY I've already reached out to, even under a new label.
                        cand_person_keys = {_nk(c["name"]) for c in usable if c["name"]}
                        cand_li = set()
                        for c in usable:
                            mm = re.search(r"/in/([^/?#\s]+)", (c["linkedin"] or "").lower())
                            if mm:
                                cand_li.add(mm.group(1).strip("-"))
                        if (_nk(name) in contacted_firm_keys
                                or cand_person_keys & contacted_person_keys
                                or cand_li & contacted_li):
                            return d, None, f"{name} (already contacted)", _time.time() - t0

                        # ── HARD VERIFICATION GATE ──
                        # Nothing becomes a lead on an LLM's say-so. We require a
                        # credible source that names THIS investor in a REAL deal,
                        # and we re-derive the company's true sector from that
                        # source (this is what catches a cybersecurity company
                        # mislabelled as a "food thesis match").
                        ev = verify_lead_evidence(name, d.get("invested_company", ""))
                        if not ev["verified"]:
                            return d, None, f"{name} (unverified: {ev['reason'][:40]})", _time.time() - t0
                        if not ev["is_consumer_food"]:
                            return (d, None,
                                    f"{name} (not consumer/food: {ev['company_sector'][:26]})",
                                    _time.time() - t0)

                        d2 = dict(d)
                        d2["key_contact"] = ",".join(c["name"] for c in usable if c["name"])
                        d2["email"]       = ",".join(c["email"] for c in usable if c["email"])
                        d2["linkedin"]    = ",".join(clean_linkedin(c["linkedin"]) for c in usable if c["linkedin"])
                        d2["evidence_url"]  = ev["evidence_url"]
                        d2["evidence_note"] = ev["evidence_note"]
                        d2["verified"]      = True
                        # Trust the SOURCED sector over the discovery-time guess.
                        if ev["company_sector"]:
                            d2["sector"] = ev["company_sector"][:200]
                        d2.pop("_classify", None)
                        return d2, True, None, _time.time() - t0
                    except Exception as e:
                        print(f"[refresh:w{worker_id}] {name}: {e}")
                        return d, None, f"{name} (error)", _time.time() - t0

            added_ids = []   # newly-inserted lead ids → parallel message pre-compose
            with app.app_context():
                with _TPE(max_workers=ENRICH_WORKERS) as ex:
                    futs = {ex.submit(enrich_one, d, i % ENRICH_WORKERS): d
                            for i, d in enumerate(ranked)}
                    for fut in _ac(futs):
                        try:
                            d2, ok, skip_reason, elapsed = fut.result()
                        except Exception:
                            with _lock:
                                _refresh_status["skipped"] += 1
                                _refresh_status["done"] += 1
                            continue

                        with _lock:
                            item_times.append(elapsed)
                            if ok:
                                lead = InvestmentLead(
                                    **{k: v for k, v in d2.items() if hasattr(InvestmentLead, k)})
                                db.session.add(lead)
                                db.session.commit()
                                added_ids.append(lead.id)
                                _refresh_status["added"] += 1
                                _refresh_status["added_names"].append(d2["investor_name"])
                            else:
                                _refresh_status["skipped"] += 1
                                _refresh_status["skipped_firms"].append(skip_reason or "")
                            _refresh_status["done"] += 1
                            _refresh_status["current"] = d2.get("investor_name", "")
                            _refresh_status["elapsed_seconds"] = round(_time.time() - enrich_start)
                            # ETL: avg seconds per item × items remaining
                            remaining = _refresh_status["total"] - _refresh_status["done"]
                            if item_times and remaining > 0:
                                avg = sum(item_times) / len(item_times)
                                _refresh_status["eta_seconds"] = round(avg * remaining / ENRICH_WORKERS)
                            else:
                                _refresh_status["eta_seconds"] = 0

            # ── Phase 3: parallel message pre-compose ─────────────────────────
            # Write the personalised connect note + DM for every new lead NOW
            # (Claude + cached news hook), so the compose modal opens instantly
            # instead of making the user wait after clicking Message.
            if added_ids:
                _refresh_status["phase"] = "composing"
                _refresh_status["compose_total"] = len(added_ids)
                _refresh_status["compose_done"] = 0

                def compose_one(lid):
                    with app.app_context():
                        try:
                            l = InvestmentLead.query.get(lid)
                            if l:
                                _refresh_status["current"] = l.investor_name
                                _compose_and_cache_linkedin(l)
                        except Exception as e:
                            print(f"[refresh:compose] lead {lid}: {e}")

                with _TPE(max_workers=5) as ex:
                    for _ in ex.map(compose_one, added_ids):
                        with _lock:
                            _refresh_status["compose_done"] += 1

        except Exception as e:
            print(f"[refresh] fatal: {e}")
        _refresh_status["current"] = ""
        _refresh_status["phase"] = "done"
        _refresh_status["eta_seconds"] = 0
        _refresh_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "total": user_limit,
                    "message": f"Scouting up to {user_limit} reachable India D2C/consumer/food angels on LinkedIn…"})


@app.route("/api/refresh/status")
def refresh_status():
    return jsonify(_refresh_status)


@app.route("/api/export")
def export_csv():
    leads = InvestmentLead.query.order_by(InvestmentLead.id.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Investor Name", "Type", "Invested Company", "Amount", "Round",
        "Sector", "Deal Date", "Key Contact", "Email", "LinkedIn",
        "Recent Investments", "Status", "Notes", "Source"
    ])
    for l in leads:
        writer.writerow([
            l.investor_name, l.investor_type, l.invested_company,
            l.investment_amount, l.round_type, l.sector, l.deal_date,
            l.key_contact, l.email, l.linkedin,
            l.recent_investments or "", l.status, l.notes or "", l.source_url or ""
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=bhookle_investment_leads.csv"},
    )


# ── Gmail OAuth2 setup ───────────────────────────────────────────────────────

@app.route("/api/gmail/status")
def gmail_status():
    ready = _gmail_ready()
    return jsonify({"connected": ready, "has_credentials_json": ready,
                    "method": "app_password", "user": GMAIL_USER if ready else "",
                    "redirect_uri": GMAIL_REDIRECT})


@app.route("/api/gmail/credentials", methods=["POST"])
def upload_gmail_credentials():
    """Accept the user's Google OAuth client file (credentials.json) via the UI,
    so they never have to drop it in the project root by hand or restart. The auth
    flow reads it fresh each time, so it's usable immediately after upload."""
    import json as _json
    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"error": "Choose your credentials.json file"}), 400
    raw = request.files["file"].read()
    try:
        data = _json.loads(raw)
    except Exception:
        return jsonify({"error": "That file isn't valid JSON"}), 400
    if not (isinstance(data, dict) and ("web" in data or "installed" in data)):
        return jsonify({"error": "Not a Google OAuth client file (missing 'web'/'installed' key). "
                                 "Download it from Google Cloud Console → Credentials."}), 400
    try:
        with open(GMAIL_CREDS, "wb") as f:
            f.write(raw)
    except Exception as e:
        return jsonify({"error": f"Could not save: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/api/gmail/auth")
def gmail_auth():
    from google_auth_oauthlib.flow import Flow
    if not os.path.exists(GMAIL_CREDS):
        return jsonify({"error": "credentials.json not found"}), 400
    flow = Flow.from_client_secrets_file(GMAIL_CREDS, scopes=GMAIL_SCOPES, redirect_uri=GMAIL_REDIRECT)
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/api/gmail/callback")
def gmail_callback():
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        GMAIL_CREDS, scopes=GMAIL_SCOPES,
        redirect_uri=GMAIL_REDIRECT, state=session.get("oauth_state"),
    )
    flow.fetch_token(authorization_response=request.url)
    with open(GMAIL_TOKEN, "w") as f:
        f.write(flow.credentials.to_json())
    return redirect("/?gmail=connected")


@app.route("/api/gmail/disconnect", methods=["POST"])
def gmail_disconnect():
    if os.path.exists(GMAIL_TOKEN):
        os.remove(GMAIL_TOKEN)
    return jsonify({"ok": True})


# ── Outreach message templates CRUD ──────────────────────────────────────────
# Legacy email stages (new/didnt_respond/not_interested/generic) are retained so
# old rows still validate, plus the two LinkedIn message types the UI now uses:
#   li_connect — the ≤300-char connection-request note
#   li_dm      — the full direct message (after they accept / already connected)
VALID_STAGES = {"new", "didnt_respond", "not_interested", "generic",
                "li_connect", "li_dm"}

# Fallback base copy so the composer works even before the user has saved their
# own LinkedIn templates. Real traction figures are masked as [X] placeholders in this public copy.
DEFAULT_LI_CONNECT = (
    "Hi {investor_name}, I'm Arvind — founder of Bhookle, the \"Airbnb of "
    "home-cooked food.\" Fully bootstrapped to [X]K+ meals, [N] chefs & ₹[X] GOV "
    "across [City A] & [City B], [X]% word-of-mouth. Raising ₹[X] Cr to launch [N] "
    "new cities — keen to connect before we close. — Arvind"
)
DEFAULT_LI_DM = (
    "Hi {investor_name} — thanks for connecting.\n\n"
    "I'm Arvind, founder of Bhookle — the \"Airbnb of home-cooked food.\" Two years "
    "in, fully bootstrapped, and the traction speaks for itself:\n\n"
    "• [X]K+ meals to [X]K+ customers — [X]% repeat\n"
    "• [N] home chefs, ₹[X] Cr already paid out to them\n"
    "• ₹[X] GOV across 3 live revenue engines: B2C, subscriptions & B2B catering\n"
    "• [X]% word-of-mouth, [X]% conversion — on near-zero paid marketing\n\n"
    "We're raising ₹[X] Cr to scale into [N] new cities and the round is filling fast. "
    "I'd genuinely value 20 minutes this week before allocation closes — I'll send "
    "the deck ahead so we go straight to substance.\n\n"
    "Founding story (3 min): <founding-story-video-link>\n\n"
    "— Arvind"
)


@app.route("/api/templates", methods=["GET"])
def list_templates():
    """List templates, optionally filtered by ?stage=new|didnt_respond|not_interested|generic"""
    q = EmailTemplate.query
    stage = request.args.get("stage", "")
    if stage in VALID_STAGES:
        q = q.filter_by(stage=stage)
    templates = q.order_by(EmailTemplate.id.asc()).all()
    return jsonify([t.to_dict() for t in templates])


@app.route("/api/templates", methods=["POST"])
def create_template():
    data = request.get_json()
    if not data.get("name") or not data.get("body"):
        return jsonify({"error": "name and body are required"}), 400
    stage = data.get("stage", "generic")
    if stage not in VALID_STAGES:
        stage = "generic"
    t = EmailTemplate(
        name=data["name"],
        subject=data.get("subject", ""),
        body=data["body"],
        stage=stage,
        locked=bool(data.get("locked", False)),
    )
    db.session.add(t)
    _invalidate_li_cache_if_needed(stage)
    db.session.commit()
    return jsonify({"ok": True, "id": t.id}), 201


def _invalidate_li_cache_if_needed(stage):
    """Base LinkedIn copy changed → every pre-composed message is stale. Clear the
    cache so the next open (or fetch pre-compose) rebuilds from the new base."""
    if stage in ("li_connect", "li_dm"):
        InvestmentLead.query.update({
            InvestmentLead.cached_li_connect: None,
            InvestmentLead.cached_li_dm: None,
            InvestmentLead.cached_li_basis: None,
            InvestmentLead.cached_li_personalized: None,
        })
    else:
        # An email template changed → every pre-composed email is stale.
        InvestmentLead.query.update({
            InvestmentLead.cached_em_subject: None,
            InvestmentLead.cached_em_body: None,
            InvestmentLead.cached_em_basis: None,
            InvestmentLead.cached_em_personalized: None,
        })


@app.route("/api/templates/<int:tid>", methods=["PUT"])
def update_template(tid):
    t = EmailTemplate.query.get_or_404(tid)
    data = request.get_json()
    t.name    = data.get("name",    t.name)
    t.subject = data.get("subject", t.subject)
    t.body    = data.get("body",    t.body)
    if "stage" in data and data["stage"] in VALID_STAGES:
        t.stage = data["stage"]
    if "locked" in data:
        t.locked = bool(data["locked"])
    _invalidate_li_cache_if_needed(t.stage)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/templates/ai-improve", methods=["POST"])
def ai_improve_template():
    """AI template maker. Paste a rough draft + target stage → Claude returns a
    tightened, stage-appropriate, voice-preserving template (<300 words) for the
    founder to REVIEW before saving. Does not persist anything."""
    data = request.get_json() or {}
    raw_body = (data.get("body") or "").strip()
    if not raw_body:
        return jsonify({"error": "Paste a draft body to improve"}), 400
    stage = data.get("stage", "generic")
    if stage not in VALID_STAGES:
        stage = "generic"
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 400

    result = improve_template(data.get("subject", ""), raw_body, stage, api_key)
    if not result:
        return jsonify({"error": "AI failed to improve the draft — try again"}), 500
    return jsonify({"ok": True, "stage": stage, **result})


@app.route("/api/templates/<int:tid>", methods=["DELETE"])
def delete_template(tid):
    t = EmailTemplate.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    return jsonify({"ok": True})


# ── LinkedIn outreach: compose + mark-sent ───────────────────────────────────

def _lead_ctx(lead):
    """The grounding context passed to the personalisers (email + LinkedIn)."""
    return {
        "investor_name":      lead.investor_name,
        "key_contact":        lead.key_contact or "",
        "investor_type":      lead.investor_type or "",
        "invested_company":   lead.invested_company or "",
        "sector":             lead.sector or "",
        "recent_investments": lead.recent_investments or "",
        "trigger_signals":    lead.trigger_signals or "",
        "action_item":        lead.action_item or "",
    }


def _cached_news_hook(lead):
    """Reuse the per-lead cached grounded hook; look it up once if never checked.
    Mirrors draft_email so LinkedIn copy is grounded the same way. Best-effort."""
    if lead.cached_news_hook is not None:
        return lead.cached_news_hook          # "" = checked-but-none; text = hook
    hook = ""
    try:
        from enrich_engine import recent_news_hook
        hook = recent_news_hook(lead.investor_name) or ""
    except Exception as e:
        print(f"[linkedin] news hook: {e}")
    lead.cached_news_hook = hook
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return hook


def _li_base(stage, fallback):
    """The user's saved LinkedIn base copy for a stage, else the built-in default."""
    t = (EmailTemplate.query.filter_by(stage=stage)
         .order_by(EmailTemplate.locked.desc(), EmailTemplate.id.asc()).first())
    return t.body if (t and (t.body or "").strip()) else fallback


def _contact_differs_from_firm(lead):
    """True when the contact is a PERSON AT a firm (so the firm name is on their
    LinkedIn profile and is a safe search disambiguator). False for solo angels,
    where lead name == contact name and there's no employer to match on."""
    kc = (lead.key_contact or "").split(",")[0].strip().lower()
    return bool(kc) and kc != (lead.investor_name or "").strip().lower()


def _li_search_context(lead):
    """Pick a disambiguator that actually appears ON the person's LinkedIn profile.

    Priority:
      1. Employer parsed from contact_headline ("SVP at Flipkart" → "Flipkart")
      2. The firm they work at (only when the contact is a person AT a firm)
      3. Nothing — bare-name search (correct for solo angels; a portfolio company
         is NOT on their profile and would return zero results)
    """
    headline = (lead.contact_headline or "").strip()
    if headline:
        m = re.search(r"\b(?:at|@|,)\s+(.+)$", headline)
        employer = (m.group(1) if m else headline).strip(" .,|-")
        # keep it short — long strings over-constrain LinkedIn's search
        if employer and len(employer) <= 40:
            return employer
    if _contact_differs_from_firm(lead):
        return (lead.investor_name or "").strip()
    return ""


def _compose_and_cache_linkedin(lead, force=False, use_news=True):
    """Compose (or serve the cached) LinkedIn connect note + DM for a lead.
    The cache is written at fetch time by a parallel pre-compose pass so the
    modal opens instantly; force=True recomposes and refreshes the cache."""
    if not force and ((lead.cached_li_connect or "").strip()
                      or (lead.cached_li_dm or "").strip()):
        return {"connect_note": lead.cached_li_connect or "",
                "dm": lead.cached_li_dm or "",
                "personalized": bool(lead.cached_li_personalized),
                "basis": (lead.cached_li_basis or "") + " ⚡ (pre-composed)"}

    connect_base = _li_base("li_connect", DEFAULT_LI_CONNECT)
    dm_base      = _li_base("li_dm", DEFAULT_LI_DM)
    ctx = _lead_ctx(lead)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    news_hook = _cached_news_hook(lead) if (api_key and use_news) else ""

    if api_key:
        res = compose_linkedin(ctx, connect_base, dm_base, api_key, news_hook=news_hook)
    else:
        # No API key → deterministic placeholder merge only (never invents).
        from scraper import _merge_placeholders
        res = {"connect_note": _merge_placeholders(connect_base, ctx)[:LINKEDIN_CONNECT_MAX],
               "dm": _merge_placeholders(dm_base, ctx),
               "personalized": False, "confidence": 0,
               "basis": "ANTHROPIC_API_KEY not set — used your base copy as-is."}

    lead.cached_li_connect      = res["connect_note"]
    lead.cached_li_dm           = res["dm"]
    lead.cached_li_basis        = res["basis"]
    lead.cached_li_personalized = bool(res["personalized"])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return res


@app.route("/api/lead/<int:lead_id>/linkedin", methods=["POST"])
def linkedin_compose(lead_id):
    """Compose the two LinkedIn messages for a lead — a ≤300-char connection note
    and a full DM — personalised under the same anti-guess gate as email. Served
    from the pre-composed cache when available (instant). The user picks one,
    copies it, and pastes it into LinkedIn themselves (no send API)."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json(silent=True) or {}
    li_url = (lead.linkedin or "").split(",")[0].strip()

    res = _compose_and_cache_linkedin(lead, force=bool(data.get("force")),
                                      use_news=data.get("use_news", True))

    return jsonify({
        "ok": True,
        "connect_note": res["connect_note"],
        "dm":           res["dm"],
        "linkedin_url": li_url,
        "has_linkedin": bool(li_url),
        "personalized": res["personalized"],
        "basis":        res["basis"],
        "connect_max":  LINKEDIN_CONNECT_MAX,
        "investor_name": lead.investor_name,
        "key_contact":  (lead.key_contact or "").split(",")[0].strip(),
        # LinkedIn people-search only matches text ON the profile. Best
        # disambiguator is the person's EMPLOYER (from contact_headline, e.g.
        # "SVP at Flipkart"); next best is the firm they work at. A PORTFOLIO
        # company is never on their profile — searching it returns zero results.
        "search_context": _li_search_context(lead),
        # Extra identifying facts for the UI + the Google fallback (Google CAN
        # match a portfolio company since it indexes news, unlike LinkedIn).
        "portfolio_co": (lead.invested_company or "").strip().strip("—-"),
        "investor_type_label": (lead.investor_type or "").strip(),
        "headline": (lead.contact_headline or "").strip(),
    })


@app.route("/api/lead/<int:lead_id>/linkedin/profile", methods=["POST"])
def linkedin_save_profile(lead_id):
    """Save the RIGHT person's LinkedIn profile URL (and optionally their
    role/employer) once the user has identified them. This turns a repeated
    'which of these 8 same-name people is mine?' hunt into a one-time cost —
    every later open goes straight to the profile."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json(silent=True) or {}
    url = clean_linkedin((data.get("url") or "").strip())
    if not url or "/in/" not in url:
        return jsonify({"error": "Paste a linkedin.com/in/… profile URL"}), 400

    # Put the confirmed profile first; keep any others we already had.
    others = [u.strip() for u in (lead.linkedin or "").replace(";", ",").split(",")
              if u.strip() and u.strip().rstrip("/") != url.rstrip("/")]
    lead.linkedin = ",".join([url] + others)
    headline = (data.get("headline") or "").strip()
    if headline:
        lead.contact_headline = headline[:300]
    lead.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "linkedin": url,
                    "headline": lead.contact_headline or ""})


@app.route("/api/lead/<int:lead_id>/linkedin/mark", methods=["POST"])
def linkedin_mark(lead_id):
    """Record that the user sent a LinkedIn connection note / DM (they paste+send
    it themselves). Logs an outreach event for the Report and stamps a note, but
    leaves status alone — the founder moves the lead to 'Reached Out' manually
    once BOTH channels (LinkedIn + email) are done."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json(silent=True) or {}
    kind = "dm" if data.get("type") == "dm" else "connect"
    li_url = (lead.linkedin or "").split(",")[0].strip()

    status_before = lead.status
    _mark_linkedin_sent(lead, kind)
    _log_event(lead_id, "sent", status_at=status_before, status_to=lead.status,
               template_stage=("li_dm" if kind == "dm" else "li_connect"),
               to_email=li_url, subject=f"LinkedIn {kind}",
               detail=f"LinkedIn {'message' if kind == 'dm' else 'connection request'} sent")
    lead.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "status": lead.status})


@app.route("/api/lead/<int:lead_id>/email/compose", methods=["POST"])
def email_compose(lead_id):
    """Build the outreach EMAIL for a lead — subject + body + the attached deck.

    Reuses the same personalisation engine as LinkedIn, so the email carries the
    same verified hook. Returns a draft for review; nothing is sent here."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json(silent=True) or {}
    template, stage = _pick_template_for_lead(lead)
    if not template:
        return jsonify({"error": "No email template saved yet"}), 400

    # Serve the pre-composed email when we have one — a live Claude call cost
    # ~8s on every modal open, which is what made the Email button feel broken.
    if not data.get("force") and (lead.cached_em_body or "").strip():
        res = {"subject": lead.cached_em_subject or (template.subject or ""),
               "body": lead.cached_em_body,
               "personalized": bool(lead.cached_em_personalized),
               "basis": (lead.cached_em_basis or "") + " ⚡ (pre-composed)"}
    else:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        news_hook = _cached_news_hook(lead) if (api_key and data.get("use_news", True)) else ""
        ctx = _lead_ctx(lead)
        if api_key:
            res = personalize_email(ctx, template.subject or "", template.body,
                                    api_key, news_hook=news_hook)
        else:
            from scraper import _merge_placeholders
            res = {"subject": _merge_placeholders(template.subject or "", ctx),
                   "body": _merge_placeholders(template.body, ctx),
                   "personalized": False, "confidence": 0,
                   "basis": "ANTHROPIC_API_KEY not set — used your template as-is."}
        lead.cached_em_subject      = res["subject"]
        lead.cached_em_body         = res["body"]
        lead.cached_em_basis        = res["basis"]
        lead.cached_em_personalized = bool(res["personalized"])
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    emails = [e.strip() for e in (lead.email or "").replace(";", ",").split(",") if e.strip()]
    return jsonify({
        "ok": True,
        "to": emails[0] if emails else "",
        "all_emails": emails,
        "subject": res["subject"] or template.subject or "",
        "body": res["body"],
        "personalized": res["personalized"],
        "basis": res["basis"],
        "template_id": template.id,
        "attachment": template.attachment_name or "",
        "investor_name": lead.investor_name,
        "key_contact": (lead.key_contact or "").split(",")[0].strip(),
        "gmail_ready": _gmail_ready(),
    })


# lead_id → {state: queued|sent|failed, to, error, at}. In-memory; the durable
# record is the lead's notes + the outreach event log.
_email_send_status = {}


@app.route("/api/lead/<int:lead_id>/email/send", methods=["POST"])
def email_send(lead_id):
    """Queue the outreach email and return IMMEDIATELY.

    The actual SMTP upload is ~3.6MB (a 2.7MB deck grows 35% under base64), which
    blocked the request for 15-30s on a normal uplink and made the UI look frozen
    or self-driving. We now hand off to a background thread and report progress
    via /email/status, so the founder can move to the next lead at once.

    Status is deliberately NOT changed — the founder advances the lead by hand
    once both LinkedIn and email are done."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json(silent=True) or {}
    to_email = (data.get("to") or "").strip()
    subject  = (data.get("subject") or "").strip()
    body     = (data.get("body") or "").strip()
    if not to_email:
        return jsonify({"error": "No recipient email — enrich or add one first"}), 400
    if not (subject and body):
        return jsonify({"error": "Subject and body are required"}), 400
    if not _gmail_ready():
        return jsonify({"error": "Gmail not configured (GMAIL_USER / "
                                 "GMAIL_APP_PASSWORD missing in .env)"}), 400

    attachment_path = attachment_name = None
    tid = data.get("template_id")
    if tid:
        t = EmailTemplate.query.get(tid)
        if t and t.attachment_path:
            attachment_path = t.attachment_path
            attachment_name = t.attachment_name      # friendly name for the recipient

    msg_id = _make_message_id(lead_id)
    _email_send_status[lead_id] = {"state": "queued", "to": to_email, "error": ""}

    import threading

    def _worker():
        try:
            _send_via_gmail(to_email, subject, body, attachment_path,
                            message_id=msg_id, attachment_name=attachment_name)
        except Exception as e:
            _email_send_status[lead_id] = {"state": "failed", "to": to_email,
                                           "error": str(e)[:200]}
            print(f"[email_send] lead {lead_id} → {to_email}: {e}")
            return
        with app.app_context():
            try:
                l = InvestmentLead.query.get(lead_id)
                if l:
                    today = date.today().strftime("%d %b %Y")
                    note = f"Email sent on {today} to {to_email}"
                    l.notes = (l.notes.rstrip() + f"\n{note}") if l.notes else note
                    _log_event(lead_id, "sent", status_at=l.status, status_to=l.status,
                               template_stage="email", to_email=to_email,
                               subject=subject, message_id=msg_id,
                               detail="Email sent (status unchanged)")
                    l.updated_at = datetime.utcnow()
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"[email_send] post-send bookkeeping failed for {lead_id}: {e}")
        _email_send_status[lead_id] = {"state": "sent", "to": to_email, "error": ""}

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"ok": True, "queued": True, "to": to_email,
                    "status": lead.status, "attached": bool(attachment_path)})


@app.route("/api/lead/<int:lead_id>/email/status")
def email_send_status(lead_id):
    """Poll the outcome of a queued send (queued | sent | failed | unknown)."""
    return jsonify(_email_send_status.get(lead_id, {"state": "unknown"}))


# ── AI Email Draft Generation ────────────────────────────────────────────────

def _pick_template_for_lead(lead):
    """Auto-select the right template for a lead by its status → stage, preferring
    a LOCKED template. Falls back to a generic template, then to any template.
    Returns (template_or_None, stage)."""
    stage = EmailTemplate.STATUS_TO_STAGE.get(lead.status or "New")

    def _first(query):
        return query.order_by(EmailTemplate.locked.desc(), EmailTemplate.id.asc()).first()

    t = _first(EmailTemplate.query.filter_by(stage=stage)) if stage else None
    if not t:
        t = _first(EmailTemplate.query.filter_by(stage="generic"))
    if not t:
        t = EmailTemplate.query.order_by(EmailTemplate.id.asc()).first()
    return t, stage


@app.route("/api/lead/<int:lead_id>/draft-email", methods=["POST"])
def draft_email(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json() or {}
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 400

    # Template: explicit choice, else auto-pick by the lead's status/stage.
    template_id = data.get("template_id")
    auto_selected = False
    if template_id:
        template = EmailTemplate.query.get_or_404(template_id)
        stage = template.stage
    else:
        template, stage = _pick_template_for_lead(lead)
        auto_selected = True
        if not template:
            return jsonify({"error": "No templates yet — create one in Email Templates first"}), 400

    # Grounded news hook — CACHED per lead so personalisation is consistent across
    # re-composes (the live web search is otherwise non-deterministic). Looked up
    # once, then reused; {"refresh_news": true} forces a fresh lookup.
    news_hook = ""
    if data.get("use_news", True):
        if lead.cached_news_hook is not None and not data.get("refresh_news"):
            news_hook = lead.cached_news_hook          # "" = checked-but-none; text = hook
        else:
            try:
                from enrich_engine import recent_news_hook
                news_hook = recent_news_hook(lead.investor_name) or ""
            except Exception as e:
                print(f"[draft_email] news hook: {e}")
                news_hook = ""
            lead.cached_news_hook = news_hook          # cache the result (incl. empty)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    ctx = {
        "investor_name":      lead.investor_name,
        "key_contact":        lead.key_contact or "",
        "investor_type":      lead.investor_type or "",
        "invested_company":   lead.invested_company or "",
        "sector":             lead.sector or "",
        "recent_investments": lead.recent_investments or "",
        "trigger_signals":    lead.trigger_signals or "",
        "action_item":        lead.action_item or "",
    }
    res = personalize_email(ctx, template.subject or "", template.body, api_key, news_hook=news_hook)

    return jsonify({
        "ok": True,
        "subject":       res["subject"] or template.subject or "",
        "body":          res["body"],
        "personalized":  res["personalized"],
        "confidence":    res["confidence"],
        "basis":         res["basis"],
        "news_hook":     news_hook,
        "template_id":   template.id,
        "template_name": template.name,
        "stage":         stage or "generic",
        "auto_selected": auto_selected,
        "locked":        bool(template.locked),
    })


# ── Single lead send ─────────────────────────────────────────────────────────

@app.route("/api/lead/<int:lead_id>/send-email", methods=["POST"])
def send_email_route(lead_id):
    lead = InvestmentLead.query.get_or_404(lead_id)
    data        = request.get_json()
    to_email    = (data.get("to_email") or "").strip()
    subject     = (data.get("subject")  or "").strip()
    body        = (data.get("body")     or "").strip()
    template_id = data.get("template_id")

    if not to_email: return jsonify({"error": "Recipient email required"}), 400

    attachment_path = attachment_name = None
    if template_id:
        t = EmailTemplate.query.get(template_id)
        if t and t.attachment_path:
            attachment_path = t.attachment_path
            attachment_name = t.attachment_name

    status_before = lead.status
    msg_id = _make_message_id(lead_id)
    try:
        _send_via_gmail(to_email, subject, body, attachment_path, message_id=msg_id,
                        attachment_name=attachment_name)
    except RuntimeError as e:
        if "gmail_not_connected" in str(e):
            return jsonify({"error": "gmail_not_connected"}), 401
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    new_status = _next_reached_out_status(status_before)
    _log_event(lead_id, "sent", status_at=status_before, status_to=new_status,
               template_stage=EmailTemplate.STATUS_TO_STAGE.get(status_before or ""),
               to_email=to_email, subject=subject, message_id=msg_id)
    _mark_sent(lead)
    db.session.commit()
    return jsonify({"ok": True, "new_status": new_status})


# ── Bulk send ─────────────────────────────────────────────────────────────────

@app.route("/api/bulk-send", methods=["POST"])
def bulk_send():
    data        = request.get_json()
    lead_ids    = data.get("lead_ids", [])
    template_id = data.get("template_id")
    api_key     = os.getenv("ANTHROPIC_API_KEY")

    if not lead_ids or not template_id:
        return jsonify({"error": "lead_ids and template_id are required"}), 400

    template = EmailTemplate.query.get_or_404(template_id)
    leads    = InvestmentLead.query.filter(InvestmentLead.id.in_(lead_ids)).all()

    results = []
    for lead in leads:
        email = (lead.email or "").split(",")[0].strip()
        if not email:
            results.append({"id": lead.id, "name": lead.investor_name, "status": "skipped", "reason": "no email"})
            continue
        try:
            draft = generate_email_draft(
                lead.investor_name, lead.investor_type or "",
                lead.invested_company or "", lead.sector or "",
                template.subject or "", template.body, api_key,
            ) if api_key else None
            subject = (draft or {}).get("subject") or template.subject or ""
            body    = (draft or {}).get("body")    or template.body
            _send_via_gmail(email, subject, body, template.attachment_path,
                            attachment_name=template.attachment_name)
            _mark_sent(lead)
            results.append({"id": lead.id, "name": lead.investor_name, "status": "sent", "email": email})
        except RuntimeError as e:
            if "gmail_not_connected" in str(e):
                db.session.commit()
                return jsonify({"error": "gmail_not_connected", "results": results}), 401
            results.append({"id": lead.id, "name": lead.investor_name, "status": "error", "reason": str(e)})
        except Exception as e:
            results.append({"id": lead.id, "name": lead.investor_name, "status": "error", "reason": str(e)})

    db.session.commit()
    sent = sum(1 for r in results if r["status"] == "sent")
    return jsonify({"ok": True, "sent": sent, "total": len(leads), "results": results})


# ── Stage 2: review-approved dispatch (background, throttled) ─────────────────
# Sends already-reviewed-and-approved drafts. Each lead's subject/body is taken
# verbatim from the review queue (no re-generation), throttled with jitter, with
# a "stop after current send" flag. On success: status → "Reached Out" + note.
_dispatch_status = {
    "running": False, "total": 0, "done": 0, "sent": 0, "failed": 0, "skipped": 0,
    "current": "", "eta_seconds": None, "stop": False, "results": [],
}
DISPATCH_JITTER_MIN = 15   # seconds between sends (randomised)
DISPATCH_JITTER_MAX = 45


@app.route("/api/dispatch/start", methods=["POST"])
def dispatch_start():
    global _dispatch_status
    if _dispatch_status["running"]:
        return jsonify({"ok": False, "message": "A send is already in progress"}), 409
    # Pre-flight: Gmail must be configured (validated before anything leaves).
    if not _gmail_ready():
        return jsonify({"ok": False, "error": "gmail_not_connected"}), 401

    items = (request.get_json(silent=True) or {}).get("items") or []
    queue, skipped = [], []
    for it in items:
        if (it.get("to_email") or "").strip() and (it.get("body") or "").strip():
            queue.append(it)
        else:
            skipped.append({"name": it.get("name", ""), "email": it.get("to_email", ""),
                            "status": "skipped", "reason": "no email / empty body"})

    _dispatch_status = {
        "running": True, "total": len(queue), "done": 0, "sent": 0, "failed": 0,
        "skipped": len(skipped), "current": "", "eta_seconds": None,
        "stop": False, "results": list(skipped),
    }

    import time as _t, random as _r, threading

    def run():
        global _dispatch_status
        with app.app_context():
            for i, it in enumerate(queue):
                if _dispatch_status["stop"]:
                    break
                name = it.get("name", "")
                em   = (it.get("to_email") or "").split(",")[0].strip()
                _dispatch_status["current"] = name

                attach = attach_name = None
                tid = it.get("template_id")
                if tid:
                    t = EmailTemplate.query.get(tid)
                    if t and t.attachment_path:
                        attach = t.attachment_path
                        attach_name = t.attachment_name
                try:
                    lead = InvestmentLead.query.get(it.get("lead_id"))
                    status_before = lead.status if lead else None
                    msg_id = _make_message_id(it.get("lead_id"))
                    _send_via_gmail(em, it.get("subject", ""), it.get("body", ""),
                                    attach, message_id=msg_id,
                                    attachment_name=attach_name)
                    if lead:
                        _log_event(lead.id, "sent", status_at=status_before,
                                   status_to=_next_reached_out_status(status_before),
                                   template_stage=EmailTemplate.STATUS_TO_STAGE.get(status_before or ""),
                                   to_email=em, subject=it.get("subject", ""), message_id=msg_id)
                        _mark_sent(lead)
                        db.session.commit()
                    _dispatch_status["sent"] += 1
                    _dispatch_status["results"].append(
                        {"name": name, "email": em, "status": "sent"})
                except Exception as e:
                    _dispatch_status["failed"] += 1
                    _dispatch_status["results"].append(
                        {"name": name, "email": em, "status": "failed", "reason": str(e)[:140]})

                _dispatch_status["done"] += 1
                remaining = _dispatch_status["total"] - _dispatch_status["done"]
                # ~30s avg jitter + a couple seconds to send.
                _dispatch_status["eta_seconds"] = remaining * 32 if remaining > 0 else 0

                # Throttle between sends — interruptible so "stop" feels instant.
                if remaining > 0 and not _dispatch_status["stop"]:
                    for _ in range(_r.randint(DISPATCH_JITTER_MIN, DISPATCH_JITTER_MAX)):
                        if _dispatch_status["stop"]:
                            break
                        _t.sleep(1)

        _dispatch_status["current"] = ""
        _dispatch_status["eta_seconds"] = 0
        _dispatch_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "total": len(queue), "skipped": len(skipped)})


@app.route("/api/dispatch/status")
def dispatch_status():
    return jsonify(_dispatch_status)


@app.route("/api/dispatch/stop", methods=["POST"])
def dispatch_stop():
    _dispatch_status["stop"] = True
    return jsonify({"ok": True})


# ── Outreach report (on-demand, computed live from the event log) ────────────
@app.route("/api/report")
def outreach_report():
    from sqlalchemy import func, distinct
    sent       = OutreachEvent.query.filter_by(event_type="sent").count()
    bounced    = OutreachEvent.query.filter_by(event_type="bounce").count()
    replies    = OutreachEvent.query.filter_by(event_type="reply").count()
    contacted  = db.session.query(func.count(distinct(OutreachEvent.lead_id))) \
                   .filter(OutreachEvent.event_type == "sent").scalar() or 0
    total_leads = InvestmentLead.query.count()

    statuses = ["New", "Reached Out", "Reached Out Again",
                "Engaged", "Didn't Respond", "Not Interested"]
    by_status = {s: InvestmentLead.query.filter_by(status=s).count() for s in statuses}
    engaged = by_status.get("Engaged", 0)

    # last 14 days of send volume
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=14)
    rows = (db.session.query(func.date(OutreachEvent.created_at), func.count())
            .filter(OutreachEvent.event_type == "sent",
                    OutreachEvent.created_at >= since)
            .group_by(func.date(OutreachEvent.created_at)).all())
    per_day = [{"date": str(d), "count": c} for d, c in rows]

    last_event = (OutreachEvent.query.order_by(OutreachEvent.created_at.desc()).first())

    return jsonify({
        "emails_sent": sent,
        "bounced": bounced,
        "delivered": max(0, sent - bounced),
        "replies": replies,
        "leads_contacted": contacted,
        "leads_engaged": engaged,
        "total_leads": total_leads,
        "by_status": by_status,
        "per_day": per_day,
        "last_activity": last_event.created_at.isoformat() if last_event else None,
    })


# ── One-click status sync: reply→Engaged (IMAP thread-match), bounce detect,
#    and the 5-day Reached-Out→No-Response rule. Statuses only; never sends. ────
NO_RESPONSE_DAYS = 5


@app.route("/api/sync-status", methods=["POST"])
def sync_status():
    if not _gmail_ready():
        return jsonify({"ok": False, "error": "gmail_not_connected"}), 401
    import imaplib, email as _email
    from email.utils import parseaddr
    from datetime import timedelta

    # Map every Message-ID we stamped → its lead.
    id_to_lead = {ev.message_id.strip().lower(): ev.lead_id
                  for ev in OutreachEvent.query.filter_by(event_type="sent").all()
                  if ev.message_id}
    seen_reply_ids = {e.message_id for e in OutreachEvent.query.filter_by(event_type="reply").all() if e.message_id}

    engaged, no_response, bounced = [], [], []

    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        M.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        M.select("INBOX")

        # ── Replies: only messages that reference one of OUR message-ids ──
        typ, data = M.search(None, '(OR HEADER REFERENCES "bhookle-" HEADER IN-REPLY-TO "bhookle-")')
        for num in (data[0].split() if data and data[0] else []):
            typ, md = M.fetch(num, '(BODY.PEEK[HEADER.FIELDS (FROM IN-REPLY-TO REFERENCES MESSAGE-ID SUBJECT)])')
            if not md or not md[0]:
                continue
            msg  = _email.message_from_bytes(md[0][1])
            refs = ((msg.get("In-Reply-To") or "") + " " + (msg.get("References") or "")).lower()
            frm  = parseaddr(msg.get("From", ""))[1].lower()
            in_id = (msg.get("Message-ID") or "").strip()
            if frm == (GMAIL_USER or "").lower() or (in_id and in_id in seen_reply_ids):
                continue
            lead_id = next((lid for oid, lid in id_to_lead.items() if oid in refs), None)
            if not lead_id:
                continue
            lead = InvestmentLead.query.get(lead_id)
            if not lead:
                continue
            _log_event(lead.id, "reply", status_at=lead.status, status_to="Engaged",
                       to_email=frm, subject=(msg.get("Subject") or "")[:200],
                       message_id=in_id, detail="Reply received")
            if lead.status != "Engaged":
                lead.status = "Engaged"
                engaged.append(lead.investor_name)
        db.session.commit()

        # ── Bounces (best-effort): mailer-daemon notices that quote our id ──
        typ, data = M.search(None, '(FROM "mailer-daemon")')
        for num in (data[0].split() if data and data[0] else [])[-40:]:
            typ, md = M.fetch(num, '(BODY.PEEK[])')
            if not md or not md[0]:
                continue
            raw = md[0][1].decode("utf-8", "ignore").lower()
            oid = next((o for o in id_to_lead if o in raw), None)
            if not oid:
                continue
            if OutreachEvent.query.filter_by(event_type="bounce", message_id=oid).first():
                continue
            lead = InvestmentLead.query.get(id_to_lead[oid])
            _log_event(id_to_lead[oid], "bounce", status_at=(lead.status if lead else None),
                       message_id=oid, detail="Delivery failure (bounce)")
            bounced.append(lead.investor_name if lead else str(id_to_lead[oid]))
        db.session.commit()
        M.logout()
    except Exception as e:
        return jsonify({"ok": False, "error": f"IMAP error: {e}"}), 500

    # ── 5-day rule: two paths, two verdicts ──────────────────────────────────
    # Reached Out       (first contact) + 5d no reply → Didn't Respond
    # Reached Out Again (re-engagement)  + 5d no reply → Not Interested
    #                                                   reason: "Never responded"
    cutoff = datetime.utcnow() - timedelta(days=NO_RESPONSE_DAYS)
    gave_up = []   # leads that just transitioned to Not Interested via the harder rule

    def _is_no_reply(lead):
        """Shared check for both 5-day rules: last send > NO_RESPONSE_DAYS ago and
        no reply has landed since that send. Returns the last_sent event (truthy)
        if the lead should transition, or None to skip."""
        last_sent = (OutreachEvent.query.filter_by(lead_id=lead.id, event_type="sent")
                     .order_by(OutreachEvent.created_at.desc()).first())
        if not last_sent or (last_sent.created_at or datetime.utcnow()) > cutoff:
            return None
        replied = OutreachEvent.query.filter(
            OutreachEvent.lead_id == lead.id, OutreachEvent.event_type == "reply",
            OutreachEvent.created_at >= last_sent.created_at).first()
        return None if replied else last_sent

    # Forward path
    for lead in InvestmentLead.query.filter_by(status="Reached Out").all():
        if not _is_no_reply(lead):
            continue
        _log_event(lead.id, "status_change", status_at="Reached Out",
                   status_to="Didn't Respond",
                   detail=f"No reply {NO_RESPONSE_DAYS}d after send")
        lead.status = "Didn't Respond"
        no_response.append(lead.investor_name)

    # Backward path — second attempt aged out → real "no". Records the rejection
    # reason so the Not Interested view tells the right story at a glance.
    for lead in InvestmentLead.query.filter_by(status="Reached Out Again").all():
        if not _is_no_reply(lead):
            continue
        _log_event(lead.id, "status_change", status_at="Reached Out Again",
                   status_to="Not Interested",
                   detail=f"No reply {NO_RESPONSE_DAYS}d after re-engagement")
        lead.status = "Not Interested"
        lead.rejection_reason = "Never responded"
        gave_up.append(lead.investor_name)
    db.session.commit()

    parts = []
    if engaged:     parts.append(f"{len(engaged)} → Engaged")
    if no_response: parts.append(f"{len(no_response)} → Didn't Respond")
    if gave_up:     parts.append(f"{len(gave_up)} → Not Interested (never responded)")
    if bounced:     parts.append(f"{len(bounced)} bounced")
    return jsonify({"ok": True, "engaged": engaged, "no_response": no_response,
                    "gave_up": gave_up, "bounced": bounced,
                    "summary": " · ".join(parts) if parts else "No status changes"})


# ── Check Bounce — focused IMAP scan for delivery failures. Logs each new
#    bounce, reverts the lead's status from "Reached Out" → "New" so the founder
#    can fix the email and re-dispatch. The Bounced label in the table persists
#    after the revert so problematic addresses stay visible. ─────────────────────
@app.route("/api/check-bounce", methods=["POST"])
def check_bounce():
    if not _gmail_ready():
        return jsonify({"ok": False, "error": "gmail_not_connected"}), 401
    import imaplib, email as _email

    # Map every Message-ID we stamped on outgoing emails → its lead. A bounce
    # notification quotes the original Message-ID in its body, so we match on it.
    id_to_lead = {ev.message_id.strip().lower(): ev.lead_id
                  for ev in OutreachEvent.query.filter_by(event_type="sent").all()
                  if ev.message_id}
    already_bounced = {e.message_id for e in
                       OutreachEvent.query.filter_by(event_type="bounce").all()
                       if e.message_id}

    bounced = []           # newly detected this run → leads + what we did
    already = 0            # already-logged bounces we skipped

    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        M.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        M.select("INBOX")

        # Cast a wider net than sync-status: mailer-daemon + postmaster +
        # "Undeliverable" subject lines (Outlook/Exchange-style bounces). Last
        # 200 results across the union — bounces normally land within minutes,
        # but the founder may run this days after a dispatch.
        nums = set()
        for q in ('(FROM "mailer-daemon")', '(FROM "postmaster")',
                  '(SUBJECT "Undeliverable")', '(SUBJECT "Delivery Status Notification")'):
            typ, data = M.search(None, q)
            if data and data[0]:
                nums.update(data[0].split())
        nums = list(nums)[-200:]

        for num in nums:
            typ, md = M.fetch(num, '(BODY.PEEK[])')
            if not md or not md[0]:
                continue
            raw = md[0][1].decode("utf-8", "ignore").lower()
            oid = next((o for o in id_to_lead if o in raw), None)
            if not oid:
                continue
            if oid in already_bounced:
                already += 1
                continue

            lead = InvestmentLead.query.get(id_to_lead[oid])
            if not lead:
                continue

            was_status = lead.status
            _log_event(lead.id, "bounce", status_at=was_status,
                       message_id=oid, detail="Delivery failure (bounce)")
            already_bounced.add(oid)   # don't double-count if the same bounce matches another rule

            reverted = False
            # Bring "Reached Out" leads back to "New" so the founder can fix the
            # email and dispatch again. We don't touch already-Engaged leads
            # (they replied) or Didn't Respond / Not Interested (manually set).
            if was_status == "Reached Out":
                lead.status = "New"
                _log_event(lead.id, "status_change", status_at=was_status,
                           status_to="New",
                           detail="Reverted to New after bounce")
                reverted = True

            bounced.append({
                "id": lead.id, "name": lead.investor_name,
                "email": (lead.email or "").split(",")[0].strip(),
                "was_status": was_status, "reverted": reverted,
            })

        db.session.commit()
        M.logout()
    except Exception as e:
        return jsonify({"ok": False, "error": f"IMAP error: {e}"}), 500

    return jsonify({
        "ok": True, "count": len(bounced),
        "reverted": sum(1 for b in bounced if b["reverted"]),
        "already_logged": already, "bounced": bounced,
        "summary": (f"{len(bounced)} new bounce" + ("s" if len(bounced) != 1 else "")
                    + (f" · {sum(1 for b in bounced if b['reverted'])} sent back to New"
                       if any(b["reverted"] for b in bounced) else ""))
                   if bounced else "No new bounces in your inbox 🎉",
    })


# ── Rejection-reason classification (for "Not Interested" leads) ─────────────
# Batch endpoint: classify every Not Interested lead's notes via Claude in
# parallel, save to lead.rejection_reason. Per-lead PATCH below lets the founder
# fix a wrong classification or set one manually.

_classify_status = {"running": False, "done": 0, "total": 0, "classified": 0,
                    "skipped": 0, "current": ""}


@app.route("/api/classify-rejections", methods=["POST"])
def classify_rejections():
    """Read notes on every 'Not Interested' lead and classify the rejection
    reason via Claude. Skips leads with empty notes (no signal to classify on)
    and, by default, leads that already have a rejection_reason set.

    Query / body knobs:
      force=true  → reclassify even leads that already have a reason
                     (use after editing notes en masse).
    """
    global _classify_status
    if _classify_status["running"]:
        return jsonify({"ok": False, "message": "Classification already running"}), 409

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 400

    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))

    with app.app_context():
        q = InvestmentLead.query.filter_by(status="Not Interested")
        candidates = []
        empty_notes = 0
        already = 0
        for l in q.all():
            if not (l.notes or "").strip():
                empty_notes += 1
                continue
            if not force and (l.rejection_reason or "").strip():
                already += 1
                continue
            candidates.append((l.id, l.investor_name, l.notes))

    _classify_status = {"running": True, "done": 0, "total": len(candidates),
                        "classified": 0, "skipped": empty_notes + already,
                        "empty_notes": empty_notes, "already_classified": already,
                        "current": ""}

    if not candidates:
        _classify_status["running"] = False
        return jsonify({"ok": True, "total": 0, "empty_notes": empty_notes,
                        "already_classified": already,
                        "message": "Nothing to classify — every Not Interested "
                                   "lead either has no notes or is already tagged."})

    from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _ac
    import threading
    _lock = threading.Lock()

    def run():
        global _classify_status
        # 4 concurrent Claude calls — fast enough for a typical 10-50 lead batch,
        # well under Anthropic's per-minute limits at normal use.
        with app.app_context():
            def classify_one(item):
                lid, name, notes = item
                r = classify_rejection_reason(name, notes, api_key)
                return lid, name, r

            with _TPE(max_workers=4) as ex:
                futs = [ex.submit(classify_one, item) for item in candidates]
                for fut in _ac(futs):
                    try:
                        lid, name, r = fut.result()
                    except Exception:
                        with _lock: _classify_status["done"] += 1
                        continue
                    with _lock:
                        _classify_status["current"] = name
                        lead = InvestmentLead.query.get(lid)
                        if lead:
                            lead.rejection_reason = r["reason"]
                            db.session.commit()
                            _classify_status["classified"] += 1
                        _classify_status["done"] += 1
        _classify_status["current"] = ""
        _classify_status["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "total": len(candidates),
                    "empty_notes": empty_notes, "already_classified": already,
                    "message": f"Classifying {len(candidates)} rejection note(s)…"})


@app.route("/api/classify-rejections/status")
def classify_rejections_status():
    return jsonify(_classify_status)


@app.route("/api/lead/<int:lead_id>/rejection-reason", methods=["PATCH"])
def update_rejection_reason(lead_id):
    """Manual override / clear of a lead's rejection_reason (drives the inline
    dropdown in the table). Allows empty string to clear."""
    lead = InvestmentLead.query.get_or_404(lead_id)
    data = request.get_json() or {}
    reason = (data.get("rejection_reason") or "").strip()
    if reason and reason not in REJECTION_REASONS:
        return jsonify({"error": f"Invalid reason. Allowed: {REJECTION_REASONS}"}), 400
    lead.rejection_reason = reason or None
    db.session.commit()
    return jsonify({"ok": True, "rejection_reason": lead.rejection_reason or ""})


# ── Attachment upload for templates ──────────────────────────────────────────

@app.route("/api/templates/<int:tid>/attachment", methods=["POST"])
def upload_attachment(tid):
    t = EmailTemplate.query.get_or_404(tid)
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext      = os.path.splitext(f.filename)[1]
    filename = uuid.uuid4().hex + ext
    path     = os.path.join(ATTACHMENTS_DIR, filename)
    # Remove old file
    if t.attachment_path and os.path.exists(t.attachment_path):
        os.remove(t.attachment_path)
    f.save(path)
    t.attachment_path = path
    t.attachment_name = f.filename
    db.session.commit()
    return jsonify({"ok": True, "attachment_name": f.filename})


@app.route("/api/templates/<int:tid>/attachment", methods=["DELETE"])
def remove_attachment(tid):
    t = EmailTemplate.query.get_or_404(tid)
    if t.attachment_path and os.path.exists(t.attachment_path):
        os.remove(t.attachment_path)
    t.attachment_path = None
    t.attachment_name = None
    db.session.commit()
    return jsonify({"ok": True})


def _backfill_reached_out_again():
    """One-shot cleanup for the mixed-bucket era: any lead currently sitting in
    'Reached Out' whose MOST RECENT send was a re-engagement (logged with
    status_at = "Didn't Respond" or "Not Interested") gets reclassified to
    'Reached Out Again'. Idempotent — once moved, the lead no longer matches the
    filter, so re-running this is a no-op.

    Covers any send that flowed through send_email_route or dispatch_start
    (both call _log_event with status_at=status_before). bulk_send doesn't log
    a status_at, so any of those (older code path) can't be auto-detected — fix
    manually by changing the status select if needed.
    """
    fixed = 0
    for lead in InvestmentLead.query.filter_by(status="Reached Out").all():
        last_sent = (OutreachEvent.query
                     .filter_by(lead_id=lead.id, event_type="sent")
                     .order_by(OutreachEvent.created_at.desc()).first())
        if not last_sent:
            continue
        if last_sent.status_at in ("Didn't Respond", "Not Interested"):
            _log_event(lead.id, "status_change", status_at="Reached Out",
                       status_to="Reached Out Again",
                       detail="Backfill: re-engagement send detected in history")
            lead.status = "Reached Out Again"
            fixed += 1
    if fixed:
        db.session.commit()
        print(f"[backfill] moved {fixed} mixed-bucket lead(s) → Reached Out Again")


# Run create_all + lightweight column migrations at IMPORT time (not just under
# __main__), so the auto-reloader picks up new columns added in this session
# without a full process restart. Idempotent — safe to run on every boot.
with app.app_context():
    db.create_all()
    try:
        _ensure_schema()
    except Exception as _e:
        print(f"[schema] migration warning: {_e}")
    try:
        _backfill_reached_out_again()
    except Exception as _e:
        print(f"[backfill] warning: {_e}")


if __name__ == "__main__":
    with app.app_context():
        seed_db()
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", threaded=True,
            port=int(os.getenv("PORT", "5050")))
