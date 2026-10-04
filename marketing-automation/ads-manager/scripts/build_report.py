#!/usr/bin/env python3
"""
AdsManager — Branded PDF Report Generator
-----------------------------------------
Reads an analysis JSON and outputs a Bhookle-branded PDF using ReportLab.

Brand tokens:
  --bh-orange    #FFA70B   primary
  --bh-mulberry  #2D1B3D   deep
  --bh-cream     #FFF8EC   page background
  --bh-magenta   #E51A4B   accent (rare)
  --bh-teal      #00AAB2   fresh / positive
"""

import sys, json
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether, HRFlowable, Image
)

# Register Poppins (brand font, supports ₹ symbol)
FONT_DIR = Path(__file__).resolve().parents[2] / "bhookle-design-system" / "fonts"
try:
    pdfmetrics.registerFont(TTFont("Poppins",        str(FONT_DIR / "Poppins-Medium.ttf")))
    pdfmetrics.registerFont(TTFont("Poppins-Bold",   str(FONT_DIR / "Poppins-Black.ttf")))
    pdfmetrics.registerFont(TTFont("Poppins-Thin",   str(FONT_DIR / "Poppins-Thin.ttf")))
    BODY_FONT = "Poppins"
    BOLD_FONT = "Poppins-Bold"
except Exception as e:
    print(f"⚠️  Could not load Poppins ({e}); falling back to Helvetica (₹ will render as boxes)")
    BODY_FONT = "Helvetica"
    BOLD_FONT = "Helvetica-Bold"

# Brand colors
ORANGE      = HexColor("#FFA70B")
MULBERRY    = HexColor("#2D1B3D")
MULBERRY_60 = HexColor("#6E4F7A")
MULBERRY_20 = HexColor("#D8CCE0")
MULBERRY_10 = HexColor("#EEE7F2")
CREAM       = HexColor("#FFF8EC")
CREAM_2     = HexColor("#FBEFD4")
MAGENTA     = HexColor("#E51A4B")
TEAL        = HexColor("#00AAB2")
ORANGE_50   = HexColor("#FFE9C2")
INK         = HexColor("#1A1A1A")

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm


def page_bg(canvas, doc):
    """Paint cream background + page footer."""
    canvas.saveState()
    canvas.setFillColor(CREAM)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # Top orange strip
    canvas.setFillColor(ORANGE)
    canvas.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, fill=1, stroke=0)
    # Footer
    canvas.setFillColor(MULBERRY_60)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 8 * mm, "Bhookle Ads Intelligence Report")
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def cover_page_bg(canvas, doc):
    """Hero cover: orange band + mulberry block + meta text drawn directly."""
    canvas.saveState()
    canvas.setFillColor(CREAM)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(ORANGE)
    canvas.rect(0, PAGE_H - 80 * mm, PAGE_W, 80 * mm, fill=1, stroke=0)
    canvas.setFillColor(MULBERRY)
    canvas.rect(0, 0, PAGE_W, 55 * mm, fill=1, stroke=0)

    # Read summary for cover meta (drawn directly on canvas to avoid flow overflow)
    try:
        latest_payload = canvas._cover_payload
        s = latest_payload["summary"]
        canvas.setFillColor(CREAM)
        canvas.setFont(BOLD_FONT, 11)
        canvas.drawString(MARGIN, 38 * mm, "BHOOKLE EATS")
        canvas.setFont(BODY_FONT, 9.5)
        canvas.drawString(MARGIN, 30 * mm, f"Ad Account · {s['account_id']}")
        canvas.drawString(MARGIN, 22 * mm, f"Active campaigns · {s['active_campaigns']}   ·   Account health · {s['health_score']}/100")
        canvas.drawString(MARGIN, 14 * mm, f"Action items · {s['action_items_total']} ({s['action_items_high']} HIGH)")
    except Exception:
        pass
    canvas.restoreState()


