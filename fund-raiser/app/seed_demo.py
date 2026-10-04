"""
Create a DEMO database full of obviously-fictional investors so the tracker can
be run (and screenshotted) without any real investor data or API keys.

    python seed_demo.py            # creates instance/investment_leads.db if empty
    python seed_demo.py --reset    # wipes the demo tables first

Everything here is invented: people, funds, portfolio companies, emails
(@example.com) and LinkedIn slugs (/in/demo-...). The AI drafts are stored in
the same pre-compose cache columns the real app fills with Claude, so the
LinkedIn / Email modals open instantly with a realistic personalised draft
even when ANTHROPIC_API_KEY is not set.
"""
import random
import sys
from datetime import datetime, timedelta

from app import app
from database import db, InvestmentLead, EmailTemplate, OutreachEvent

random.seed(42)
NOW = datetime.utcnow()

# name, type, contact, headline, portfolio co, sector, round, amount, status, score, tier
LEADS = [
    ("Asha Example",            "Angel",         "Asha Example",      "Angel Investor · ex-COO at Demo Grocers",      "Tiffin Demo Co",       "Home Food / Tiffin",      "Angel",    "₹50L", "New",               91, 1),
    ("Placeholder Seed Fund",   "Micro VC",      "Rohan Sample",      "Partner at Placeholder Seed Fund",             "Masala Sample Labs",   "D2C Spices",              "Seed",     "$750K","New",               88, 1),
    ("Kabir Fictional",         "Angel",         "Kabir Fictional",   "Founder, Sample Snacks · Angel investor",      "Crunchy Demo Foods",   "D2C Snacks",              "Angel",    "₹30L", "Reached Out",       86, 1),
    ("Demo Angel Syndicate",    "Angel Network", "Meera Placeholder", "Syndicate Lead at Demo Angel Syndicate",       "Ghar Ka Khana (demo)", "Cloud Kitchen",           "Pre-Seed", "₹1Cr", "Engaged",           84, 1),
    ("Nisha Testcase",          "Angel",         "Nisha Testcase",    "Angel · Consumer brands operator",             "Chai Demo Collective", "Beverages / QSR",         "Angel",    "₹25L", "New",               82, 1),
    ("Mock Street Ventures",    "Micro VC",      "Vikram Mockwell",   "Principal at Mock Street Ventures",            "Lunchbox Sample",      "Subscription Meals",      "Seed",     "$1M",  "Reached Out Again", 80, 1),
    ("Sample HNI Family Office","Family Office", "Ananya Sampleton",  "Investment Director at Sample HNI FO",         "Organic Demo Farms",   "Farm-to-Table",           "Seed",     "₹2Cr", "Didn't Respond",    78, 1),
    ("Arjun Notreal",           "Angel",         "Arjun Notreal",     "Angel investor · ex-CMO, Example Retail",      "Dabba Demo",           "Home Food",               "Angel",    "₹40L", "New",               77, 1),
    ("First Cheque Example Club","Angel Network","Divya Fakename",    "Co-founder at First Cheque Example Club",      "Pickle Sample Co",     "D2C Packaged Food",       "Pre-Seed", "₹75L", "Reached Out",       76, 1),
    ("Imaginary Capital",       "Solo GP",       "Sameer Imaginary",  "Solo GP at Imaginary Capital",                 "Millet Mock Foods",    "Health Food",             "Seed",     "$500K","New",               74, 1),
    ("Priya Dummydata",         "Angel",         "Priya Dummydata",   "Angel · Partner at Example Law LLP",           "Sweet Sample Mithai",  "Sweets / D2C",            "Angel",    "₹20L", "Engaged",           73, 1),
    ("Lorem Ipsum Angels",      "Angel Network", "Karan Loremson",    "Deal Lead at Lorem Ipsum Angels",              "Bowl Demo Kitchens",   "Cloud Kitchen",           "Seed",     "₹1.5Cr","Not Interested",   72, 1),
    ("Rahul Specimen",          "Angel",         "Rahul Specimen",    "Angel · VP Product at Demo Delivery",          "Breakfast Sample Co",  "Consumer Tech",           "Angel",    "₹35L", "New",               69, 2),
    ("Test Kitchen Capital",    "Micro VC",      "Farah Testwala",    "Associate at Test Kitchen Capital",            "Sample Sauces",        "FMCG",                    "Seed",     "$600K","Reached Out",       67, 2),
    ("Sneha Madeup",            "Angel",         "Sneha Madeup",      "Angel investor · D2C founder (exited)",        "Granola Demo",         "Health Snacks",           "Angel",    "₹15L", "Didn't Respond",    65, 2),
    ("Faux Fund I",             "Micro VC",      "Aditya Fauxman",    "Managing Partner at Faux Fund I",              "Fresh Mock Dairy",     "Dairy / D2C",             "Pre-Seed", "$400K","New",               63, 2),
    ("Neha Hypothetical",       "Angel",         "Neha Hypothetical", "Angel · ex-Head of Growth, Sample Quick-commerce","Meal Kit Example",   "Meal Kits",               "Angel",    "₹25L", "Not Interested",    61, 2),
    ("Sandbox Scouts",          "Scout",         "Ishaan Sandbox",    "Scout at Sandbox Scouts",                      "Tea Demo Estates",     "Beverages",               "Pre-Seed", "₹40L", "New",               60, 2),
    ("Zara Fictitious",         "Angel",         "Zara Fictitious",   "Angel · Brand consultant",                     "Bakery Sample House",  "Bakery",                  "Angel",    "₹10L", "Reached Out",       58, 2),
    ("Example Consumer Partners","Micro VC",      "Dev Exampleton",    "Partner at Example Consumer Partners",         "Spice Route Demo",     "D2C Spices",              "Seed",     "$1.2M","Reached Out Again", 57, 2),
    ("Tanvi Notarealname",      "Angel",         "Tanvi Notarealname","Angel · CFO at Demo Hospitality",              "Healthy Tiffin Mock",  "Home Food / Tiffin",      "Angel",    "₹20L", "New",               55, 2),
    ("Mockingbird Angels",      "Angel Network", "Yusuf Mockingbird", "Network Manager at Mockingbird Angels",        "Regional Bites Demo",  "Regional Cuisine",        "Pre-Seed", "₹60L", "Engaged",           54, 2),
    ("Varun Samplesingh",       "Angel",         "Varun Samplesingh", "Angel · Founder, Example Logistics",           "Cold Chain Demo",      "Hyperlocal Delivery",     "Angel",    "₹30L", "Not Interested",    52, 2),
    ("Placebo Ventures",        "Micro VC",      "Leela Placebo",     "Principal at Placebo Ventures",                "Ready-to-Cook Sample", "Packaged Food",           "Seed",     "$800K","New",               50, 2),
    ("Gauri Pretend",           "Angel",         "Gauri Pretend",     "Angel · Food blogger turned investor",         "Home Chef Demo Market", "Home Food Marketplace",  "Angel",    "₹12L", "Didn't Respond",    48, 2),
]

