# Social Eval — Report Sections Specification

Seven sections. Write 2–7 first, then Section 1 (Executive Summary) last.
Section 1 is placed first in the PDF.

---

## Section 1 — Executive Summary
**Written last. Placed first in PDF.**

**Required content:**
- 5 key findings — one sentence each, the most important insight from each of sections 2–6
- Top-performing reel: caption snippet, engagement rate, what made it work
- Single biggest opportunity (from competitive benchmarking)
- 3 priority recommendations for next 30 days, ranked by expected impact

**Format:** 5 bullet findings + 2 callout boxes (Top Reel ER%, Avg ER%) + 3-item priority list

**Voice:** Decision-maker facing. Crisp, no jargon. A founder should be able to act on this page alone.

---

## Section 2 — Account Snapshot
**Data source:** Windsor.ai pull (ig_data + fb_data)

**Required content:**
- Instagram: follower count, 90-day reach, 90-day impressions, avg engagement rate, total reels published
- Facebook: page likes/followers, 90-day reach, avg engagement rate, total videos published
- 30-day follower growth delta (if available; flag with ⚠️ if not)
- Best-performing day of week (both platforms)
- Posting frequency: avg posts per week

**Charts assigned:** Chart A (90-day reach + engagement trend, dual-axis line)

**Callout boxes (yellow):** 4 stats — Total Reels Published / Avg ER% Instagram / Avg ER% Facebook / Follower Growth

**Format:** Callout boxes first, then 2–3 paragraphs of narrative, then Chart A

**Voice:** Factual, no editorialising. Let the numbers speak; add one-sentence context per metric.

---

## Section 3 — Reels Performance Deep-Dive
**Data source:** Windsor.ai ig_data (reel-level rows)

**Required content:**

**Top 5 reels** (ranked by engagement rate):
- For each: caption snippet (first 80 chars), publish date, plays, reach, ER%, likes, comments, saves, shares
- Pattern observation: what theme, format, hook, or timing contributed to its success

**Bottom 5 reels** (ranked by engagement rate):
- Same format as top 5
- Pattern observation: what may have suppressed performance

**Engagement by content theme:**
- Table: Theme | # Reels | Avg Plays | Avg ER% | Avg Saves
- Themes: Chef Story / Food Visual / Offer-Discount / UGC-Testimonial / Educational / Behind-the-Scenes

**Charts assigned:** Chart B (top 10 reels by ER%, horizontal bar) + Chart C (engagement by theme, grouped bar)

**Format:** Top 5 table → bottom 5 table → theme breakdown table → Chart B → Chart C

**Voice:** Specific and observational. Reference actual captions where possible. Avoid vague adjectives.

---

## Section 4 — What's Working
**Data source:** Synthesis from Section 3 analysis

**Required content:**
- 4–6 specific observations about patterns that correlate with high ER%
- For each: the pattern (e.g. "Chef backstory reels outperform food-only reels 2.3×"), the evidence (which reels, what numbers), and the hypothesis for why it works
- Posting timing insight: if a best day/time emerges, call it out explicitly
- Format insight: any format (e.g. 15-sec hook + voiceover, carousel vs single clip) that consistently outperforms

**Charts assigned:** Chart D (posting frequency by day-of-week, bar)

**Format:** Bulleted observations with sub-evidence, then Chart D

**Voice:** Analytical but encouraging. Frame findings as assets to double down on.

---

## Section 5 — What's Not Working
**Data source:** Synthesis from Section 3 analysis (bottom reels + low-performing themes)

**Required content:**
- 3–5 specific patterns that correlate with low ER%
- For each: the pattern, the evidence, and a hypothesis (e.g. "Offer-discount reels generate low saves suggesting the audience isn't purchase-ready")
- One honest observation about content gaps vs brand voice (reference `_context/` brand voice if available)
- Any signs of audience fatigue (declining trend, if detectable in the 90-day window)

**Format:** Bulleted observations with sub-evidence

**Voice:** Honest, constructive, non-judgmental. Frame as course-correction opportunities, not failures.

---

## Section 6 — Competitor Intelligence
**Data source:** WebSearch research (Step 2)

**For @cookr.india:**
- Estimated followers (flag as ⚠️ observed/estimated)
- Estimated posting cadence (reels/week)
- Dominant content themes (top 3)
- Brand tone description (2–3 adjectives)
- Standout recent content (describe 1–2 reels that appeared to perform well)
- CTA pattern (how do they drive action?)

**For @app_good_food:**
- Same dimensions

**Format:** One subsection per competitor (H3 heading), parallel structure

**Voice:** Neutral and observational. No speculation beyond what was observed. Always flag estimated data.

---

## Section 7 — Competitive Benchmarking & Recommendations
**Data source:** Sections 2–6 synthesis

**Required content:**

**Benchmarking table** (Bhookle vs @cookr.india vs @app_good_food):

| Dimension | Bhookle | Cookr | GoodFood |
|---|---|---|---|
| Est. Followers | | | |
| Posts/Week | | | |
| Dominant Theme | | | |
| Brand Tone | | | |
| Unique Strength | | | |
| Biggest Gap vs Bhookle | | | |

**Charts assigned:** Chart E (competitor ER% comparison, grouped bar) + Chart F (content strategy radar)

**Recommendations — 5 to 8 concrete ideas:**
For each recommendation:
- Title (bold, 5–8 words)
- What: specific content idea or format change
- Why: data or competitive rationale
- How: execution note (e.g. "Film 3 chef backstory reels in the next 2 weeks")
- Priority: High / Medium

**Format:** Benchmarking table → Chart E → Chart F → numbered recommendation list

**Voice:** Specific and actionable. Each recommendation must be executable without budget. Ground every idea in the data from sections 3–6.

---

## Writing order reminder

```
Step 3 → sections.md: Section 2 (Account Snapshot)
Step 3 → sections.md: Section 3 (Reels Deep-Dive)
Step 3 → sections.md: Section 4 (What's Working)
Step 3 → sections.md: Section 5 (What's Not Working)
Step 3 → sections.md: Section 6 (Competitor Intelligence)
Step 3 → sections.md: Section 7 (Benchmarking + Recommendations)
Step 3 → sections.md: Section 1 (Executive Summary — LAST)
```