# Style sheet
ss = getSampleStyleSheet()
STYLES = {
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName=BOLD_FONT,
                         fontSize=24, leading=28, textColor=MULBERRY, spaceAfter=4),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName=BOLD_FONT,
                         fontSize=16, leading=20, textColor=ORANGE, spaceBefore=12, spaceAfter=8),
    "h3": ParagraphStyle("h3", parent=ss["Heading3"], fontName=BOLD_FONT,
                         fontSize=12, leading=15, textColor=MULBERRY, spaceBefore=6, spaceAfter=4),
    "body": ParagraphStyle("body", parent=ss["BodyText"], fontName=BODY_FONT,
                           fontSize=10, leading=14, textColor=INK, spaceAfter=6),
    "small": ParagraphStyle("small", parent=ss["BodyText"], fontName=BODY_FONT,
                            fontSize=8.5, leading=11, textColor=MULBERRY_60),
    "callout": ParagraphStyle("callout", parent=ss["BodyText"], fontName=BOLD_FONT,
                              fontSize=10, leading=14, textColor=MULBERRY),
    "cover_title": ParagraphStyle("ct", parent=ss["Heading1"], fontName=BOLD_FONT,
                                  fontSize=36, leading=42, textColor=MULBERRY, alignment=TA_LEFT),
    "cover_sub": ParagraphStyle("cs", parent=ss["BodyText"], fontName=BODY_FONT,
                                fontSize=13, leading=17, textColor=MULBERRY_60, alignment=TA_LEFT),
    "cover_meta": ParagraphStyle("cm", parent=ss["BodyText"], fontName=BODY_FONT,
                                 fontSize=10, leading=13, textColor=CREAM, alignment=TA_LEFT),
    "kpi_label": ParagraphStyle("kl", fontName=BODY_FONT, fontSize=8.5, leading=10,
                                textColor=MULBERRY_60, alignment=TA_CENTER, spaceAfter=2),
    "kpi_value": ParagraphStyle("kv", fontName=BOLD_FONT, fontSize=16, leading=20,
                                textColor=MULBERRY, alignment=TA_CENTER),
}


def fmt_inr(v, decimals=0):
    if v is None: return "—"
    if decimals == 0:
        return f"₹{int(round(v)):,}"
    return f"₹{v:,.{decimals}f}"


def fmt_num(v):
    if v is None: return "—"
    return f"{int(v):,}" if isinstance(v, (int, float)) else str(v)


def fmt_pct(v):
    if v is None: return "—"
    return f"{v:+.1f}%"


def kpi_cell(label, value):
    """Single KPI cell: small label on top, big value below."""
    return [
        Paragraph(label, STYLES["kpi_label"]),
        Paragraph(value, STYLES["kpi_value"]),
    ]


def kpi_row(items):
    """Row of KPI cells in a table. items=[(label,value), ...]"""
    n = len(items)
    col_width = (PAGE_W - 2 * MARGIN) / n
    data = [[kpi_cell(lbl, val) for lbl, val in items]]
    t = Table(data, colWidths=[col_width] * n, rowHeights=[24 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CREAM_2),
        ("BOX", (0, 0), (-1, -1), 0.6, MULBERRY_20),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, MULBERRY_20),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


# ────────────────────────────────────────────────────────────────────────────
# Section builders
# ────────────────────────────────────────────────────────────────────────────
def build_cover(payload):
    """Minimal flowables — meta text is drawn directly on canvas in cover_page_bg."""
    s = payload["summary"]
    items = []
    items.append(Spacer(1, 68 * mm))  # push past orange band
    items.append(Paragraph("Ads Intelligence", STYLES["cover_title"]))
    items.append(Paragraph("Report", STYLES["cover_title"]))
    items.append(Spacer(1, 3 * mm))
    items.append(Paragraph(f"Last 90 days · generated {s['run_date']}", STYLES["cover_sub"]))
    items.append(PageBreak())
    return items