TRIGGERS = [
    "Backed {co} ({round}, {amount}) in the last 90 days",
    "Posted on LinkedIn about home-food unit economics last month",
    "Fresh fund close — actively writing first cheques in consumer",
    "Co-invested with a food-tech angel syndicate this quarter",
    "Spoke on a consumer-brands panel about regional cuisine",
]
ACTIONS = [
    "Lead with chef-supply moat + repeat-rate; reference {co}",
    "Open with subscription retention numbers; ask for 20 min",
    "Mention B2B catering revenue line — overlaps their thesis",
    "Reference their {co} cheque; position Bhookle as adjacent",
]
REJECTIONS = {"Lorem Ipsum Angels": "Thesis Misfit",
              "Neha Hypothetical": "Traction Concerns",
              "Varun Samplesingh": "Portfolio Misfit"}


def slug(name):
    return "demo-" + name.lower().replace(" ", "-")


def li_connect(first, co):
    return (f"Hi {first}, saw you backed {co} — love seeing cheques go into home food. "
            "I'm the founder of Bhookle, a marketplace for home-cooked meals: bootstrapped, "
            "[X]K+ meals, [X]% repeat, now raising ₹[X] Cr to open [N] new cities. Would value connecting!")[:300]


def li_dm(first, co, sector):
    return (f"Hi {first} — thanks for connecting.\n\n"
            f"Your bet on {co} caught my eye: {sector.lower()} only works when supply is "
            "reliable and repeat is high, which is exactly the problem we've spent two years on.\n\n"
            "Bhookle is the \"Airbnb of home-cooked food\":\n"
            "• [X]K+ meals delivered, [X]% repeat customers\n"
            "• [N] home chefs onboarded, ₹[X] Cr paid out to chefs\n"
            "• 3 revenue lines — B2C, subscriptions, B2B catering\n"
            "• [X]% word-of-mouth growth, near-zero paid spend\n\n"
            "We're raising ₹[X] Cr to expand to [City A] & [City B]. Could I send the deck and "
            "grab 20 minutes this week?\n\n— Founder, Bhookle")


