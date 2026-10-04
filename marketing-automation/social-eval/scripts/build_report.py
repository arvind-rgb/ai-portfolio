#!/usr/bin/env python3
"""
Bhookle Social Eval — PDF Report Builder v1
Usage: python3 build_report.py <content.json> <output.pdf>
"""

import json
import sys
import os
import re
import io
import tempfile
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, Image, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

# ── Brand tokens ──────────────────────────────────────────────────────────────
PURPLE      = colors.HexColor("#7030A0")
PURPLE_LIGHT= colors.HexColor("#EDE0F5")
YELLOW      = colors.HexColor("#FFC000")
YELLOW_LIGHT= colors.HexColor("#FFF8E1")
DARK_GREY   = colors.HexColor("#2D2D2D")
MED_GREY    = colors.HexColor("#666666")
LIGHT_GREY  = colors.HexColor("#F2F2F2")
RULE_GREY   = colors.HexColor("#CCCCCC")
WHITE       = colors.white
RISK_BG     = colors.HexColor("#FFF8E1")
RISK_BORDER = colors.HexColor("#FFC000")

PAGE_W, PAGE_H = A4
MARGIN_TOP    = 22 * mm
MARGIN_BOTTOM = 22 * mm
MARGIN_LEFT   = 25 * mm
MARGIN_RIGHT  = 22 * mm
TEXT_W        = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT

# ── Font registration ─────────────────────────────────────────────────────────
UNICODE_FONT   = "Helvetica"
UNICODE_BOLD   = "Helvetica-Bold"
UNICODE_ITALIC = "Helvetica-Oblique"

def register_fonts():
    global UNICODE_FONT, UNICODE_BOLD, UNICODE_ITALIC
    candidates = [
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
        ("/Library/Fonts/Arial Unicode.ttf", None),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular):
            pdfmetrics.registerFont(TTFont("UniFont", regular))
            UNICODE_FONT   = "UniFont"
            UNICODE_ITALIC = "UniFont"
            bold_path = bold if (bold and os.path.exists(bold)) else regular
            pdfmetrics.registerFont(TTFont("UniFont-Bold", bold_path))
            UNICODE_BOLD = "UniFont-Bold"
            return

register_fonts()

def safe(text):
    text = text.replace("₹", "Rs.")
    if UNICODE_FONT == "Helvetica":
        text = text.replace("•", "-")
        text = text.replace("—", "--")
        text = text.replace("–", "-")
        text = text.replace("‘", "'").replace("’", "'")
        text = text.replace("“", '"').replace("”", '"')
        text = text.encode("latin-1", "replace").decode("latin-1")
    return text

# ── Source reference extractor ────────────────────────────────────────────────
SOURCE_RE = re.compile(r'\s*\*?\(Source:\s*([^)]+?)\)\*?', re.IGNORECASE)

def extract_sources(text):
    sources = []
    def replacer(m):
        src = m.group(1).strip()
        if src not in sources:
            sources.append(src)
        idx = sources.index(src) + 1
        return f" [{idx}]"
    cleaned = SOURCE_RE.sub(replacer, text)
    return cleaned, sources