def build_executive_summary(payload):
    s = payload["summary"]
    items = [
        Paragraph("Executive Summary", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
        Spacer(1, 2 * mm),
    ]

    # KPI strip 1: spend + installs + CPI (30d)
    items.append(kpi_row([
        ("Spend (30d)",  fmt_inr(s["spend_30d"])),
        ("Installs (30d)", fmt_num(s["installs_30d"])),
        ("Blended CPI (30d)", fmt_inr(s["blended_cpi_30d"], 2) if s["blended_cpi_30d"] else "—"),
        ("Active campaigns", str(s["active_campaigns"])),
    ]))
    items.append(Spacer(1, 3 * mm))

    # KPI strip 2: 90d + health + actions
    items.append(kpi_row([
        ("Spend (90d)",  fmt_inr(s["spend_90d"])),
        ("Installs (90d)", fmt_num(s["installs_90d"])),
        ("Account health", f"{s['health_score']}/100"),
        ("Action items", f"{s['action_items_total']} ({s['action_items_high']} HIGH)"),
    ]))
    items.append(Spacer(1, 6 * mm))

    # Narrative
    cpi_text = (
        f"At a blended CPI of {fmt_inr(s['blended_cpi_30d'], 2)} over the last 30 days, "
        "the account is delivering installs efficiently — well within the ₹5 benchmark we use for India app campaigns."
        if s["blended_cpi_30d"] and s["blended_cpi_30d"] < 5
        else
        f"The blended CPI of {fmt_inr(s['blended_cpi_30d'], 2)} is above the ₹5 efficiency benchmark — optimization opportunities exist."
        if s["blended_cpi_30d"]
        else "Install attribution unavailable for the period."
    )
    seven_day_note = ""
    if s["blended_cpi_7d"] and s["blended_cpi_30d"]:
        delta = (s["blended_cpi_7d"] - s["blended_cpi_30d"]) / s["blended_cpi_30d"] * 100
        if abs(delta) > 10:
            direction = "rising" if delta > 0 else "improving"
            seven_day_note = f" The 7-day CPI of {fmt_inr(s['blended_cpi_7d'], 2)} is {direction} ({delta:+.0f}%) vs the 30-day baseline — worth tracking closely."

    fatigue_note = ""
    if s["fatigued_active_creatives"] > 0:
        fatigue_note = (
            f"<br/><br/><b>{s['fatigued_active_creatives']} active creative(s)</b> are showing fatigue signals. "
            "See the Creative Fatigue section for details."
        )

    new_creative_note = ""
    if s.get("new_creatives_28d"):
        new_creative_note = (
            f"<br/><br/><b>{s['new_creatives_28d']} creative(s) launched in the last 28 days</b> — "
            f"{s.get('new_creatives_learning', 0)} still in learning, "
            f"{s.get('new_creatives_winning', 0)} showing winner/promising signals. "
            "See the New Creative Watch section for the cohort breakdown."
        )

    narrative = (
        f"{cpi_text}{seven_day_note}{new_creative_note}"
        f"<br/><br/><b>{s['action_items_high']} HIGH-priority action items</b> were identified across "
        "creative, budget, targeting, and campaign-structure dimensions."
        f"{fatigue_note}"
    )
    items.append(Paragraph(narrative, STYLES["body"]))
    items.append(PageBreak())
    return items


def build_campaign_section(payload):
    items = [
        Paragraph("Campaign Performance", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
    ]

    campaigns = sorted(payload["campaigns"],
                       key=lambda x: ((x["status"] != "ACTIVE"), -(x["spend_30d"] or 0)))

    # Performance table
    header = ["Campaign", "Status", "Spend 30d", "Inst 30d", "CPI 30d", "CPI 7d", "CTR 30d", "Freq"]
    rows = [header]
    for c in campaigns:
        rows.append([
            Paragraph(f"<b>{(c['name'] or '')[:35]}</b><br/><font size=7 color='#6E4F7A'>{c['objective'] or ''}</font>", STYLES["small"]),
            c["status"],
            fmt_inr(c["spend_30d"]),
            fmt_num(c["installs_30d"]),
            fmt_inr(c["cpi_30d"], 2) if c["cpi_30d"] else "—",
            fmt_inr(c["cpi_7d"], 2)  if c["cpi_7d"]  else "—",
            f"{c['ctr_30d']:.2f}%" if c["ctr_30d"] else "—",
            f"{c['freq_30d']:.2f}" if c["freq_30d"] else "—",
        ])

    col_widths = [55*mm, 20*mm, 18*mm, 16*mm, 18*mm, 18*mm, 18*mm, 14*mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), MULBERRY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), CREAM),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ALIGN",      (1, 1), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CREAM, CREAM_2]),
        ("BOX",        (0, 0), (-1, -1), 0.6, MULBERRY_20),
        ("GRID",       (0, 0), (-1, -1), 0.4, MULBERRY_20),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    items.append(t)
    items.append(Spacer(1, 6 * mm))

    # Per-campaign commentary
    for c in campaigns:
        if c["commentary"]:
            items.append(Paragraph(f"<b>{c['name']}</b>", STYLES["h3"]))
            for note in c["commentary"]:
                items.append(Paragraph(f"• {note}", STYLES["body"]))
            items.append(Spacer(1, 2 * mm))

    items.append(PageBreak())
    return items


