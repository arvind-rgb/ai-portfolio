# Self-Critique Rubric — Test-Case Catalog Coverage (v2, screen-first)

Used in Phase 3. The TC catalog must score **≥ 90 / 100** before the suite is allowed to run. Re-score after every regeneration.

> v2 change: coverage is **screen-first** and must include **in-page actions**, not just journeys. The `type` axis is `core`/`extra` (not smoke/regression). Test nature lives in `category` (smoke / functional / negative / edge / data-variation).

## Scoring axes

### A. Journey-core coverage — 25 points

For each journey in `state/flows/user-flow.md`, check that at least one **`core`** TC exists (P0 where the journey is revenue-critical).

- Score = `25 × (journeys with ≥1 core TC) / (total journeys)`.
- Secondary journeys (Search, Festival) may legitimately top out at P1/P2 but still need a `core` TC.

### B. Screen / in-page coverage — 25 points

For each screen in `state/flows/screen-flow.md` (and every screen visible in the product screenshots):

- The screen has a `core` happy-path TC, **and**
- Its in-page actions (buttons, toggles, steppers, filters, sort, accordions, inputs, modals, sheets) each have a TC.

Score = `25 × (screens with core happy-path + enumerated in-page actions) / (total screens)`. A control-dense screen (Cart, ChefFoodList, GetNow, Profile) left with one or two TCs is a defect and loses this axis fast.

### C. Negative-path coverage — 20 points

Each **critical screen** must have ≥1 `negative` or `edge` TC. Critical set: CartScreen, LoginScreen, OTPScreen, Payment (PhonePe), ChefFoodListScreen, Chef Registration, Contact Us Form, AddressCollectionScreen, Coupon Sheet.

Score = `20 × (critical screens with a negative/edge TC) / (critical screen count)`.

Must-cover gotchas (from `bhookleApp/CLAUDE.md §5` + v3 flows): Cart-tab-is-an-action (login redirect), Profile login-skip gate, exact order-status strings, Veg Mode two-valued, time-slot user selection, fixed tax breakup (Food GST 5% / Delivery GST 18%), address-is-anchor, dish_max_quantity cap, chef-register network-failure silent bug.

### D. Data-variation coverage — 15 points

- Veg Mode tested in **both** values ("all kitchens" + "Pure Veg kitchens") — required.
- Get Today **and** Get Later each have dedicated TCs — required.
- Coupon tested valid **and** invalid.
- At least one explicit `data-variation` category TC exists.
- Each check = `15 / 5` points (the fifth slot rewards guest-vs-logged variation on forms).

### E. Dormant-flow tagging — 15 points

The subscription self-serve PhonePe path, SubscriptionDetail, and RenewalCheckout must be tagged `dormant` and defaulted to `Skip-Until-Flag-On` (gated by `reduxIsSelfSubscriptionEnabled`, default false). Full marks only if every dormant TC is both tagged and skip-defaulted.

## Scoring procedure

1. Walk each axis, compute subtotal (the `build-tcs` self-critique snippet does this programmatically against `catalog.json`).
2. Sum to overall score; write it to `meta.critique_score` (+ `meta.critique_breakdown`).
3. If < 90: list the deficits explicitly (which screens/in-page actions/variations are missing), generate the additional TCs, save, re-score.
4. Report the final score and the per-axis breakdown.

## Output to user

| Axis | Score | Max | Notes |
|---|---|---|---|
| A — Journey-core coverage | 22 | 25 | 9/10 journeys have a core TC (Festival is extra-only) |
| B — Screen / in-page coverage | 23 | 25 | 31/33 screens have a core happy-path |
| C — Negative-path coverage | 20 | 20 | all 9 critical screens covered |
| D — Data-variation coverage | 15 | 15 | veg×2, today/later, coupon valid/invalid |
| E — Dormant-flow tagging | 15 | 15 | 3 dormant TCs tagged + skip-defaulted |
| **Total** | **95** | **100** | Above 90% gate ✅ |
