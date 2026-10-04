# AdsManager — Analysis Framework

Six dimensions, in the order they appear in the report.

---

## 1. Campaign Performance

**What we measure (per campaign):**
- 90d / 30d / 7d windows for: spend, impressions, clicks, CTR, CPC, CPM, reach, frequency, installs, CPI
- Trend signals: CTR decay % (7d vs 30d), CPI spike % (7d vs 30d)
- Daily budget vs actual pacing

**Benchmarks for Bhookle (India Android App Installs):**
- **Efficient CPI:** ≤ ₹5
- **Acceptable CPI:** ₹5–15
- **Concerning CPI:** > ₹15
- **Healthy CTR:** ≥ 1.0%
- **Concerning CTR:** < 0.5%
- **Healthy frequency (30d):** ≤ 2.0
- **Saturation frequency:** > 2.5

**Commentary rules:**
- If CPI < ₹5 → "Strong unit economics"
- If CPI > ₹15 → "Audience-creative mismatch or saturation"
- If CPI spike > 25% week-over-week → "Fatigue or auction-pressure signal"
- If frequency > 2.5 → "Same users seeing ads too often"
- If a "retarg*" campaign optimizes for APP_INSTALLS → "Likely mis-configured" (retargeting audience has already installed)

---

## 2. Creative Fatigue Analysis

**Fatigue score (0–9):**

| Signal | Threshold | Points |
|---|---|---|
| CTR decay (7d vs 30d) | < -20% | +3 |
|  | < -10% | +2 |
|  | < -5% | +1 |
| CPI spike (7d vs 30d) | > +50% | +3 |
|  | > +25% | +2 |
|  | > +10% | +1 |
| Frequency (30d) | > 3.0 | +2 |
|  | > 2.5 | +1 |
| Creative age | > 180 days | +1 |
| Video hold-rate (% reaching P100) | < 5% | +1 |

**Levels:**
- Score ≥ 5 → **HIGH** (recommend pause)
- Score 3–4 → **MEDIUM** (monitor + plan refresh)
- Score 1–2 → **LOW** (no action)
- Score 0 → **NONE**

**Video completion funnel:**
For video creatives, the funnel P25 → P50 → P75 → P100 reveals where users drop off:
- Sharp drop from P25 → P50: the hook is good but the message dies in the middle
- Smooth drop: pacing is fine but length may be too long
- High P100 hold rate (>15%): exceptional video — study and replicate

---

## 3. Targeting & Audience Review

**Per ad set:**
- Optimization goal (and whether it aligns with the campaign's apparent intent)
- Bid strategy
- Daily budget
- Demographics: age range, genders
- Geography: countries, cities, regions
- Interests (flexible_spec)
- Exclusions

**Flags raised automatically:**
- Retargeting campaign optimized for APP_INSTALLS → mis-configuration
- > 10 interests stacked → may dilute precision
- Single-city only → consider geo expansion if creative is performing

**Manual review prompts (added to commentary):**
- Is the age range too broad? Bhookle's primary persona is 25–45 working professionals.
- Are excluded audiences set? E.g., existing app installers should typically be excluded from acquisition campaigns.
- Is the bid strategy consistent across ad sets in the same campaign?

---

## 4. Budget Reallocation

**Rule:** If the worst-performing active campaign has CPI ≥ 1.5× the best-performing active campaign's CPI, recommend a move.

**Rationale template:**
> {best_campaign} delivers installs at ₹{best_cpi} vs ₹{worst_cpi} for {worst_campaign} — {multiple}x more efficient. Shifting budget here should compound install volume.

**Caveats to mention:**
- Sudden large budget moves (>20% increase) can reset Meta's learning. Stage moves over 2–3 days.
- A campaign with lower CPI but very low spend may not scale — efficiency at ₹100/day doesn't always hold at ₹1000/day.
- Always consider audience saturation. If the winning campaign's frequency is already > 2, more budget = more saturation, not more reach.

---

## 5. Improvement Opportunities

**Auto-surfaced opportunities:**

| Trigger | Opportunity |
|---|---|
| All active ads share near-identical copy | **Creative monotony** — test 2–3 distinct angles |
| One creative significantly outperforms others | **Scale the winner** — build variants of the top creative |
| All targeting is Bangalore-only with good CPI | **Geographic expansion** — Mumbai, Hyderabad, Pune |
| Mixed bid strategies in account | **Bid strategy A/B** — consolidate toward whatever's winning |
| Campaign spending < 50% of expected pace | **Underpacing** — budget cap too high, audience too narrow, or weak auction signal |

**Manual opportunities the marketer should consider each cycle:**
- Has the creative team been briefed on the winners? (Inform future creative production.)
- Are there seasonal angles to test (festivals, weather, time-of-day)?
- Has the landing page (Play Store listing) been updated to match the ad creative?
- Is there a retention story to tell? (App-event optimization, not just installs.)

---

## 6. Action Items

**Sorting priority:**
1. HIGH-priority creative pauses (immediate, no downside)
2. HIGH-priority targeting fixes (mis-optimized goals)
3. HIGH-priority budget reallocations
4. MEDIUM-priority creative refreshes (plan for next 2 weeks)
5. MEDIUM opportunity items
6. LOW reactivation candidates

**Action item structure:**
```json
{
  "id": 1,
  "priority": "HIGH",
  "category": "Creative",
  "title": "Pause fatigued creative: Revised Creative 03 – Copy 2",
  "rationale": "Fatigue score 7/9. CTR change 7d-vs-30d: -18%. CPI change: +117%. Frequency: 1.0. Video hold-rate to 100%: 5%.",
  "api_action": {"type": "pause_ad", "entity_id": "<AD_ID>"},
  "entity_name": "Revised Creative 03 – Copy 2",
  "status": "pending"
}
```

**Status values:**
- `pending` — not yet addressed
- `executed` — user approved and API call succeeded
- `skipped` — user chose to skip
- `modified` — user modified and executed with different params

---

## Account Health Score (0–100)

Starts at 100. Penalties:
- Blended CPI > ₹5: −15
- Blended CPI > ₹10: −15 (additional)
- Each fatigued active creative: −10 (capped at −30)
- Each HIGH-priority action item: −5 (capped at −20)

**Interpretation:**
- 90–100: Account is running cleanly
- 70–89: Some optimization opportunities; healthy overall
- 50–69: Material issues — address HIGH-priority items
- < 50: Significant inefficiency; deep review needed
