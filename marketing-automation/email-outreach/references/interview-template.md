# Stage 1 — Interview Template

Claude conducts this Q&A in 3 rounds before drafting any campaign.
Ask all questions in a round as a numbered list — don't ask one by one.

---

## Round 1 — Goals & Scope

1. **What is the primary goal of this email campaign?**
   (e.g. user activation, chef recruitment, order frequency, seasonal promo, re-engagement)

2. **Who is the audience?**
   (e.g. all app users, users who ordered in the last 30 days, users who haven't ordered in 60 days, chef applicants, Bengaluru-only)

3. **How many campaigns do you want to create in this session?**
   (Each campaign = a unique list + a unique email)

4. **Is there a hard deadline or event this campaign is tied to?**
   (e.g. a festival, a product launch, a flash sale)

---

## Round 2 — Campaign Themes (one set per campaign)

For each campaign (ask in one block):

1. **Campaign name** (internal reference, e.g. "June Re-engagement Blast")
2. **Theme / angle** — what story or emotion should this email lead with?
   (e.g. "nostalgia + Amma's cooking", "time-saving busy professional", "discovery — try something new")
3. **Key message** — what is the ONE thing you want the reader to take away?
4. **CTA** — what action should the reader take?
   (Always "Download the Bhookle app" or "Order on the Bhookle app" — never a URL)
5. **Tone** — pick one: warm & emotional / playful & light / urgent & direct / informative
6. **Any specific dishes, chefs, or cities to feature?**

---

## Round 3 — Logistics

1. **Preferred send date(s)?** (Claude will research best time-of-day in Stage 3)
2. **Reply-to email?** (default: `team@example.com`)
3. **Any content to avoid?** (competitors, pricing, sensitive topics)

---

## After the interview — Claude's output per campaign

For each campaign Claude produces:
- `name`: internal slug (lowercase-hyphenated)
- `subject`: email subject line (≤60 chars, no caps-lock, no emojis unless requested)
- `preview_text`: preheader (≤90 chars)
- `body_html`: full branded HTML email (Bhookle orange #FF6B00, clean layout, 600px max-width)
- `body_txt`: plain-text fallback
- `image_prompt`: prompt for Imagen 4 Ultra hero image (photo-realistic, food-forward, warm Indian tones)

Then Claude generates the hero image and presents the full campaign for approval.

## Approval gate
User must say one of: **"approve"**, **"looks good"**, **"confirmed"**, **"ship it"**
before Claude proceeds to Stage 2. Any other response = iterate on the draft.

## Copy rules (always apply)
- CTA: "Download the Bhookle app" or "Order now on Bhookle" — never a URL
- Never: bhookleeats.com or any web URL
- Never: emojis unless user explicitly requests
- Tone references: bhookle-brand-voice skill
- From name: "Bhookle" (not Bhookle Eats, not Bhookle Team)
- Unsubscribe line: required in footer — "To unsubscribe, reply with 'Unsubscribe'"