def build_creative_section(payload):
    items = [
        Paragraph("Creative Fatigue Analysis", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
        Paragraph(
            "Creative fatigue is scored on a 9-point scale from CTR decay (7d vs 30d), "
            "CPI spike, frequency saturation, creative age, and video hold-rate. "
            "Scores ≥5 are flagged HIGH and recommended for pause.",
            STYLES["body"]),
        Spacer(1, 3 * mm),
    ]

    creatives = sorted(payload["creatives"], key=lambda x: -x["fatigue_score"])
    if not creatives:
        items.append(Paragraph("<i>No creative-level data available.</i>", STYLES["body"]))
        items.append(PageBreak())
        return items

    header = ["Ad", "Status", "Spend 30d", "CPI 30d", "CPI 7d", "CTR Δ", "CPI Δ", "Freq", "Age", "Fatigue"]
    rows = [header]
    for c in creatives[:25]:  # cap to keep PDF readable
        fatigue_color_map = {"HIGH": "#E51A4B", "MEDIUM": "#FFA70B", "LOW": "#6E4F7A", "NONE": "#00AAB2"}
        fc = fatigue_color_map[c["fatigue_level"]]
        rows.append([
            Paragraph(f"{(c['ad_name'] or '')[:32]}", STYLES["small"]),
            c["status"][:8] if c["status"] else "—",
            fmt_inr(c["spend_30d"]),
            fmt_inr(c["cpi_30d"], 2) if c["cpi_30d"] else "—",
            fmt_inr(c["cpi_7d"], 2) if c["cpi_7d"] else "—",
            fmt_pct(c["ctr_decay_pct"]),
            fmt_pct(c["cpi_spike_pct"]),
            f"{c['freq_30d']:.2f}" if c["freq_30d"] else "—",
            f"{c['creative_age_days']}d" if c["creative_age_days"] else "—",
            Paragraph(f"<font color='{fc}'><b>{c['fatigue_level']}</b></font> ({c['fatigue_score']})", STYLES["small"]),
        ])

    col_widths = [42*mm, 14*mm, 18*mm, 17*mm, 17*mm, 14*mm, 14*mm, 12*mm, 12*mm, 17*mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), MULBERRY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), CREAM),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7.5),
        ("ALIGN",      (1, 1), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CREAM, CREAM_2]),
        ("GRID",       (0, 0), (-1, -1), 0.4, MULBERRY_20),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    items.append(t)
    items.append(Spacer(1, 6 * mm))

    # Highlight HIGH-fatigue creatives with copy preview
    high = [c for c in creatives if c["fatigue_level"] == "HIGH" and c["status"] == "ACTIVE"]
    if high:
        items.append(Paragraph("HIGH-fatigue creatives requiring action", STYLES["h2"]))
        for c in high:
            items.append(Paragraph(f"<b>{c['ad_name']}</b> · Score {c['fatigue_score']}/9", STYLES["h3"]))
            items.append(Paragraph(f"<i>\"{c['creative_body']}\"</i>", STYLES["small"]))
            items.append(Paragraph(
                f"Video completion funnel: P25→{c['video_p25']:,} · P50→{c['video_p50']:,} · "
                f"P75→{c['video_p75']:,} · P100→{c['video_p100']:,} "
                f"(hold-rate {c['video_hold_rate_pct']}%)" if c["video_p25"] else
                f"No video metrics", STYLES["small"]))
            items.append(Spacer(1, 3 * mm))

    items.append(PageBreak())
    return items