def em_body(first, co):
    return (f"Hi {first},\n\n"
            f"I noticed your recent investment in {co} — congratulations. Since you clearly "
            "understand how hard (and valuable) it is to get people eating well every day, I "
            "thought Bhookle might be interesting to you.\n\n"
            "Bhookle connects households with vetted home chefs in their neighbourhood. We've "
            "grown to [X]K+ meals and [X]% repeat customers, fully bootstrapped, with three "
            "revenue engines (B2C, subscriptions and B2B catering).\n\n"
            "We're now raising ₹[X] Cr to launch in [City A] & [City B]. I've attached a short "
            "deck — would you be open to a 20-minute call this week?\n\n"
            "Warm regards,\nFounder, Bhookle")


def main(reset=False):
    with app.app_context():
        db.create_all()
        if reset:
            OutreachEvent.query.delete()
            EmailTemplate.query.delete()
            InvestmentLead.query.delete()
            db.session.commit()
        if InvestmentLead.query.count():
            print("DB already has leads — run with --reset to rebuild the demo data.")
            return

        # ── Templates (the founder's approved base copy) ──
        db.session.add_all([
            EmailTemplate(name="LinkedIn connection note", stage="li_connect", locked=True, subject="",
                          body="Hi {investor_name}, I'm the founder of Bhookle — the \"Airbnb of home-cooked "
                               "food.\" Bootstrapped to [X]K+ meals and [N] home chefs; raising ₹[X] Cr to open [N] new "
                               "cities. Keen to connect!"),
            EmailTemplate(name="LinkedIn direct message", stage="li_dm", locked=True, subject="",
                          body="Hi {investor_name} — thanks for connecting.\n\nI'm the founder of Bhookle, the "
                               "\"Airbnb of home-cooked food.\" Two years in, fully bootstrapped:\n\n"
                               "• [X]K+ meals, [X]% repeat\n• [N] home chefs, ₹[X] Cr paid out\n"
                               "• B2C + subscriptions + B2B catering\n\nWe're raising ₹[X] Cr to expand to "
                               "[City A] & [City B]. Could I send the deck and grab 20 minutes?\n\n— Founder, Bhookle"),
            EmailTemplate(name="First-touch investor email", stage="new", locked=True,
                          subject="Bhookle — home-cooked food marketplace, raising seed",
                          body="Hi {investor_name},\n\nI'm the founder of Bhookle, a marketplace connecting "
                               "households with vetted home chefs. [X]K+ meals, [X]% repeat, bootstrapped.\n\n"
                               "We're raising ₹[X] Cr to launch [City A] & [City B] — deck attached. Open to a "
                               "20-minute call?\n\nWarm regards,\nFounder, Bhookle",
                          attachment_name="Bhookle-Deck-DEMO.pdf"),
            EmailTemplate(name="Re-engage: no response", stage="didnt_respond", locked=False,
                          subject="Quick update from Bhookle",
                          body="Hi {investor_name},\n\nA quick update since my last note: we crossed another "
                               "milestone this month and the round is now partly committed. Happy to share the "
                               "latest deck if useful.\n\nBest,\nFounder, Bhookle"),
        ])

        leads = []
        for i, (name, typ, contact, headline, co, sector, rnd, amt, status, score, tier) in enumerate(LEADS):
            first = contact.split()[0]
            created = NOW - timedelta(days=30 - i, hours=random.randint(0, 12))
            trig = random.choice(TRIGGERS).format(co=co, round=rnd, amount=amt)
            lead = InvestmentLead(
                investor_name=name, investor_type=typ, invested_company=co,
                investment_amount=amt, round_type=rnd, sector=sector,
                deal_date=f"2026-Q{random.randint(2, 3)}",
                key_contact=contact,
                email=f"{first.lower()}@example.com" if i % 6 != 4 else "",
                linkedin=f"https://www.linkedin.com/in/{slug(contact)}/" if i % 7 != 5 else "",
                contact_headline=headline,
                source_url=f"https://example.com/news/{slug(co)}",
                status=status,
                confidence_score=score,
                priority_tier="Tier 1 [High Intent]" if tier == 1 else "Tier 2 [Niche Fit]",
                trigger_signals=trig + "; India-based; first-cheque writer; consumer/food fit",
                action_item=random.choice(ACTIONS).format(co=co),
                signal_date=(NOW - timedelta(days=random.randint(5, 80))).strftime("%Y-%m-%d"),
                evidence_url=f"https://example.com/news/{slug(co)}-funding",
                evidence_note=f"{name} participated in {co}'s {rnd} round ({amt}) — demo source",
                verified=True,
                cached_news_hook=f"Backed {co} ({rnd}, {amt})",
                cached_li_connect=li_connect(first, co),
                cached_li_dm=li_dm(first, co, sector),
                cached_li_basis=f"Hook: their {co} investment (verified source). Confidence 90/100.",
                cached_li_personalized=True,
                cached_em_subject=f"{first}, a home-food bet adjacent to {co}",
                cached_em_body=em_body(first, co),
                cached_em_basis=f"Hook: their {co} investment (verified source). Confidence 90/100.",
                cached_em_personalized=True,
                rejection_reason=REJECTIONS.get(name),
                follow_up_date=((NOW + timedelta(days=random.randint(1, 10))).strftime("%Y-%m-%d")
                                if status in ("Reached Out", "Engaged", "Reached Out Again") else None),
                notes={"Engaged": "Replied — asked for the deck and unit economics. Call booked.",
                       "Not Interested": "Passed for now; open to revisit after next milestone.",
                       "Reached Out": "LinkedIn connection request sent.",
                       "Reached Out Again": "Second nudge sent after 5 days of silence.",
                       "Didn't Respond": "No reply after two touches."}.get(status, ""),
                created_at=created, updated_at=created,
            )
            db.session.add(lead)
            leads.append(lead)
        db.session.flush()

        # ── Outreach event log (drives the Report modal) ──
        for lead in leads:
            if lead.status == "New":
                continue
            first = (lead.key_contact or "").split()[0].lower()
            sent_at = NOW - timedelta(days=random.randint(1, 13), hours=random.randint(0, 9))
            db.session.add(OutreachEvent(lead_id=lead.id, event_type="sent", status_at="New",
                                         status_to="Reached Out", template_stage="li_connect",
                                         to_email=lead.linkedin, subject="LinkedIn connect",
                                         detail="LinkedIn connection request sent", created_at=sent_at))
            if lead.email:
                db.session.add(OutreachEvent(lead_id=lead.id, event_type="sent", status_at="New",
                                             status_to="Reached Out", template_stage="new",
                                             to_email=lead.email, subject=lead.cached_em_subject,
                                             message_id=f"<demo-{lead.id}@example.com>",
                                             created_at=sent_at + timedelta(hours=2)))
            if lead.status == "Engaged":
                db.session.add(OutreachEvent(lead_id=lead.id, event_type="reply", status_at="Reached Out",
                                             status_to="Engaged", to_email=lead.email,
                                             detail="Sounds interesting — please send the deck.",
                                             created_at=min(sent_at + timedelta(days=1),
                                                            NOW - timedelta(hours=1))))
            if lead.status == "Reached Out Again":
                db.session.add(OutreachEvent(lead_id=lead.id, event_type="sent", status_at="Didn't Respond",
                                             status_to="Reached Out Again", template_stage="didnt_respond",
                                             to_email=lead.email, subject="Quick update from Bhookle",
                                             created_at=min(sent_at + timedelta(days=5),
                                                            NOW - timedelta(hours=3))))
        # one bounce so the "bounced" tag + report sub-stat are visible
        bounced = next(l for l in leads if l.status == "Didn't Respond" and l.email)
        db.session.add(OutreachEvent(lead_id=bounced.id, event_type="bounce", to_email=bounced.email,
                                     detail="Delivery failure (bounce) — demo",
                                     created_at=NOW - timedelta(days=2)))
        db.session.commit()
        print(f"Seeded {len(leads)} fictional leads, "
              f"{EmailTemplate.query.count()} templates, "
              f"{OutreachEvent.query.count()} outreach events.")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