# ── Style definitions ─────────────────────────────────────────────────────────
def build_styles():
    def P(name, **kw):
        kw.setdefault("fontName", UNICODE_FONT)
        return ParagraphStyle(name, **kw)

    styles = {}
    styles["body"] = P("body",
        fontSize=9.5, leading=14, textColor=DARK_GREY, spaceAfter=5,
        alignment=TA_JUSTIFY)
    styles["body_left"] = P("body_left",
        fontSize=9.5, leading=14, textColor=DARK_GREY, spaceAfter=5)
    styles["h2"] = P("h2",
        fontName=UNICODE_BOLD,
        fontSize=12, leading=16, textColor=PURPLE,
        spaceBefore=14, spaceAfter=5, keepWithNext=1)
    styles["h3"] = P("h3",
        fontName=UNICODE_BOLD,
        fontSize=10.5, leading=14, textColor=DARK_GREY,
        spaceBefore=10, spaceAfter=4, keepWithNext=1)
    styles["bullet"] = P("bullet",
        fontSize=9.5, leading=14, textColor=DARK_GREY,
        leftIndent=12, firstLineIndent=0, spaceAfter=3)
    styles["footnote_heading"] = P("footnote_heading",
        fontName=UNICODE_BOLD,
        fontSize=8, leading=11, textColor=PURPLE, spaceBefore=8, spaceAfter=3)
    styles["footnote"] = P("footnote",
        fontSize=7.5, leading=11, textColor=MED_GREY, spaceAfter=2, leftIndent=8)
    styles["note"] = P("note",
        fontName=UNICODE_ITALIC,
        fontSize=8.5, leading=12, textColor=MED_GREY, spaceAfter=5)
    styles["risk"] = P("risk",
        fontSize=9, leading=13, textColor=DARK_GREY, spaceAfter=5,
        leftIndent=8, rightIndent=8)
    styles["callout_num"] = P("callout_num",
        fontName=UNICODE_BOLD,
        fontSize=20, leading=24, textColor=DARK_GREY, alignment=TA_CENTER)
    styles["callout_label"] = P("callout_label",
        fontSize=8, leading=11, textColor=DARK_GREY, alignment=TA_CENTER)
    styles["toc_entry"] = P("toc_entry",
        fontSize=9.5, leading=14, textColor=DARK_GREY, spaceAfter=2)
    styles["cover_title"] = P("cover_title",
        fontName=UNICODE_BOLD,
        fontSize=30, leading=38, textColor=WHITE, alignment=TA_CENTER)
    styles["cover_sub"] = P("cover_sub",
        fontSize=16, leading=22, textColor=WHITE, alignment=TA_CENTER)
    styles["table_header"] = P("table_header",
        fontName=UNICODE_BOLD,
        fontSize=8, leading=11, textColor=WHITE, alignment=TA_LEFT)
    styles["table_body"] = P("table_body",
        fontSize=8.5, leading=12, textColor=DARK_GREY)
    return styles


# ── Chart helpers ─────────────────────────────────────────────────────────────
_PURPLE  = "#7030A0"
_PURPLEM = "#9C60CC"
_PURPLEL = "#C9A8E0"
_YELLOW  = "#FFC000"
_GREY    = "#CCCCCC"
_DKGREY  = "#2D2D2D"
_MEDGREY = "#666666"
_ORANGE  = "#FF8C00"

def _fig(w=7.2, h=3.0):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#DDDDDD')
    ax.spines['bottom'].set_color('#DDDDDD')
    ax.tick_params(colors=_MEDGREY, labelsize=8)
    return fig, ax

def _save(fig):
    buf = io.BytesIO()
    plt.tight_layout(pad=0.5)
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf

def _title(ax, text):
    ax.set_title(text, color=_PURPLE, fontsize=10, fontweight='bold', pad=8)


# Chart A — 90-day reach + engagement trend (dual-axis line)
def chart_reach_engagement_trend(chart_data):
    dates  = chart_data.get("dates", [])
    reach  = chart_data.get("reach", [])
    er_pct = chart_data.get("er_pct", [])

    if not dates:
        dates  = [f"Week {i+1}" for i in range(6)]
        reach  = [12000, 15400, 18200, 14300, 21000, 19800]
        er_pct = [4.2, 5.1, 6.8, 4.9, 7.2, 6.1]

    fig, ax1 = plt.subplots(figsize=(7.2, 3.2))
    fig.patch.set_facecolor('white')
    ax1.set_facecolor('white')
    for sp in ['top', 'right']:
        ax1.spines[sp].set_visible(False)
    ax1.spines['left'].set_color('#DDDDDD')
    ax1.spines['bottom'].set_color('#DDDDDD')
    ax1.tick_params(colors=_MEDGREY, labelsize=8)

    ax1.fill_between(dates, reach, alpha=0.15, color=_PURPLE)
    ax1.plot(dates, reach, color=_PURPLE, linewidth=2.5, marker='o',
             markersize=5, markerfacecolor='white', markeredgewidth=2, label='Reach')
    ax1.set_ylabel('Reach', fontsize=8, color=_PURPLE)
    ax1.tick_params(axis='y', colors=_PURPLE, labelsize=8)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{int(x/1000)}K' if x >= 1000 else str(int(x))))

    ax2 = ax1.twinx()
    ax2.plot(dates, er_pct, color=_YELLOW, linewidth=2.5, linestyle='--',
             marker='s', markersize=5, markerfacecolor=_YELLOW, label='ER%')
    ax2.set_ylabel('Engagement Rate %', fontsize=8, color='#8B6900')
    ax2.tick_params(axis='y', colors='#8B6900', labelsize=8)
    ax2.spines['top'].set_visible(False)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc='upper left',
               framealpha=0.9)

    ax1.set_title('90-Day Reach & Engagement Rate Trend', color=_PURPLE,
                  fontsize=10, fontweight='bold', pad=8)
    if len(dates) > 6:
        ax1.set_xticks(ax1.get_xticks()[::2])

    buf = io.BytesIO()
    plt.tight_layout(pad=0.5)
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf


# Chart B — Top 10 reels by ER% (horizontal bar)
def chart_top_reels(chart_data):
    labels = chart_data.get("labels", [f"Reel {i+1}" for i in range(6)])
    er_pct = chart_data.get("er_pct", [7.2, 6.9, 6.4, 5.8, 5.6, 5.1])

    # Truncate labels to 35 chars
    labels_short = [l[:35] + "..." if len(l) > 35 else l for l in labels]

    # Sort ascending so highest bar is at top
    pairs = sorted(zip(er_pct, labels_short), key=lambda x: x[0])
    er_sorted  = [p[0] for p in pairs]
    lab_sorted = [p[1] for p in pairs]

    n = len(er_sorted)
    bar_colors = [_YELLOW if i == n - 1 else _PURPLE for i in range(n)]

    fig, ax = _fig(7.2, max(2.8, n * 0.38))
    bars = ax.barh(lab_sorted, er_sorted, color=bar_colors, height=0.6, zorder=3)
    ax.xaxis.grid(True, color='#EEEEEE', linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel('Engagement Rate %', fontsize=8, color=_MEDGREY)
    ax.spines['left'].set_visible(False)

    for bar, val in zip(bars, er_sorted):
        ax.text(val + 0.1, bar.get_y() + bar.get_height() / 2,
                f'{val:.1f}%', va='center', fontsize=8, color=_DKGREY, fontweight='bold')

    _title(ax, 'Top Reels by Engagement Rate')
    return _save(fig)


# Chart C — Engagement by content theme (grouped bar)
def chart_theme_performance(chart_data):
    themes   = chart_data.get("themes",   ["Chef Story", "Food Visual", "Offer/Discount", "UGC", "Educational", "BTS"])
    avg_er   = chart_data.get("avg_er",   [6.8, 4.2, 2.1, 5.9, 3.8, 4.5])
    avg_saves= chart_data.get("avg_saves",[280, 110, 45, 195, 130, 165])

    x = np.arange(len(themes))
    w = 0.38

    fig, ax1 = plt.subplots(figsize=(7.2, 3.0))
    fig.patch.set_facecolor('white')
    ax1.set_facecolor('white')
    for sp in ['top', 'right']:
        ax1.spines[sp].set_visible(False)
    ax1.spines['left'].set_color('#DDDDDD')
    ax1.spines['bottom'].set_color('#DDDDDD')
    ax1.tick_params(colors=_MEDGREY, labelsize=8)

    b1 = ax1.bar(x - w/2, avg_er, width=w, color=_PURPLE, label='Avg ER%', zorder=3)
    ax1.set_ylabel('Avg Engagement Rate %', fontsize=8, color=_PURPLE)
    ax1.tick_params(axis='y', colors=_PURPLE, labelsize=8)
    ax1.yaxis.grid(True, color='#EEEEEE', linewidth=0.5, zorder=0)
    ax1.set_axisbelow(True)

    ax2 = ax1.twinx()
    b2 = ax2.bar(x + w/2, avg_saves, width=w, color=_YELLOW, label='Avg Saves', zorder=3)
    ax2.set_ylabel('Avg Saves', fontsize=8, color='#8B6900')
    ax2.tick_params(axis='y', colors='#8B6900', labelsize=8)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_color('#DDDDDD')

    ax1.set_xticks(x)
    ax1.set_xticklabels(themes, fontsize=8, rotation=15, ha='right')

    lines = [mpatches.Patch(color=_PURPLE, label='Avg ER%'),
             mpatches.Patch(color=_YELLOW, label='Avg Saves')]
    ax1.legend(handles=lines, fontsize=8, loc='upper right', framealpha=0.9)

    _title(ax1, 'Performance by Content Theme')

    buf = io.BytesIO()
    plt.tight_layout(pad=0.5)
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf


# Chart D — Posting frequency by day-of-week (bar)
def chart_posting_frequency(chart_data):
    days   = chart_data.get("days",   ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    avg_er = chart_data.get("avg_er", [4.1, 6.2, 5.8, 6.5, 4.8, 3.9, 3.2])

    max_idx = avg_er.index(max(avg_er))
    bar_colors = [_YELLOW if i == max_idx else _PURPLE for i in range(len(days))]

    fig, ax = _fig(6.5, 3.0)
    ax.set_facecolor('#FAFAFA')
    bars = ax.bar(days, avg_er, color=bar_colors, width=0.55, zorder=3,
                  edgecolor='white', linewidth=1.5)
    ax.yaxis.grid(True, color='#EEEEEE', linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.set_ylabel('Avg Engagement Rate %', fontsize=8, color=_MEDGREY)

    for bar, val in zip(bars, avg_er):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f'{val:.1f}%', ha='center', va='bottom',
                fontsize=8, fontweight='bold', color=_DKGREY)

    _title(ax, 'Avg Engagement Rate by Day of Week')
    return _save(fig)


# Chart E — Competitor ER% comparison (grouped bar)
def chart_competitor_er(chart_data):
    accounts = chart_data.get("accounts", ["Bhookle", "Cookr", "GoodFood"])
    er_pct   = chart_data.get("er_pct",   [5.8, 3.2, 2.9])

    bar_colors = [_PURPLE if a == "Bhookle" else _GREY for a in accounts]

    fig, ax = _fig(5.5, 3.0)
    ax.set_facecolor('#FAFAFA')
    bars = ax.bar(accounts, er_pct, color=bar_colors, width=0.45, zorder=3,
                  edgecolor='white', linewidth=1.5)
    ax.yaxis.grid(True, color='#EEEEEE', linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.set_ylabel('Est. Engagement Rate %', fontsize=8, color=_MEDGREY)

    for bar, val in zip(bars, er_pct):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f'{val:.1f}%', ha='center', va='bottom',
                fontsize=9, fontweight='bold', color=_DKGREY)

    ax.annotate('⚠ Competitor ER% estimated from public observation',
                xy=(0.5, -0.18), xycoords='axes fraction',
                ha='center', fontsize=7.5, color=_MEDGREY, style='italic')

    _title(ax, 'Estimated Engagement Rate Comparison')
    return _save(fig)


# Chart F — Content strategy radar (polar chart, 3 players)
def chart_strategy_radar(chart_data):
    themes   = chart_data.get("themes",   ["Chef Story", "Food Visual", "Offer/Promo", "UGC", "Educational", "BTS"])
    bhookle  = chart_data.get("bhookle",  [8, 6, 4, 5, 3, 7])
    cookr    = chart_data.get("cookr",    [3, 8, 6, 2, 4, 2])
    goodfood = chart_data.get("goodfood", [2, 7, 8, 3, 5, 1])

    N = len(themes)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]

    fig = plt.figure(figsize=(6.5, 4.2))
    fig.patch.set_facecolor('white')
    ax = fig.add_subplot(111, polar=True)
    ax.set_facecolor('white')
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(themes, fontsize=8, color=_DKGREY)
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(['2','4','6','8','10'], fontsize=6.5, color=_MEDGREY)
    ax.yaxis.grid(True, color='#EEEEEE', linewidth=0.5)
    ax.xaxis.grid(True, color='#DDDDDD', linewidth=0.5)
    ax.spines['polar'].set_color('#DDDDDD')

    players = [
        ("Bhookle",  bhookle,  _PURPLE, '-',  2.5, 0.18),
        ("Cookr",    cookr,    _GREY,   '--', 1.2, 0.07),
        ("GoodFood", goodfood, _ORANGE, ':',  1.0, 0.05),
    ]
    for name, scores, col, ls, lw, alpha in players:
        vals = scores + scores[:1]
        ax.plot(angles, vals, color=col, linestyle=ls, linewidth=lw,
                label=name, zorder=3 if name == 'Bhookle' else 2)
        ax.fill(angles, vals, color=col, alpha=alpha)

    ax.legend(loc='upper right', bbox_to_anchor=(1.38, 1.15), fontsize=8, framealpha=0.9)
    ax.set_title('Content Strategy Radar — Theme Mix by Account',
                 color=_PURPLE, fontsize=10, fontweight='bold', pad=20)
    return _save(fig)


def chart_to_image(buf, width=TEXT_W, max_height=180):
    img = Image(buf)
    aspect = img.imageWidth / img.imageHeight
    h = min(max_height, width / aspect)
    w = h * aspect
    img.drawWidth  = w
    img.drawHeight = h
    return img


def _chart_flowables(buf, caption, styles, max_height=160):
    return [
        Spacer(1, 8),
        chart_to_image(buf, width=TEXT_W, max_height=max_height),
        Paragraph(safe(caption), styles["note"]),
        Spacer(1, 8),
    ]


def section_charts(sid, styles, data):
    """Auto-insert charts after their assigned sections."""
    out = []
    ca = data.get("chart_a_data", {})
    cb = data.get("chart_b_data", {})
    cc = data.get("chart_c_data", {})
    cd = data.get("chart_d_data", {})
    ce = data.get("chart_e_data", {})
    cf = data.get("chart_f_data", {})

    if sid == 2 and ca:
        out += _chart_flowables(
            chart_reach_engagement_trend(ca),
            "Figure 2.1 — 90-day reach and engagement rate trend. Dual axis: purple = reach (left), "
            "yellow dashed = ER% (right). Source: Windsor.ai Instagram connector.",
            styles, max_height=170)

    elif sid == 3:
        if cb:
            out += _chart_flowables(
                chart_top_reels(cb),
                "Figure 3.1 — Top reels ranked by engagement rate. Yellow bar = highest performer. "
                "Source: Windsor.ai Instagram connector.",
                styles, max_height=185)
        if cc:
            out += _chart_flowables(
                chart_theme_performance(cc),
                "Figure 3.2 — Average engagement rate and saves by content theme. "
                "Source: Windsor.ai Instagram connector.",
                styles, max_height=160)

    elif sid == 4 and cd:
        out += _chart_flowables(
            chart_posting_frequency(cd),
            "Figure 4.1 — Average engagement rate by day of week. Yellow bar = best-performing day. "
            "Source: Windsor.ai Instagram connector.",
            styles, max_height=155)

    elif sid == 7:
        if ce:
            out += _chart_flowables(
                chart_competitor_er(ce),
                "Figure 7.1 — Estimated engagement rate by account. Competitor figures are "
                "observational estimates, not audited data.",
                styles, max_height=155)
        if cf:
            out += _chart_flowables(
                chart_strategy_radar(cf),
                "Figure 7.2 — Content strategy radar: relative weighting of each theme per account "
                "(1=rarely used, 10=dominant). Estimated from public feed observation.",
                styles, max_height=210)
    return out


# ── Section header band ───────────────────────────────────────────────────────
def section_header_band(section_id, title, styles):
    label = f"SECTION {section_id}  —  {title.upper()}" if section_id else title.upper()
    cell = Paragraph(safe(f'<font color="white"><b>{label}</b></font>'), styles["body"])
    t = Table([[cell]], colWidths=[TEXT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), PURPLE),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    return t


def h2_with_rule(text, styles):
    return [
        HRFlowable(width=TEXT_W, thickness=1.2, color=PURPLE_LIGHT,
                   spaceAfter=3, spaceBefore=10),
        Paragraph(safe(text), styles["h2"]),
    ]


# ── Callout boxes ─────────────────────────────────────────────────────────────
def callout_row(items, styles):
    n = len(items)
    cell_w = TEXT_W / n
    num_cells   = [Paragraph(safe(it.get("number", "")), styles["callout_num"]) for it in items]
    label_cells = [Paragraph(safe(it.get("label", "")),  styles["callout_label"]) for it in items]
    t = Table([num_cells, label_cells], colWidths=[cell_w] * n)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), YELLOW),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1,  0), "BOTTOM"),
        ("VALIGN",        (0, 1), (-1,  1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1,  0), 10),
        ("BOTTOMPADDING", (0, 0), (-1,  0), 3),
        ("TOPPADDING",    (0, 1), (-1,  1), 3),
        ("BOTTOMPADDING", (0, 1), (-1,  1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBEFORE",    (1, 0), (-1, -1), 2, WHITE),
    ]))
    return t


