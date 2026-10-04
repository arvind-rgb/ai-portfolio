# Report Sections — Kitchen Intel (chef-shareable edition)

**The report is written to be handed to the kitchen owner.** Tone: respectful, direct,
numbers-first — the critique must feel like a gift, not an ambush. NO internal pitch
tactics in the report (no objection-handling, no "how to convince them" framing) —
put those in the chat summary for Arvind only.

Every claim states its source + date inline. Numbers only from what was observed this
run; unavailable data = "not publicly visible" (itself a finding). Use the visual blocks
(`bars`, `scatter`, `callouts` — see build_report.py docstring) wherever a chart says it
faster than a paragraph. `prepared_for` field goes on the cover ("Prepared for the team
at <kitchen>").

## 1. Kitchen Snapshot
Stats row (all platform ratings + counts, cost-for-two, delivery SLA, outlets, own
audience). Intro paragraph: what the kitchen is, since when, what customers consistently
say. Bullets: platform-identity inconsistencies, current offers, missing public basics.

## 2. Where <Kitchen> Stands Today
Two `callouts`: niche-keyword search rank vs mass-keyword search rank (measure both via
the Swiggy search API at the kitchen's own lat/lng). `bars`: rating-count vs competitor
set (order-volume proxy). Text: rating consistency, review velocity/staleness, owner
response behaviour. `verdict` block: one honest line.

## 3. The Cuisine: deep dive
Name the kitchen's actual culinary tradition precisely (region, sub-style) — usually
more specific than its own listings say. Map how the city currently serves that cuisine
(formats, players) and locate the unclaimed seat. Include dish-naming critique:
authentic names the menu fails to use are free authenticity + price power.

## 4. The Demand: who will order this food
Grounded city demographics → 3–4 target segments as `callouts`, each with kicker,
audience, evidence (population/community/office numbers with sources), and an
occasion/format tag. Never invent statistics — search and cite ranges honestly.

## 5. Brand Presence Review
`score` block (~6 dimensions /5) + specific fixable findings: identity splits, listing
errors, missing story, unanswered reviews. Frame errors as costing trust, not as blame.

## 6. Menu Deep-Dive
Heroes table (per-item price/rating/count + what it means), weak-tail paragraph
(name the items dragging the average), structural reading (who the menu serves today
and which audiences it has no answer for).

## 7. The Menu Gap: marketable items missing today
The standout section. `callouts` (5–7 cards): each a specific missing item with local
demand PROOF (a competitor's numbers, a daypart, a calendar event), fit with the
kitchen's existing skill, and a price-point tag. Include at least one zero-cost reframe
(naming/format of an existing dish) and one order-value raiser (family/festival format).

## 8. Price Intelligence
`bars`: hero-item price vs competitors. Item-level table vs 2–3 competitors with gap %.
Text: what the price gap means after ~25–30% aggregator commission (₹ net per plate),
whether ratings support a higher price point, and the kitchen's discount posture.

## 9. Competitive Landscape
`scatter`: price-for-two (x) vs rating (y), all radius competitors, kitchen highlighted,
plus a `ghost` point marking the open position. Competitor table (format, rating,
volume, price, distance). Text: who owns what, and why the open seat is theirs to take.

## 10. What Customers Are Saying
Theme table (positive vs negative mentions + reading). 4–6 short verbatim quotes
(≤15 words, sourced/dated, mixed sentiment). Text: what the review pattern rewards
amplifying and what it demands fixing.

## 11. The Road Ahead, Together
The Bhookle partnership section, chef-facing: what co-branding adds (audience,
brand craft, whitespace claim, per-plate economics), explicitly what does NOT change
(their kitchen, recipes, existing listings), and a simple low-risk first step.
Approved proof points: 865+ home chefs, 87% chef retention. CTA is always
"Download the Bhookle app" — never a URL.