def build_new_creative_section(payload):
    """Launch-cohort tracker: ads <28 days old vs incumbent benchmarks,
    with learning-phase-aware verdicts."""
    items = [
        Paragraph("New Creative Watch", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
        Paragraph(
            "Every ad launched in the last 28 days, benchmarked against the incumbent ads "
            "in its ad set (median 30-day CPI). Ads still in Meta's learning phase "
            "(&lt;50 installs) are never judged on CPI — their verdicts are informational only. "
            "Verdicts: WINNER / PROMISING (scale), AVERAGE (hold), LEARNING / TOO EARLY (wait), "
            "UNDERPERFORMER / NO TRACTION (act).",
            STYLES["body"]),
        Spacer(1, 3 * mm),
    ]
    watch = payload.get("new_creative_watch") or []
    if not watch:
        items.append(Paragraph(
            "<i>No creatives launched in the last 28 days. If performance is plateauing, "
            "that itself is a signal — fresh creative is the highest-leverage input.</i>",
            STYLES["body"]))
        items.append(PageBreak())
        return items

    verdict_colors = {
        "WINNER": "#00AAB2", "PROMISING": "#00AAB2",
        "AVERAGE": "#FFA70B", "LEARNING": "#6E4F7A", "TOO_EARLY": "#6E4F7A",
        "UNDERPERFORMER": "#E51A4B", "NO_TRACTION": "#E51A4B", "NOT_DELIVERING": "#E51A4B",
    }
    header = ["Ad", "Launched", "Status", "Spend 30d", "Installs", "CPI 30d", "Bench", "CTR 30d", "Verdict"]
    rows = [header]
    for w in watch:
        vc = verdict_colors.get(w["verdict"], "#6E4F7A")
        rows.append([
            Paragraph((w["ad_name"] or "")[:34], STYLES["small"]),
            w["launched"] or "—",
            (w["status"] or "—")[:8],
            fmt_inr(w["spend_30d"]),
            fmt_num(w["installs_30d"]),
            fmt_inr(w["cpi_30d"], 2) if w["cpi_30d"] else "—",
            fmt_inr(w["benchmark_cpi"], 2) if w["benchmark_cpi"] else "—",
            f"{w['ctr_30d']:.2f}%" if w["ctr_30d"] else "—",
            Paragraph(f"<font color='{vc}'><b>{w['verdict'].replace('_', ' ')}</b></font>", STYLES["small"]),
        ])
    col_widths = [40*mm, 17*mm, 15*mm, 18*mm, 15*mm, 16*mm, 16*mm, 16*mm, 24*mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), MULBERRY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), CREAM),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7.5),
        ("ALIGN",      (1, 1), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CREAM, CREAM_2]),
        ("GRID",       (0, 0), (-1, -1), 0.4, MULBERRY_20),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    items.append(t)
    items.append(Spacer(1, 6 * mm))

    # Per-ad reading
    items.append(Paragraph("Cohort reading", STYLES["h2"]))
    for w in watch:
        vc = verdict_colors.get(w["verdict"], "#6E4F7A")
        items.append(KeepTogether([
            Paragraph(
                f"<b>{w['ad_name']}</b>  <font color='{vc}'>· {w['verdict'].replace('_', ' ')}</font>",
                STYLES["h3"]),
            Paragraph(w["note"], STYLES["body"]),
            Spacer(1, 2 * mm),
        ]))
    items.append(PageBreak())
    return items