# ── Data tables ───────────────────────────────────────────────────────────────
def smart_col_widths(headers, rows, total_w):
    n = len(headers)
    weights = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
               for i, h in enumerate(headers)]
    total_w_units = sum(weights)
    return [max(total_w * w / total_w_units, 28) for w in weights]

def data_table(headers, rows, styles, accent=PURPLE):
    col_w = smart_col_widths(headers, rows, TEXT_W)
    scale = TEXT_W / sum(col_w)
    col_w = [w * scale for w in col_w]

    header_cells = [Paragraph(safe(str(h)), styles["table_header"]) for h in headers]
    table_data = [header_cells]
    for row in rows:
        table_data.append([Paragraph(safe(str(c)), styles["table_body"]) for c in row])

    t = Table(table_data, colWidths=col_w, repeatRows=1)
    row_bgs = [LIGHT_GREY if i % 2 == 0 else WHITE for i in range(len(rows))]
    style_cmds = [
        ("BACKGROUND",    (0,0),  (-1,0),  accent),
        ("VALIGN",        (0,0),  (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0),  (-1,-1), 5),
        ("BOTTOMPADDING", (0,0),  (-1,-1), 5),
        ("LEFTPADDING",   (0,0),  (-1,-1), 6),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 6),
        ("GRID",          (0,0),  (-1,-1), 0.3, RULE_GREY),
        ("LINEBELOW",     (0,0),  (-1,0),  1.0, accent),
        ("FONTNAME",      (0,0),  (-1,0),  UNICODE_BOLD),
        ("FONTSIZE",      (0,0),  (-1,-1), 8.5),
        ("FONTNAME",      (0,1),  (-1,-1), UNICODE_FONT),
    ]
    for i, bg in enumerate(row_bgs, start=1):
        style_cmds.append(("BACKGROUND", (0,i), (-1,i), bg))
    t.setStyle(TableStyle(style_cmds))
    return t


