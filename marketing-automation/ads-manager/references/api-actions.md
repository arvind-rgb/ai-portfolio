# AdsManager — Marketing API Action Cookbook

All write operations against the Meta Marketing API. Use `api_actions.py` for code; this file
is for understanding what each action does and what to confirm with the user first.

---

## Status changes (low risk)

### Pause an ad
```python
from api_actions import pause_ad
pause_ad("<AD_ID>")
```

### Pause / activate a campaign
```python
pause_campaign("<ADSET_ID>")
activate_campaign("<ADSET_ID>")
```

### Pause / activate an ad set
```python
pause_adset("<ADSET_ID>")
activate_adset("<ADSET_ID>")
```

**Confirm with user before executing:** No — pause is reversible.
**Confirm before activating:** Yes — surface current budget and recent CPI.

---

## Budget changes (medium risk — affects spend)

### Set ad set daily budget (in rupees)
```python
set_adset_budget("<ADSET_ID>", 575)   # ₹575/day
```

### Set campaign daily budget
```python
set_campaign_budget("<ADSET_ID>", 1000)
```

**Always confirm rupee amount with the user.** Meta stores in paise (×100); the helper handles the conversion.

**Learning-phase caveat:** Bumping budget > 20% can reset Meta's learning. If the user proposes
a > 20% increase, mention this and ask if they want to stage the move over 2–3 days instead.

---

## Reallocate budget across ad sets

```python
reallocate_budget(
  from_adset_id="<ADSET_ID>",
  to_adset_id="<ADSET_ID>",
  amount_inr=230
)
```

Returns a diff: `{"from": {"old": 345, "new": 115}, "to": {"old": 345, "new": 575}}`.

**Confirm with user:**
- Source has enough headroom (the helper checks and errors if not)
- Target's resulting daily budget isn't > 1.2× the current value (learning reset risk)
- Both ad sets are still ACTIVE (pausing the source might be cleaner)

---

## Optimization goal changes

```python
set_adset_optimization_goal("<ADSET_ID>", "OFFSITE_CONVERSIONS")
```

**Valid goals (for app campaigns):**
- `APP_INSTALLS` — optimize for installs (default for new users)
- `OFFSITE_CONVERSIONS` — optimize for post-install events (first order, registration, purchase)
- `LINK_CLICKS` — optimize for cheap clicks (rarely useful for app)
- `LANDING_PAGE_VIEWS`
- `IMPRESSIONS` / `REACH` — awareness, never for performance
- `POST_ENGAGEMENT` — engagement campaigns
- `VALUE` — purchase value optimization

**When to switch:**
- Retargeting installed users → `OFFSITE_CONVERSIONS` with a post-install event
- New-user acquisition → `APP_INSTALLS` (default is correct)

**Warning:** Switching optimization goal mid-campaign resets the learning phase. Reserve for
clearly misconfigured ad sets, not minor tweaks.

---

## Create new campaign (skeleton)

```python
create_campaign(
  name="Bhookle_Android_NUA_HYD_July2026",
  objective="OUTCOME_APP_PROMOTION",
  daily_inr=300
)
```

Creates a **paused** campaign. Always paused — never let an unattended skill kick off a live spend.

Then direct user to Ads Manager to finish setup (ad sets, creative, targeting):
`https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=<AD_ACCOUNT_ID>`

**Why not full automation here?**
- Creative upload requires asset hashing — better in UI
- Targeting refinement is multi-step (audience size feedback, exclusions, lookalikes) — UI is faster
- The Marketing API can do all of it, but the friction-to-value ratio favours the UI for first-time setup

---

## Naming conventions (recommend these to the user)

`{Source}_{Platform}_{Audience}_{Geo}_{Date}`

Examples:
- `RR_Android_NUA_Bangalore_July2026` (retention/rollover, Android, new-user acquisition, Bangalore)
- `RT_Android_LowUsage_BLR_Aug2026` (retargeting, low app usage, Bangalore)
- `AMS_Android_Sales_Pan-India_Q3-2026` (advantage+ shopping)

Consistent naming makes the analysis script's auto-flagging (retargeting detection, etc.) more reliable.

---

## Field reference cheat-sheet

**Insights fields most useful for analysis:**
```
spend impressions clicks ctr cpc cpm reach frequency
actions cost_per_action_type
video_p25_watched_actions video_p50_watched_actions video_p75_watched_actions video_p100_watched_actions
purchase_roas lead
```

**Action types we filter on:**
```
omni_app_install      → app install (cross-device)
mobile_app_install    → mobile-only install
omni_purchase         → purchase
omni_activate_app     → app open after install
link_click            → link click
landing_page_view     → landing page view
video_view            → video view
post_engagement       → engagements
```

**Campaign objectives (the new "Outcome" naming):**
```
OUTCOME_APP_PROMOTION   → installs + post-install events
OUTCOME_SALES           → purchases / conversions
OUTCOME_LEADS           → lead-gen forms
OUTCOME_AWARENESS       → reach + brand lift
OUTCOME_TRAFFIC         → link clicks / landing page views
OUTCOME_ENGAGEMENT      → engagement / video views
```

---

## Common errors & recovery

| Error | Cause | Fix |
|---|---|---|
| `OAuthException · Permissions error` | System user role missing OR peer-approval policy blocking writes | Confirm Full Control + toggle off peer approval in Security Centre |
| `Invalid parameter · daily_budget` | Budget below minimum (₹96.54/day for INR accounts) | Surface to user, ask for higher amount |
| `Cannot edit this campaign` | Campaign is in `WITH_ISSUES` state | Check Ads Manager for the specific issue (often payment or policy) |
| `User has not granted access to this ad account` | System user not assigned to ad account | Re-assign the ad account to the system user with Manage permissions |
