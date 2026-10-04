#!/usr/bin/env python3
"""Build the chef-facing pricing sheet from a priced menu.json.

    python build_chef_pdf.py menu.json [-o Chef_Pricing_Sheet.pdf]

Renders the split table, and — where menu.json carries them — the market rationale, the
per-serving gain ticker, any rate changes, and one open question for the chef.
See references/chef-sheet.md for what belongs in each of those.
"""
import argparse, json, sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONTDIR = "/usr/share/fonts/truetype/dejavu/"
try:
    pdfmetrics.registerFont(TTFont("DJ", FONTDIR + "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DJ-B", FONTDIR + "DejaVuSans-Bold.ttf"))
except Exception:
    sys.exit("DejaVu fonts not found. They carry the rupee glyph; the built-in fonts do not.")

INK = colors.HexColor("#1a1a1a"); MUTED = colors.HexColor("#6b6b6b")
QTY = colors.HexColor("#3f5a8a"); NAVY = colors.HexColor("#1f3864")
BAND = colors.HexColor("#f4f5f7"); LINE = colors.HexColor("#d5d5d5")
CHEF = colors.HexColor("#8a6a1f"); ZC = colors.HexColor("#b23a2e")
BC = colors.HexColor("#2f6f4f"); UP = colors.HexColor("#1d7a4c")