# ── Risk / note boxes ─────────────────────────────────────────────────────────
def risk_box(text, styles):
    cell = Paragraph(safe(f"⚠  {text}"), styles["risk"])
    t = Table([[cell]], colWidths=[TEXT_W - 12])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), RISK_BG),
        ("LINEBELOW",     (0,0), (-1,-1), 2, YELLOW),
        ("LINETOP",       (0,0), (-1,-1), 2, YELLOW),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ]))
    return t


def footnote_block(sources, styles):
    items = [Paragraph(safe("References"), styles["footnote_heading"])]
    for i, src in enumerate(sources, 1):
        items.append(Paragraph(safe(f"[{i}] {src}"), styles["footnote"]))
    return items


def _cite_markers(text):
    return re.sub(
        r'\[(\d+)\]',
        lambda m: f'<font size="7" color="#7030A0"><b>[{m.group(1)}]</b></font>',
        text
    )


# ── Block → flowables dispatcher ──────────────────────────────────────────────
def block_to_flowables(block, styles, section_sources):
    btype = block.get("type", "paragraph")
    out = []

    if btype == "paragraph":
        raw = block.get("text", "")
        cleaned, srcs = extract_sources(raw)
        for s in srcs:
            if s not in section_sources:
                section_sources.append(s)
        out.append(Paragraph(safe(_cite_markers(cleaned)), styles["body"]))

    elif btype == "heading":
        level = block.get("level", 2)
        if level == 2:
            out.extend(h2_with_rule(block.get("text", ""), styles))
        else:
            out.append(Paragraph(safe(block.get("text", "")), styles["h3"]))

    elif btype == "bullets":
        if block.get("heading"):
            out.extend(h2_with_rule(block["heading"], styles))
        for item in block.get("items", []):
            cleaned, srcs = extract_sources(item)
            for s in srcs:
                if s not in section_sources:
                    section_sources.append(s)
            out.append(Paragraph(safe(f"    -  {_cite_markers(cleaned)}"), styles["bullet"]))

    elif btype in ("table", "gap_table"):
        out.append(Spacer(1, 4))
        out.append(data_table(block["headers"], block["rows"], styles,
                               accent=PURPLE if btype == "table" else colors.HexColor("#5A1A8A")))
        out.append(Spacer(1, 4))

    elif btype == "callouts":
        out.append(Spacer(1, 4))
        out.append(callout_row(block["items"], styles))
        out.append(Spacer(1, 8))

    elif btype == "note":
        out.append(Paragraph(safe(f"Note: {block.get('text','')}"), styles["note"]))

    elif btype == "risk":
        out.append(Spacer(1, 4))
        out.append(risk_box(block.get("text", ""), styles))
        out.append(Spacer(1, 4))

    elif btype == "page_break":
        out.append(PageBreak())

    out.append(Spacer(1, 3))
    return out


