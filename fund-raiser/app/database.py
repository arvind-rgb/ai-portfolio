from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class InvestmentLead(db.Model):
    __tablename__ = "investment_leads"

    id = db.Column(db.Integer, primary_key=True)
    investor_name = db.Column(db.String(200), nullable=False)
    investor_type = db.Column(db.String(100))         # Angel / PE / VC / Family Office
    invested_company = db.Column(db.String(200), nullable=False)
    investment_amount = db.Column(db.String(100))
    round_type = db.Column(db.String(100))            # Seed / Series A / etc.
    sector = db.Column(db.String(200))                # Cloud kitchen / Agritech / etc.
    deal_date = db.Column(db.String(50))
    key_contact = db.Column(db.String(200))
    email = db.Column(db.String(200))
    linkedin = db.Column(db.String(500))
    source_url = db.Column(db.String(1000))
    status = db.Column(
        db.String(50),
        default="New",
    )  # New / Reached Out / Reached Out Again / Engaged / Didn't Respond / Not Interested
    recent_investments = db.Column(db.Text)   # crawled: "Startup A ($2M), Startup B (₹5Cr)"
    follow_up_date = db.Column(db.String(20))
    notes = db.Column(db.Text)
    # ── Lead-sourcing scoring (getLeads engine) ──
    confidence_score = db.Column(db.Integer)        # 0-100 fit/intent score
    priority_tier    = db.Column(db.String(40))     # "Tier 1 [High Intent]" / "Tier 2 [Niche Fit]"
    trigger_signals  = db.Column(db.Text)           # why it matched (semicolon-joined)
    action_item      = db.Column(db.Text)           # suggested outreach angle
    signal_date      = db.Column(db.String(20))     # date of the freshest signal
    # Cached grounded news hook → personalisation stays consistent across re-composes.
    # NULL = never checked; "" = checked, none found; text = the cached hook.
    cached_news_hook = db.Column(db.Text)
    # ── Pre-composed LinkedIn messages (written in parallel right after a lead
    #    is fetched, so the compose modal opens instantly). NULL = not composed
    #    yet; cleared whenever the base LinkedIn templates change. ──
    cached_li_connect      = db.Column(db.Text)
    cached_li_dm           = db.Column(db.Text)
    cached_li_basis        = db.Column(db.Text)
    cached_li_personalized = db.Column(db.Boolean)
    # Same idea for the EMAIL channel — composing live cost ~8s per modal open.
    cached_em_subject      = db.Column(db.Text)
    cached_em_body         = db.Column(db.Text)
    cached_em_basis        = db.Column(db.Text)
    cached_em_personalized = db.Column(db.Boolean)
    # The contact's current role + employer, e.g. "Senior Vice President at
    # Flipkart". This is text that actually appears ON their LinkedIn profile,
    # so it's the only reliable way to pick the right person out of a same-name
    # search (a portfolio company is NOT on their profile).
    contact_headline = db.Column(db.String(300))
    # ── Evidence of a REAL, reported investment (the verification gate) ──
    # A lead may only be created when verify_lead_evidence() cites a credible
    # source naming this investor in this deal. These fields make every lead
    # auditable at a glance instead of taken on trust.
    evidence_url  = db.Column(db.String(600))   # clickable source article
    evidence_note = db.Column(db.Text)          # "X led Y's $1M seed round, Jun 2026"
    verified      = db.Column(db.Boolean, default=False)
    # Reopened for LinkedIn parity: this lead was already emailed (and only
    # emailed) in a past cycle, so the row hides the Email button and shows an
    # "Already contacted in email" label — LinkedIn is the remaining channel.
    email_only_retry = db.Column(db.Boolean, default=False)
    # ── Rejection classification (for "Not Interested" leads) ──
    # One of: Portfolio Misfit / Thesis Misfit / Traction Concerns /
    #         Scalability Concerns / Others. NULL = never classified.
    # Drives re-engagement angle on a future "didnt_respond"/"not_interested" send.
    rejection_reason = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "investor_name": self.investor_name,
            "investor_type": self.investor_type,
            "invested_company": self.invested_company,
            "investment_amount": self.investment_amount,
            "round_type": self.round_type,
            "sector": self.sector,
            "deal_date": self.deal_date,
            "key_contact": self.key_contact,
            "email": self.email,
            "linkedin": self.linkedin,
            "source_url": self.source_url,
            "status": self.status,
            "recent_investments": self.recent_investments,
            "notes": self.notes,
            "confidence_score": self.confidence_score,
            "priority_tier": self.priority_tier,
            "trigger_signals": self.trigger_signals,
            "action_item": self.action_item,
            "signal_date": self.signal_date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EmailTemplate(db.Model):
    __tablename__ = "email_templates"

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(200), nullable=False)
    subject         = db.Column(db.String(500), default="")
    body            = db.Column(db.Text, nullable=False)  # final message that gets sent
    attachment_path = db.Column(db.String(500))   # path to file on disk
    attachment_name = db.Column(db.String(200))   # original filename shown to user
    # ── Outreach automation ──
    # Which lead lifecycle stage this template is written for. Drives status-aware
    # messaging: a "New" lead gets a 'new' template, a non-responder gets a
    # 'didnt_respond' re-engagement template, etc. 'generic' = usable anywhere.
    stage           = db.Column(db.String(40), default="generic")
    # A locked template is a finalized base the founder has approved — the
    # confidence-gated personalizer falls back to it verbatim when unsure.
    locked          = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Maps a lead's `status` value → the template stage that should be used.
    # Only statuses that get a templated, automated email map to a stage.
    # "Reached Out" / "Reached Out Again" are transient (waiting for reply) and
    # "Engaged" is handled by humans — all three omitted.
    STATUS_TO_STAGE = {
        "New":             "new",
        "Didn't Respond":  "didnt_respond",
        # Re-engage a past "no" — many passed on scale/timing, not the idea itself.
        "Not Interested":  "not_interested",
    }

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "subject": self.subject or "",
            "body": self.body or "",
            "attachment_name": self.attachment_name or "",
            "stage": self.stage or "generic",
            "locked": bool(self.locked),
        }


class OutreachEvent(db.Model):
    """Append-only log of outreach events — the backbone of lifecycle tracking
    and reporting. Each email send records the lead's status at that moment and
    the Message-ID we stamped (so replies can be thread-matched)."""
    __tablename__ = "outreach_events"

    id             = db.Column(db.Integer, primary_key=True)
    lead_id        = db.Column(db.Integer, index=True)
    event_type     = db.Column(db.String(20), index=True)  # sent | reply | bounce | status_change
    status_at      = db.Column(db.String(50))   # lead status when the event happened
    status_to      = db.Column(db.String(50))   # new status (for status_change / send)
    template_stage = db.Column(db.String(40))
    to_email       = db.Column(db.String(200))
    subject        = db.Column(db.String(500))
    message_id     = db.Column(db.String(255), index=True)  # the Message-ID we stamped on the email
    detail         = db.Column(db.String(300))  # short note (reason / reply snippet / bounce reason)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "lead_id": self.lead_id, "event_type": self.event_type,
            "status_at": self.status_at, "status_to": self.status_to,
            "template_stage": self.template_stage, "to_email": self.to_email,
            "subject": self.subject, "message_id": self.message_id,
            "detail": self.detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