def rs(v, dec=2):
    return "₹" + (f"{v:,.2f}" if dec else f"{v:,.0f}")

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("menu"); ap.add_argument("-o", "--out")
    a = ap.parse_args()
    menu = json.load(open(a.menu, encoding="utf-8"))
    chef = menu.get("chef", {}); rates = menu["rates"]; items = menu["items"]
    if any(i.get("customer_price") is None for i in items):
        sys.exit("Menu is not priced. Run price_menu.py first.")

    name = chef.get("brand") or chef.get("name", "Chef")
    out = a.out or f"{chef.get('name','Chef').split()[0]}_Chef_Pricing_Sheet.pdf"
    zp, bp = rates["zomato"], rates["bhookle"]
    keep = 1 - zp - bp

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=17*mm, rightMargin=17*mm,
                            topMargin=13*mm, bottomMargin=11*mm,
                            title=f"{name} - your Zomato pricing", author="Bhookle")
    H = ParagraphStyle("H", fontName="DJ-B", fontSize=15, textColor=INK, leading=19)
    S = ParagraphStyle("S", fontName="DJ", fontSize=9.5, textColor=MUTED, leading=13)
    H2 = ParagraphStyle("H2", fontName="DJ-B", fontSize=11.5, textColor=NAVY, leading=14.5,
                        spaceBefore=10, spaceAfter=4)
    N = ParagraphStyle("N", fontName="DJ", fontSize=8.6, textColor=colors.HexColor("#3a3a3a"),
                       leading=12.4, spaceAfter=4)
    NAME = ParagraphStyle("NAME", fontName="DJ-B", fontSize=9, textColor=INK, leading=11.4)
    QS = ParagraphStyle("QS", fontName="DJ", fontSize=7.5, textColor=QTY, leading=9.6, spaceBefore=1)
    DS = ParagraphStyle("DS", fontName="DJ", fontSize=7.0, textColor=MUTED, leading=8.9, spaceBefore=1)
    HD = ParagraphStyle("HD", fontName="DJ-B", fontSize=8, textColor=colors.white, leading=10.2, alignment=2)
    HDL = ParagraphStyle("HDL", parent=HD, alignment=0)
    HDc = ParagraphStyle("HDc", parent=HD, alignment=0)
    PR = ParagraphStyle("PR", fontName="DJ", fontSize=9, textColor=INK, leading=11.4, alignment=2)
    YOU = ParagraphStyle("YOU", fontName="DJ-B", fontSize=9, textColor=CHEF, leading=11.4, alignment=2)
    ZPS = ParagraphStyle("ZPS", fontName="DJ", fontSize=9, textColor=ZC, leading=11.4, alignment=2)
    BPS = ParagraphStyle("BPS", fontName="DJ", fontSize=9, textColor=BC, leading=11.4, alignment=2)
    TICK = ParagraphStyle("TICK", fontName="DJ-B", fontSize=7.1, textColor=UP, leading=9,
                          alignment=2, spaceBefore=1.5)
    CL = ParagraphStyle("CL", fontName="DJ", fontSize=8, textColor=INK, leading=10.6)
    CB = ParagraphStyle("CB", parent=CL, fontName="DJ-B")
    CR = ParagraphStyle("CR", parent=CL, alignment=2)

    st = []
    st.append(Paragraph(f"Your Zomato pricing &mdash; {esc(name)}", H))
    bits = [f"{len(items)} dishes"]
    if chef.get("kitchen_hours"): bits.append(f"kitchen hours {chef['kitchen_hours']}")
    bits.append("prepared by Bhookle")
    st.append(Paragraph(" &nbsp;·&nbsp; ".join(esc(b) for b in bits), S))
    st.append(Spacer(1, 4*mm))

    intro = Table([[Paragraph(
        "This sheet shows what the customer pays for each of your dishes, and how that money is "
        "divided. <b>Your rate is worked out first, and the customer price is built up from it</b> "
        "&mdash; so what reaches you is exactly what we agreed, on every dish. The second half "
        "explains why your prices are set where they are.",
        ParagraphStyle("in", fontName="DJ", fontSize=8.8, textColor=INK, leading=12.6))]],
        colWidths=[176*mm])
    intro.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#fbf8f0")),
        ("BOX", (0,0), (-1,-1), 0.7, CHEF), ("LEFTPADDING", (0,0), (-1,-1), 9),
        ("RIGHTPADDING", (0,0), (-1,-1), 9), ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
    st.append(intro); st.append(Spacer(1, 4*mm))

    W = 176.0
    bar = Table([[Paragraph(f"You keep {keep:.0%}", ParagraphStyle("b1", fontName="DJ-B", fontSize=9, textColor=colors.white, alignment=1)),
                  Paragraph(f"Zomato {zp:.0%}", ParagraphStyle("b2", fontName="DJ-B", fontSize=9, textColor=colors.white, alignment=1)),
                  Paragraph(f"Bhookle {bp:.0%}", ParagraphStyle("b3", fontName="DJ-B", fontSize=9, textColor=colors.white, alignment=1))]],
                colWidths=[W*keep*mm, W*zp*mm, W*bp*mm], rowHeights=[8*mm])
    bar.setStyle(TableStyle([("BACKGROUND", (0,0), (0,0), CHEF), ("BACKGROUND", (1,0), (1,0), ZC),
        ("BACKGROUND", (2,0), (2,0), BC), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0)]))
    st.append(bar)
    st.append(Paragraph("How every ₹100 the customer pays is divided. Zomato's share and Bhookle's "
        "share are each taken from the customer price, not from each other.",
        ParagraphStyle("cap", fontName="DJ", fontSize=7.6, textColor=MUTED, leading=10, spaceBefore=2)))
    st.append(Spacer(1, 3.5*mm))

    comm = rates.get("assumed_current_commission")
    show_tick = comm is not None and any(i.get("her_live_price") or i.get("prior_chef_rate") for i in items)
    head2 = ("Your rate<br/><font size=6.6>vs today</font>" if show_tick else "You<br/>get")
    data = [[Paragraph("Dish", HDL), Paragraph("Customer<br/>pays", HD), Paragraph(head2, HD),
             Paragraph("Zomato<br/>gets", HD), Paragraph("Bhookle<br/>gets", HD)]]
    for i in items:
        c = i["customer_price"]
        cell = [Paragraph(esc(i["name"]), NAME)]
        if i.get("serving_size"):
            cell.append(Paragraph(esc(i["serving_size"]).replace(" - ", " · "), QS))
        if i.get("description"):
            cell.append(Paragraph(esc(i["description"]), DS))
        chefcell = [Paragraph(rs(i["net_to_chef"]), YOU)]
        base = None
        if i.get("prior_chef_rate") is not None:
            base = i["prior_chef_rate"]
        elif i.get("her_live_price") and comm is not None:
            base = i["her_live_price"] * (1 - comm)
        if base is not None:
            g = i["net_to_chef"] - base
            arrow, col = ("&#9650;", UP) if g >= 0 else ("&#9660;", ZC)
            chefcell.append(Paragraph(
                f'<font color="#{col.hexval()[2:]}">{arrow} {rs(abs(g))}/serving</font>', TICK))
        data.append([cell, Paragraph(rs(c, 0), PR), chefcell,
                     Paragraph(rs(i["zomato_cut"]), ZPS), Paragraph(rs(i["bhookle_cut"]), BPS)])

    t = Table(data, colWidths=[82*mm, 24*mm, 27*mm, 23*mm, 23*mm], repeatRows=1)
    sty = [("BACKGROUND", (0,0), (-1,0), NAVY), ("VALIGN", (0,0), (-1,0), "MIDDLE"),
           ("TOPPADDING", (0,0), (-1,0), 6), ("BOTTOMPADDING", (0,0), (-1,0), 6),
           ("VALIGN", (0,1), (-1,-1), "TOP"),
           ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
           ("TOPPADDING", (0,1), (-1,-1), 2.9), ("BOTTOMPADDING", (0,1), (-1,-1), 2.9),
           ("LINEBELOW", (0,1), (-1,-1), 0.35, LINE)]
    for r in range(1, len(data)):
        if r % 2 == 0:
            sty.append(("BACKGROUND", (0,r), (-1,r), BAND))
    t.setStyle(TableStyle(sty)); st.append(t)

    # ---- rationale ----
    ex = 100 if not items else int(round(sum(i["chef_rate"] for i in items)/len(items)/10)*10)
    up = ex * (1 + zp + bp); short = ex - up * keep
    st.append(Paragraph("Why your prices are set this way", H2))
    st.append(Paragraph(
        f"<b>We divide, we do not add.</b> Take a dish where your rate is {rs(ex,0)}. Adding "
        f"{zp+bp:.0%} on top would give {rs(up,0)} &mdash; but after Zomato and Bhookle take their "
        f"shares of that, only {rs(up*keep)} would reach you. You would be {rs(short)} short. "
        f"Instead we divide your {rs(ex,0)} by {keep:.0%}, and after both commissions your full "
        f"rate reaches you. The two methods look similar and are not, and the second one is the "
        f"reason your rate holds on every dish.", N))

    market = menu.get("market", {})
    if market.get("competitors"):
        loc = chef.get("locality")
        st.append(Paragraph("<b>Your kitchen's neighbourhood shapes the price.</b> "
            + (f"We checked what kitchens near {esc(loc)} charge, " if loc else "We checked what nearby kitchens charge, ")
            + "so your menu goes live at a price people there already pay.", N))
        rows = [[Paragraph("Kitchen near you", HDc), Paragraph("Rating", HDc), Paragraph("What they charge", HDc)]]
        for c in market["competitors"]:
            rows.append([Paragraph(esc(c.get("name","")), CB),
                         Paragraph(esc(c.get("rating","")), CL),
                         Paragraph(esc(c.get("prices","")), CL)])
        tb = Table(rows, colWidths=[46*mm, 20*mm, 110*mm])
        s2 = [("BACKGROUND", (0,0), (-1,0), NAVY), ("VALIGN", (0,0), (-1,-1), "TOP"),
              ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
              ("TOPPADDING", (0,0), (-1,-1), 4.5), ("BOTTOMPADDING", (0,0), (-1,-1), 4.5),
              ("LINEBELOW", (0,0), (-1,-1), 0.35, LINE)]
        for r in range(2, len(rows), 2):
            s2.append(("BACKGROUND", (0,r), (-1,r), BAND))
        tb.setStyle(TableStyle(s2)); st.append(tb)
    for note in market.get("notes", []):
        st.append(Paragraph(esc(note).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"), N))

    changes = menu.get("changes", [])
    if changes:
        st.append(Paragraph("What changed, and what it cost", H2))
        if menu.get("changes_intro"):
            st.append(Paragraph(esc(menu["changes_intro"]), N))
        rows = [[Paragraph("Dish", HDc), Paragraph("Your rate<br/>before", HD),
                 Paragraph("Your rate<br/>now", HD), Paragraph("Customer<br/>before", HD),
                 Paragraph("Customer<br/>now", HD), Paragraph("Why", HDc)]]
        for c in changes:
            rows.append([Paragraph(esc(c["name"]), CB), Paragraph(rs(c["old_chef_rate"], 0), CR),
                         Paragraph(rs(c["new_chef_rate"], 0), CR),
                         Paragraph(rs(c["old_customer_price"], 0), CR),
                         Paragraph(rs(c["new_customer_price"], 0), CR),
                         Paragraph(esc(c.get("why", "")),
                                   ParagraphStyle("wy", parent=CL, fontSize=7.4, leading=9.6, textColor=MUTED))])
        tc = Table(rows, colWidths=[43*mm, 21*mm, 21*mm, 24*mm, 22*mm, 45*mm])
        s3 = [("BACKGROUND", (0,0), (-1,0), NAVY), ("VALIGN", (0,0), (-1,-1), "TOP"),
              ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
              ("TOPPADDING", (0,0), (-1,-1), 4.5), ("BOTTOMPADDING", (0,0), (-1,-1), 4.5),
              ("LINEBELOW", (0,0), (-1,-1), 0.35, LINE)]
        for r in range(2, len(rows), 2):
            s3.append(("BACKGROUND", (0,r), (-1,r), BAND))
        tc.setStyle(TableStyle(s3)); st.append(tc)

    if menu.get("open_question"):
        st.append(Paragraph("One dish we would like your view on", H2))
        st.append(Paragraph(esc(menu["open_question"]), N))

    foot = ("Prices are per single order, before GST and before any discount Zomato funds itself. "
            "Dish descriptions and quantities are as you gave them to us.")
    if comm is not None:
        foot += (f" Comparisons against what you earn today assume a {comm:.0%} commission on your "
                 f"own listing; your actual rate should be confirmed.")
    st.append(Spacer(1, 3*mm))
    st.append(Paragraph(foot, ParagraphStyle("src", fontName="DJ", fontSize=7.3,
                                             textColor=MUTED, leading=9.8)))
    doc.build(st)
    print(f"Wrote {out} — {len(items)} dishes")


if __name__ == "__main__":
    main()