def build_targeting_section(payload):
    items = [
        Paragraph("Targeting & Audience Review", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
    ]
    active_adsets = [a for a in payload["targeting"] if a["status"] == "ACTIVE"]
    if not active_adsets:
        items.append(Paragraph("<i>No active ad sets.</i>", STYLES["body"]))
        items.append(PageBreak())
        return items

    for a in active_adsets:
        items.append(Paragraph(f"<b>{a['adset_name']}</b>", STYLES["h3"]))
        meta = (
            f"<b>Budget:</b> {fmt_inr(a['daily_budget_inr'], 2)}/day · "
            f"<b>Goal:</b> {a['optimization_goal'] or '—'} · "
            f"<b>Bid:</b> {a['bid_strategy'] or '—'}<br/>"
            f"<b>Age:</b> {a['age_range']} · "
            f"<b>Gender:</b> {', '.join(a['genders'])} · "
            f"<b>Cities:</b> {', '.join(a['cities']) or '—'} · "
            f"<b>Country:</b> {', '.join(a['countries']) or '—'}<br/>"
            f"<b>Interests ({len(a['interests'])}):</b> {', '.join(a['interests'][:8])}"
            f"{'…' if len(a['interests']) > 8 else ''}"
        )
        items.append(Paragraph(meta, STYLES["small"]))
        if a["flags"]:
            for f in a["flags"]:
                items.append(Paragraph(f, STYLES["callout"]))
        items.append(Spacer(1, 4 * mm))
    items.append(PageBreak())
    return items


def build_budget_section(payload):
    items = [
        Paragraph("Budget Reallocation", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
    ]
    moves = payload.get("budget_reallocation", [])
    if not moves:
        items.append(Paragraph(
            "Current budget allocation appears efficient — no single campaign is materially "
            "outperforming another by a margin worth reallocating against.", STYLES["body"]))
    else:
        for m in moves:
            items.append(Paragraph(f"<b>Move budget · {m['from_campaign']} → {m['to_campaign']}</b>", STYLES["h3"]))
            items.append(Paragraph(m["rationale"], STYLES["body"]))
            items.append(Spacer(1, 3 * mm))
    items.append(PageBreak())
    return items


def build_opportunities_section(payload):
    items = [
        Paragraph("Improvement Opportunities", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
    ]
    opps = payload.get("opportunities", [])
    if not opps:
        items.append(Paragraph("No untapped opportunities surfaced this cycle.", STYLES["body"]))
    else:
        for o in opps:
            priority_color = {"HIGH": MAGENTA, "MEDIUM": ORANGE, "LOW": TEAL}[o["priority"]]
            items.append(KeepTogether([
                Paragraph(f"<b>{o['title']}</b>  <font color='{priority_color.hexval()}'>· {o['priority']}</font>", STYLES["h3"]),
                Paragraph(o["detail"], STYLES["body"]),
                Spacer(1, 3 * mm),
            ]))
    items.append(PageBreak())
    return items


def build_action_items(payload):
    items = [
        Paragraph("Action Items", STYLES["h1"]),
        HRFlowable(width="100%", thickness=2, color=ORANGE, spaceBefore=2, spaceAfter=10),
        Paragraph(
            "These are prioritized, executable steps. In Claude Code, run "
            "<b>/show-ad-research</b> to walk through them one by one.",
            STYLES["body"]),
        Spacer(1, 4 * mm),
    ]
    actions = payload.get("action_items", [])
    if not actions:
        items.append(Paragraph("No action items.", STYLES["body"]))
        return items

    actions_sorted = sorted(actions, key=lambda a: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[a["priority"]], a["id"]))
    for a in actions_sorted:
        priority_color = {"HIGH": MAGENTA, "MEDIUM": ORANGE, "LOW": TEAL}[a["priority"]]
        items.append(KeepTogether([
            Paragraph(
                f"<b>#{a['id']} — {a['title']}</b>  "
                f"<font color='{priority_color.hexval()}'>· {a['priority']} · {a['category']}</font>",
                STYLES["h3"]
            ),
            Paragraph(a["rationale"], STYLES["body"]),
            Spacer(1, 4 * mm),
        ]))
    return items


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def build(json_path, pdf_path):
    payload = json.loads(Path(json_path).read_text())

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=20 * mm, bottomMargin=15 * mm,
        title="Bhookle Ads Intelligence Report",
        author="Bhookle AdsManager"
    )

    story = []
    story += build_cover(payload)
    story += build_executive_summary(payload)
    story += build_campaign_section(payload)
    story += build_creative_section(payload)
    story += build_new_creative_section(payload)
    story += build_targeting_section(payload)
    story += build_budget_section(payload)
    story += build_opportunities_section(payload)
    story += build_action_items(payload)

    # First page uses cover background, rest use the standard one
    def first_page(canvas, doc):
        canvas._cover_payload = payload          # attach so cover_page_bg can read summary
        cover_page_bg(canvas, doc)
    def later_pages(canvas, doc): page_bg(canvas, doc)

    doc.build(story, onFirstPage=first_page, onLaterPages=later_pages)
    print(f"PDF written: {pdf_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: build_report.py <analysis.json> <output.pdf>")
    build(sys.argv[1], sys.argv[2])