# ── TOC ───────────────────────────────────────────────────────────────────────
def build_toc(sorted_sections, styles):
    out = [
        section_header_band(None, "Table of Contents", styles),
        Spacer(1, 10),
    ]
    for s in sorted_sections:
        sid, title = s["id"], s["title"]
        label = title if sid == 1 else f"Section {sid}  —  {title}"
        out.append(Paragraph(safe(f"   {label}"), styles["toc_entry"]))
    out.append(Paragraph(safe("   Appendix A: Competitor Snapshot"), styles["toc_entry"]))
    out.append(PageBreak())
    return out


# ── Cover page ────────────────────────────────────────────────────────────────
def draw_cover(c, month_str):
    c.setFillColor(PURPLE)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    c.setFillColor(YELLOW)
    c.rect(0, PAGE_H * 0.28, PAGE_W, 4, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.setFont(UNICODE_BOLD, 30)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.63, "Bhookle Social Eval")
    c.setFont(UNICODE_BOLD, 22)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.57, "Instagram & Facebook Performance Report")

    c.setFont(UNICODE_FONT, 16)
    c.setFillColor(colors.HexColor("#D4BAEC"))
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.49, month_str)

    c.setStrokeColor(YELLOW)
    c.setLineWidth(2)
    c.line(MARGIN_LEFT, PAGE_H * 0.43, PAGE_W - MARGIN_RIGHT, PAGE_H * 0.43)

    c.setFont(UNICODE_FONT, 10)
    c.setFillColor(colors.HexColor("#D4BAEC"))
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.37,
                        "Includes: Reel Analysis | Competitor Benchmarking | Recommendations")

    c.setFont(UNICODE_FONT, 8)
    c.setFillColor(colors.HexColor("#A888CC"))
    c.drawRightString(PAGE_W - MARGIN_RIGHT, MARGIN_BOTTOM,
                      "bhookle.com  |  owner@example.com")


