#!/usr/bin/env python3
"""Build the branded Kitchen Intel report (HTML always, PDF when Chrome is present).

Usage:
    python3 build_report.py <run_dir>            # expects <run_dir>/report.json
    python3 build_report.py <run_dir> --no-pdf

The report is CHEF-SHAREABLE: written for the kitchen owner's eyes. No internal
pitch tactics (objection handling etc.) — those belong in the chat summary only.

report.json schema:
{
  "kitchen": "Sample Kitchen",
  "location": "Sahakara Nagar, Bangalore",
  "date": "2026-07-23",
  "ref": "BKI-2026-07-23-SAMPLEKITCHEN",         # optional, auto-derived if absent
  "tagline": "one-line positioning read",
  "prepared_for": "the team at Sample Kitchen",  # optional, used on cover + endnote
  "sample": false,
  "sections": [
    {"title": "1. Kitchen Snapshot", "blocks": [
      {"type": "stats",  "items": [{"label", "value", "sub"?}]},
      {"type": "text",   "md": "**bold**, '- ' bullets, blank-line paragraphs"},
      {"type": "table",  "headers": [...], "rows": [[...]], "note"?},
      {"type": "quotes", "items": [{"text", "meta", "sentiment": "pos|neg"}]},
      {"type": "score",  "items": [{"label", "score", "out_of"?, "note"?}]},
      {"type": "verdict","tone": "good|warn|bad", "md": "..."},
      {"type": "bars",   "items": [{"label", "value", "display", "hl"?}], "note"?},
      {"type": "scatter","x_label", "y_label",
                         "points": [{"label", "x", "y", "hl"?, "ghost"?}], "note"?},
      {"type": "callouts","items": [{"kicker", "title", "body", "tag"?}]}
    ]}
  ]
}
scatter x/y are pre-normalized 0-100 (y: 0 = top). ghost points render as a dashed
"open position" marker. Every printed page carries "AI Augmented Research by Bhookle".
"""
import base64
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

CREAM, MULBERRY, ORANGE = "#FFF8EC", "#341C3D", "#FFA70B"
MAGENTA, TEAL, BURNT = "#E51A4B", "#00AAB2", "#E15A18"
GREEN, RASP, MUTED, LINE = "#2E8C5A", "#C81E3A", "#6E4F7A", "#F0E3CE"
TONE = {"good": GREEN, "warn": BURNT, "bad": RASP}

LOGO_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "_templates/Logo/bhookle-logo-orange-small.png",
    Path(__file__).resolve().parents[3] / ".claude/skills/bhookle-design-system/assets/logo-full-orange.png",
]

CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
html {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
body {{ font-family:'Poppins','Avenir Next','Segoe UI',sans-serif; font-weight:500;
       background:{CREAM}; color:{MULBERRY}; max-width:880px; margin:0 auto; }}

/* ---------- cover ---------- */
header {{ background:{MULBERRY}; color:{CREAM}; padding:60px 56px 52px; position:relative;
          overflow:hidden; }}
header::after {{ content:""; position:absolute; right:-70px; top:-70px; width:260px; height:260px;
          border-radius:50%; background:{ORANGE}; opacity:.14; }}
header::before {{ content:""; position:absolute; right:40px; bottom:-110px; width:220px; height:220px;
          border-radius:50%; background:{MAGENTA}; opacity:.10; }}
header img.logo {{ width:140px; margin-bottom:26px; }}
header .eyebrow {{ color:{MAGENTA}; font-weight:900; letter-spacing:.16em; font-size:12px;
                   text-transform:uppercase; }}
header h1 {{ font-size:44px; font-weight:900; margin:12px 0 8px; line-height:1.08; }}
header .meta {{ opacity:.8; font-size:15px; }}
header .prepared {{ margin-top:10px; font-size:13px; opacity:.65; }}
header .refline {{ margin-top:22px; display:flex; gap:10px; flex-wrap:wrap; }}
header .refchip {{ font-size:11px; font-weight:900; letter-spacing:.06em; border-radius:999px;
                   padding:6px 15px; background:rgba(255,248,236,.12); color:{CREAM}; }}
header .refchip.sample {{ background:{TEAL}; }}
header .tagline {{ margin-top:20px; font-size:18px; color:{ORANGE}; font-style:italic;
                   max-width:600px; line-height:1.45; }}

/* ---------- sections ---------- */
section {{ padding:36px 56px 10px; page-break-inside:avoid; }}
h2 {{ display:flex; align-items:center; gap:13px; font-size:21px; font-weight:900;
      border-bottom:3px solid {ORANGE}; padding-bottom:10px; margin-bottom:20px; }}
.secnum {{ min-width:36px; height:36px; border-radius:11px; background:{MULBERRY};
      color:{ORANGE}; font-weight:900; font-size:17px; display:flex; align-items:center;
      justify-content:center; flex:none; }}
p {{ font-size:14px; line-height:1.65; margin-bottom:12px; }}
ul {{ margin:0 0 12px 20px; }} li {{ font-size:14px; line-height:1.65; margin-bottom:5px; }}
strong {{ font-weight:900; }}

/* ---------- stats ---------- */
.stats {{ display:flex; flex-wrap:wrap; gap:12px; margin-bottom:18px; }}
.stat {{ background:#fff; border-radius:13px; padding:15px 19px; min-width:132px;
         box-shadow:0 4px 16px rgba(52,28,61,.08); border-top:4px solid {ORANGE};
         page-break-inside:avoid; }}
.stat .v {{ font-size:23px; font-weight:900; }}
.stat .l {{ font-size:10.5px; font-weight:900; text-transform:uppercase; letter-spacing:.08em;
            color:{MUTED}; }}
.stat .s {{ font-size:12px; color:{MUTED}; margin-top:2px; }}

/* ---------- tables ---------- */
table {{ width:100%; border-collapse:collapse; margin-bottom:8px; background:#fff;
         border-radius:12px; overflow:hidden; box-shadow:0 4px 16px rgba(52,28,61,.08);
         font-size:13px; page-break-inside:avoid; }}
th {{ background:{MULBERRY}; color:{CREAM}; text-align:left; padding:10px 12px; font-size:11px;
      font-weight:900; text-transform:uppercase; letter-spacing:.05em; }}
td {{ padding:9px 12px; border-bottom:1px solid {LINE}; }}
tbody tr:nth-child(even) td {{ background:#FFFCF3; }}
tr:last-child td {{ border-bottom:none; }}
.note {{ font-size:12px; color:{MUTED}; margin-bottom:16px; }}

/* ---------- quotes ---------- */
.quote {{ background:#fff; border-left:5px solid {ORANGE}; border-radius:0 12px 12px 0;
          padding:13px 16px 13px 46px; margin-bottom:10px; position:relative;
          box-shadow:0 4px 16px rgba(52,28,61,.06); page-break-inside:avoid; }}
.quote::before {{ content:"\\201C"; position:absolute; left:14px; top:0px; font-size:36px;
          font-weight:900; color:{ORANGE}; font-family:Georgia,serif; }}
.quote.neg {{ border-left-color:{RASP}; }} .quote.neg::before {{ color:{RASP}; }}
.quote .t {{ font-size:13.5px; font-style:italic; }}
.quote .m {{ font-size:11px; color:{MUTED}; margin-top:4px; }}

/* ---------- scores ---------- */
.scores {{ margin-bottom:18px; }}
.scorerow {{ display:flex; align-items:center; gap:12px; margin-bottom:9px; font-size:13px; }}
.scorerow .lab {{ width:190px; font-weight:900; }}
.bar {{ flex:1; background:{LINE}; border-radius:6px; height:13px; overflow:hidden; }}
.bar i {{ display:block; height:100%; background:{ORANGE}; }}
.scorerow .n {{ width:215px; font-size:11.5px; color:{MUTED}; }}

/* ---------- verdict ---------- */
.verdict {{ border-radius:13px; padding:15px 19px; margin-bottom:18px; color:#fff;
            font-size:14.5px; page-break-inside:avoid; }}
.verdict p {{ margin:0; color:#fff; }}

/* ---------- horizontal bar chart ---------- */
.hbars {{ background:#fff; border-radius:13px; padding:20px; margin-bottom:8px;
          box-shadow:0 4px 16px rgba(52,28,61,.08); page-break-inside:avoid; }}
.hbar {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; font-size:12.5px; }}
.hbar:last-child {{ margin-bottom:0; }}
.hbar .lab {{ width:185px; font-weight:900; flex:none; }}
.hbar .track {{ flex:1; background:#F6EDDB; border-radius:7px; height:21px; overflow:hidden; }}
.hbar .fill {{ height:100%; background:{MULBERRY}; border-radius:7px; }}
.hbar.hl .fill {{ background:{ORANGE}; }}
.hbar.hl .lab {{ color:{BURNT}; }}
.hbar .val {{ width:72px; font-weight:900; font-size:12.5px; flex:none; text-align:right; }}

/* ---------- scatter / positioning map ---------- */
.plot {{ position:relative; height:350px; background:#fff; border-radius:13px; margin-bottom:8px;
         box-shadow:0 4px 16px rgba(52,28,61,.08); overflow:hidden; page-break-inside:avoid;
         background-image:linear-gradient({LINE} 1px, transparent 1px),
                          linear-gradient(90deg, {LINE} 1px, transparent 1px);
         background-size:25% 25%; }}
.plot .axis {{ position:absolute; font-size:10px; font-weight:900; letter-spacing:.08em;
         text-transform:uppercase; color:{MUTED}; }}
.plot .axis.x {{ bottom:8px; right:12px; }}
.plot .axis.y {{ top:8px; left:12px; }}
.pt {{ position:absolute; transform:translate(-50%,-50%); display:flex; flex-direction:column;
       align-items:center; z-index:2; }}
.pt .dot {{ width:14px; height:14px; border-radius:50%; background:{MULBERRY}; }}
.pt .plabel {{ font-size:10.5px; font-weight:900; white-space:nowrap; margin-top:4px;
       background:rgba(255,255,255,.85); padding:1px 6px; border-radius:999px; }}
.pt.hl .dot {{ width:22px; height:22px; background:{ORANGE};
       box-shadow:0 0 0 7px rgba(255,167,11,.22); }}
.pt.hl .plabel {{ color:{BURNT}; font-size:11.5px; }}
.pt.ghost .dot {{ width:86px; height:86px; background:transparent;
       border:2.5px dashed {TEAL}; }}
.pt.ghost .plabel {{ color:{TEAL}; margin-top:-58px; max-width:110px; white-space:normal;
       text-align:center; line-height:1.3; background:none; }}

/* ---------- callout cards ---------- */
.callouts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(225px,1fr));
             gap:14px; margin-bottom:18px; }}
.co {{ background:#fff; border-radius:14px; padding:18px 18px 16px; border-top:4px solid {ORANGE};
       box-shadow:0 4px 16px rgba(52,28,61,.08); page-break-inside:avoid; }}
.co .kick {{ font-size:9.5px; font-weight:900; letter-spacing:.13em; color:{MAGENTA};
       text-transform:uppercase; }}
.co h3 {{ font-size:15px; font-weight:900; margin:7px 0 6px; line-height:1.3; }}
.co p {{ font-size:12.5px; color:#4A3356; line-height:1.55; margin:0; }}
.co .tag {{ display:inline-block; margin-top:10px; font-weight:900; color:{BURNT};
       font-size:12.5px; background:{CREAM}; border-radius:999px; padding:4px 12px; }}

/* ---------- endnote + repeating page footer ---------- */
.endnote {{ padding:30px 56px 24px; font-size:11.5px; color:{MUTED}; line-height:1.6; }}
table.pagewrap {{ width:100%; border-collapse:collapse; overflow:visible;
  background:transparent; border-radius:0; box-shadow:none; margin:0; font-size:inherit; }}
table.pagewrap > tbody > tr > td, table.pagewrap > tfoot > tr > td {{ padding:0; border:none;
  background:transparent; }}
.pagefoot {{ display:flex; justify-content:space-between; align-items:center;
  padding:10px 56px 14px; background:{CREAM}; border-top:2px solid {ORANGE}; }}
.pagefoot .brand {{ font-size:10px; font-weight:900; letter-spacing:.14em;
  text-transform:uppercase; color:{MULBERRY}; }}
.pagefoot .brand em {{ font-style:normal; color:{BURNT}; }}
.pagefoot .ref {{ font-size:9.5px; color:{MUTED}; }}
@media print {{
  body {{ background:{CREAM}; }}
  header {{ min-height:88vh; display:flex; flex-direction:column; justify-content:center;
            page-break-after:always; padding:48px; }}
  section {{ padding:26px 48px 4px; }}
  .endnote {{ padding:24px 48px 16px; }}
  .pagefoot {{ padding:10px 48px 14px; }}
}}
"""


def md(text):
    """Tiny markdown: **bold**, '- ' bullets, blank-line paragraphs."""
    out, bullets = [], []

    def flush():
        nonlocal bullets
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets = []

    for para in text.split("\n\n"):
        for line in para.strip().split("\n"):
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(line.strip()))
            if line.startswith("- "):
                bullets.append(line[2:])
            elif line:
                flush()
                out.append(f"<p>{line}</p>")
        flush()
    return "".join(out)


def render_block(b):
    t = b["type"]
    if t == "stats":
        cells = "".join(
            f'<div class="stat"><div class="l">{html.escape(i["label"])}</div>'
            f'<div class="v">{html.escape(str(i["value"]))}</div>'
            + (f'<div class="s">{html.escape(i["sub"])}</div>' if i.get("sub") else "")
            + "</div>"
            for i in b["items"])
        return f'<div class="stats">{cells}</div>'
    if t == "text":
        return md(b["md"])
    if t == "table":
        head = "".join(f"<th>{html.escape(str(h))}</th>" for h in b["headers"])
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>"
            for r in b["rows"])
        note = f'<div class="note">{html.escape(b["note"])}</div>' if b.get("note") else ""
        return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>{note}"
    if t == "quotes":
        return "".join(
            f'<div class="quote {"neg" if q.get("sentiment") == "neg" else ""}">'
            f'<div class="t">{html.escape(q["text"])}</div>'
            f'<div class="m">{html.escape(q.get("meta", ""))}</div></div>'
            for q in b["items"])
    if t == "score":
        rows = "".join(
            f'<div class="scorerow"><div class="lab">{html.escape(i["label"])}</div>'
            f'<div class="bar"><i style="width:{100 * i["score"] / i.get("out_of", 5):.0f}%"></i></div>'
            f'<div class="n">{i["score"]}/{i.get("out_of", 5)} — {html.escape(i.get("note", ""))}</div></div>'
            for i in b["items"])
        return f'<div class="scores">{rows}</div>'
    if t == "verdict":
        color = TONE.get(b.get("tone", "warn"), BURNT)
        return f'<div class="verdict" style="background:{color}">{md(b["md"])}</div>'
    if t == "bars":
        mx = max(i["value"] for i in b["items"]) or 1
        rows = "".join(
            f'<div class="hbar {"hl" if i.get("hl") else ""}">'
            f'<div class="lab">{html.escape(i["label"])}</div>'
            f'<div class="track"><div class="fill" style="width:{max(2, 100 * i["value"] / mx):.1f}%"></div></div>'
            f'<div class="val">{html.escape(str(i.get("display", i["value"])))}</div></div>'
            for i in b["items"])
        note = f'<div class="note">{html.escape(b["note"])}</div>' if b.get("note") else ""
        return f'<div class="hbars">{rows}</div>{note}'
    if t == "scatter":
        pts = "".join(
            f'<div class="pt {"hl" if p.get("hl") else ""} {"ghost" if p.get("ghost") else ""}"'
            f' style="left:{p["x"]}%;top:{p["y"]}%">'
            f'<div class="dot"></div><div class="plabel">{html.escape(p["label"])}</div></div>'
            for p in b["points"])
        note = f'<div class="note">{html.escape(b["note"])}</div>' if b.get("note") else ""
        return (f'<div class="plot"><div class="axis y">{html.escape(b.get("y_label", ""))}</div>'
                f'<div class="axis x">{html.escape(b.get("x_label", ""))}</div>{pts}</div>{note}')
    if t == "callouts":
        cards = "".join(
            f'<div class="co"><div class="kick">{html.escape(c.get("kicker", ""))}</div>'
            f'<h3>{html.escape(c["title"])}</h3><p>{html.escape(c["body"])}</p>'
            + (f'<span class="tag">{html.escape(c["tag"])}</span>' if c.get("tag") else "")
            + "</div>"
            for c in b["items"])
        return f'<div class="callouts">{cards}</div>'
    raise ValueError(f"unknown block type: {t}")


def logo_data_uri():
    for p in LOGO_CANDIDATES:
        if p.exists():
            return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    return None


def render_section(s):
    m = re.match(r"^(\d+)\.\s*(.*)$", s["title"])
    num, title = (m.group(1), m.group(2)) if m else ("", s["title"])
    chip = f'<span class="secnum">{num}</span>' if num else ""
    return (f'<section><h2>{chip}{html.escape(title)}</h2>'
            + "".join(render_block(b) for b in s["blocks"]) + "</section>")


def build(run_dir, make_pdf=True):
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "report.json").read_text())
    ref = data.get("ref") or "BKI-" + data["date"] + "-" + re.sub(
        r"[^A-Z0-9]", "", data["kitchen"].upper())[:8]
    logo = logo_data_uri()
    prepared = data.get("prepared_for")
    sections = "".join(render_section(s) for s in data["sections"])
    footer_brand = ('<div class="brand">AI Augmented Research <em>by Bhookle</em></div>'
                    f'<div class="ref">{html.escape(ref)} · {html.escape(data["date"])}</div>')
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Kitchen Intelligence — {html.escape(data["kitchen"])}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;900&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
<table class="pagewrap">
<tfoot><tr><td><div class="pagefoot">{footer_brand}</div></td></tr></tfoot>
<tbody><tr><td>
<header>{f'<img class="logo" src="{logo}" alt="Bhookle">' if logo else ''}
<div class="eyebrow">Kitchen Intelligence Report</div>
<h1>{html.escape(data["kitchen"])}</h1>
<div class="meta">{html.escape(data["location"])} · {html.escape(data["date"])}</div>
{f'<div class="prepared">Prepared for {html.escape(prepared)}</div>' if prepared else ''}
<div class="refline"><span class="refchip">{html.escape(ref)}</span>
<span class="refchip">AI Augmented Research by Bhookle</span>
{'<span class="refchip sample">SAMPLE</span>' if data.get("sample") else ''}</div>
{f'<div class="tagline">{html.escape(data["tagline"])}</div>' if data.get("tagline") else ""}
</header>{sections}
<div class="endnote"><strong>AI Augmented Research by Bhookle.</strong>
Compiled from publicly visible Zomato, Swiggy and Google data on {html.escape(data["date"])}.
Figures reflect what each platform displayed on that date and may change.
{f'Prepared for {html.escape(prepared)} — ' if prepared else ''}Bhookle · 865+ home chefs · 87% chef retention.</div>
</td></tr></tbody></table>
</body></html>"""
    out_html = run_dir / "report.html"
    out_html.write_text(doc)
    print(f"HTML: {out_html}")

    if make_pdf:
        chrome = next((c for c in [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            shutil.which("chromium"), shutil.which("google-chrome")] if c and Path(c).exists()), None)
        if chrome:
            out_pdf = run_dir / "report.pdf"
            subprocess.run([chrome, "--headless", "--disable-gpu", "--virtual-time-budget=4000",
                            f"--print-to-pdf={out_pdf}", "--no-pdf-header-footer",
                            out_html.resolve().as_uri()], check=True, capture_output=True)
            print(f"PDF:  {out_pdf}")
        else:
            print("PDF skipped: no Chrome/Chromium found (HTML is still complete).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    build(sys.argv[1], make_pdf="--no-pdf" not in sys.argv)