# ── Page canvas: footer + watermark ──────────────────────────────────────────
class BhookleCanvas(pdfcanvas.Canvas):
    def __init__(self, filename, **kwargs):
        super().__init__(filename, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_elements(self._pageNumber, num_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_page_elements(self, page_num, total):
        self.saveState()
        self.setFont(UNICODE_BOLD, 38)
        self.setFillColorRGB(0.85, 0.85, 0.85, alpha=0.18)
        self.translate(PAGE_W / 2, PAGE_H / 2)
        self.rotate(42)
        self.drawCentredString(0, 0, "BHOOKLE CONFIDENTIAL")
        self.restoreState()
        self.saveState()
        y_rule = MARGIN_BOTTOM - 8 * mm
        self.setStrokeColor(RULE_GREY)
        self.setLineWidth(0.4)
        self.line(MARGIN_LEFT, y_rule + 3 * mm, PAGE_W - MARGIN_RIGHT, y_rule + 3 * mm)
        self.setFont(UNICODE_FONT, 7.5)
        self.setFillColor(MED_GREY)
        self.drawString(MARGIN_LEFT, y_rule, "Bhookle Confidential")
        self.drawCentredString(PAGE_W / 2, y_rule, "bhookle.com")
        self.drawRightString(PAGE_W - MARGIN_RIGHT, y_rule, f"Page {page_num} of {total}")
        self.restoreState()


# ── Main build ────────────────────────────────────────────────────────────────
def build_pdf(content_path, output_path):
    with open(content_path, encoding="utf-8") as f:
        data = json.load(f)

    month_str = data.get("month", datetime.now().strftime("%B %Y"))
    sections  = data.get("sections", [])
    # Section 1 first, then 2-7 in order
    sorted_sections = sorted(sections, key=lambda s: s["id"])

    styles = build_styles()
    temp_path = output_path + ".body.pdf"

    doc = SimpleDocTemplate(
        temp_path, pagesize=A4,
        leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP + 4 * mm,
        bottomMargin=MARGIN_BOTTOM + 12 * mm,
    )

    def render_blocks(blocks, styles, section_sources):
        result = []
        i = 0
        while i < len(blocks):
            btype = blocks[i].get("type", "paragraph")
            if btype == "heading" and i + 1 < len(blocks):
                heading_fs = block_to_flowables(blocks[i],     styles, section_sources)
                content_fs = block_to_flowables(blocks[i + 1], styles, section_sources)
                keep = heading_fs + content_fs[:3]
                rest = content_fs[3:]
                result.append(KeepTogether(keep))
                result.extend(rest)
                i += 2
            else:
                result.extend(block_to_flowables(blocks[i], styles, section_sources))
                i += 1
        return result

    story = []
    story.extend(build_toc(sorted_sections, styles))

    for section in sorted_sections:
        sid    = section["id"]
        title  = section["title"]
        section_sources = []
        blocks = section.get("content", [])

        header_band    = section_header_band(None if sid == 1 else sid, title, styles)
        body_flowables = render_blocks(blocks, styles, section_sources)

        story.append(KeepTogether([header_band, Spacer(1, 8)] + body_flowables[:2]))
        story.extend(body_flowables[2:])

        if section_sources:
            story.extend(footnote_block(section_sources, styles))

        story.extend(section_charts(sid, styles, data))
        story.append(PageBreak())

    # Appendix A — competitor snapshot
    app_a = data.get("appendix_a", {})
    if app_a:
        story.append(section_header_band(None, "Appendix A: " + app_a.get("title", "Competitor Snapshot"), styles))
        story.append(Spacer(1, 8))
        tbl = app_a.get("table", {})
        if tbl:
            story.append(data_table(tbl["headers"], tbl["rows"], styles))
        story.append(PageBreak())

    doc.build(story, canvasmaker=BhookleCanvas)

    # Merge cover + body
    try:
        from pypdf import PdfReader, PdfWriter
        cover_path = output_path + ".cover.pdf"
        c = pdfcanvas.Canvas(cover_path, pagesize=A4)
        draw_cover(c, month_str)
        c.showPage()
        c.save()

        reader_main  = PdfReader(temp_path)
        reader_cover = PdfReader(cover_path)
        writer = PdfWriter()
        writer.add_page(reader_cover.pages[0])
        for page in reader_main.pages:
            writer.add_page(page)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as out:
            writer.write(out)
        os.remove(temp_path)
        os.remove(cover_path)
    except ImportError:
        os.rename(temp_path, output_path)
        print("Tip: install pypdf for branded cover page merging.")

    print(f"Report saved: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 build_report.py <content.json> <output.pdf>")
        sys.exit(1)
    build_pdf(sys.argv[1], sys.argv[2])
