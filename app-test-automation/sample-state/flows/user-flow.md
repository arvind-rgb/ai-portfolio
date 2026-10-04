# Bhookle Consumer App — User Journeys (v3, verified)

- **Generated:** 2026-06-07 (full-repo verification pass)
- **App commit:** `9dc0c88`
- **Visual:** open [`journey-flow.html`](./journey-flow.html) in a browser.

**What changed since v2** — corrections grounded in code reads, with file:line:
- Subscription self-serve is **dormant** today (gated by BE flag `isSelfSubscriptionEnabled`, default false). Subscribe tab → silently redirects to a contact form.
- Order checkout (cart → payment → orderAck) happens **entirely inside CartScreen**. AddressCollectionScreen is NOT a checkout step.
- Get Today / Get Later / Subscribe are **parallel choices**, not a sequence. Get Today + Get Later converge at ChefFoodListScreen.
- Search is supplementary, not a journey lane.
- Festival booking is a contact form, not a purchase.

---

## Available test data (locked, pass-through to downstream skills)

- **Login:** phone `<TEST_PHONE>`, OTP `<TEST_OTP>`
- **Test chef:** `Demo Chef`, `chef_id = '99999'`
- **Default env:** SIT
- **App IDs:** iOS `com.app.Bhookle`, Android `com.id.Bhookle`, Expo scheme `bhookle`

---

# A. NEW USER FLOW — first install with registration

**Boot condition:** `reduxRegUserData == null` → `initialScreen = "GetStartedScreen"` (`AppNavigator.tsx:646`).

## A1. Onboarding chain (linear)

1. [GetStartedScreen] → tap "Get Started"
2. [LoginScreen] — enter phone → POST `/registered_users/send_otp` → 60s countdown
3. Enter OTP → POST `/registered_users/check_user` → POST `/registered_users/register_user` → POST `/registered_users/update_user_login`
4. → [WelcomeScreen] with `{ userDet, userAddressDataList }`
5. WelcomeScreen 3-way branch (`WelcomeScreen.tsx:33-62`):
   - **5a.** New user (no saved address) → [main] Bhookle tab in `WelcomeScreenSkip` mode
   - **5b.** 1 saved address → set Redux location → [main] Bhookle tab
   - **5c.** >1 saved address → [AddressCollectionScreen] picker → choose one → [main] Bhookle tab

**Negative paths:**
- Wrong OTP → inline error, retry; 60s resend timer
- Tap "Skip" on LoginScreen → `isUserLoginSkipped=true`, lands on [main] anyway. Cart and Profile tabs will gate to login on tap.

## A2. After main (pick ONE of three parallel modes)

From [main]/[LandingScreen], user picks a fulfilment mode. **Modes are parallel; they are not visited in sequence.**

### A2.GT — Get Today journey

6.GT. Tap **Get Today** tab → [GetNowScreen] — GET `/home_v3/get_now_home_data`
7.GT. Pick a category → [CategoryGetNowChefListScreen] (or search → [GetNowSearchScreen])
8.GT. Pick chef (`Demo Chef`) → [ChefFoodListScreen] — GET `/chefs_v3_1/get_kitchen_details`
9.GT. Add dish → Redux cart updates → CartBar visible

### A2.GL — Get Later journey

6.GL. Tap **Get Later** tab → [HomeScreen] — GET `/home_v3/get_home_chef_dish_list`
7.GL. Pick category → [CategoryFoodListScreen] / [CategoryChefListScreen] (or search → [SearchScreen])
8.GL. Pick chef → [ChefFoodListScreen]
9.GL. Add dish, **pick time slot** (e.g., `7:50 PM – 8:20 PM`) → Redux cart updates

### A2.SUB — Subscribe journey (form-submit only TODAY)

6.SUB. Tap **Subscribe** tab → [SubscriptionScreen]
7.SUB. Check `reduxIsSelfSubscriptionEnabled` (`SubscriptionScreen.tsx:842-850`):
   - **`false` (today)** → automatic redirect to [subscriptionRequestScreen]
   - `true` (dormant) → multi-step Step1→Step6 PhonePe path (see Journey D)
8.SUB. [subscriptionRequestScreen] — fill form (kitchen type, frequency, address, cuisine, etc.)
9.SUB. Submit → POST `/contact_us/subscription_contact` → BE writes lead
10.SUB. Success modal → goBack to [main]
**Journey ends here today. No order, no payment, no orderAck.**

## A3. Checkout (for Get Today + Get Later only)

10. Tap Cart tab → [CartScreen]
11. (Optional) apply coupon → POST `/orders/validate_coupon`
12. (Optional) change address → [addressListScreen]
13. Tap "Proceed to Pay" → `generateOrderIdAndSaveOrder()` → POST `/orders/generate_order_id_and_save_order` (`CartScreen.tsx:538-600`)
14. PhonePePaymentSDK init + startTransaction (`CartScreen.tsx:718-771`)
15. `checkPaymentStatus()` → POST `/orders/check_payment_status` → returns `code`
16. Navigate to [orderAcknowledgementScreen] with `{ paymentStatus, cartData, deliveryDateTimeToHuman }`
17. Status branch:
    - `Payment Completed` → Success GIF + "Order Placed"
    - `Payment Pending` → Failed GIF + "Recheck on My Orders"
    - `Not Processed` → "Order Failed" + ops contact
18. Tap "My Orders" → [ordersScreen] (`upcoming_orders` tab on success, `past_orders` on failure)

## A4. Server-side post-order (FE not involved)

After step 13's POST, BE writes the order row → `BhooklePostgresqlTriggers` worker takes over (root CLAUDE.md §5):
- SendGrid confirmation email
- FCM push to chef
- WHAPI WhatsApp note
- Meta conversion event
- (Later) `OrderPickedUp`, `Delivered`, `Cancelled`, `Exception` transitions trigger further pushes/SMS/financial reconciliation

**FE has no polling.** User must revisit `ordersScreen` to see status changes.

---

# B. EXISTING USER FLOW — returning customer

**Boot condition:** Persisted `regUserData` → `initialScreen = "main"`. **Onboarding chain skipped entirely.**

1. App boots → [main] (Bhookle tab) → [LandingScreen] — GET `/home_v3/get_landing_page_data` (also refreshes `isSelfSubscriptionEnabled` flag)
2. Pick fulfilment mode — same parallel branches as A2:
   - **Get Today** (A2.GT) → ChefFoodList → cart → checkout (A3)
   - **Get Later** (A2.GL) — slot-pick → ChefFoodList → cart → checkout (A3)
   - **Subscribe** (A2.SUB) — form submit (today)
3. Convergence at orderAcknowledgementScreen (A3 step 16).

**Differences from new user:**
- Skips GetStarted/Login/Welcome.
- Address defaults to last-used. Can change via [addressListScreen] from CartScreen.
- Existing subscriptions visible at top of SubscriptionScreen (if flag ON) — can tap to view [SubscriptionDetailScreen].

**Negative paths same as A** plus:
- Persisted state corrupt → falls through to GetStartedScreen.
- Saved address no longer serviceable → checkout blocked until changed.

---

# C. BECOME A CHEF FLOW — supply-side lead

**Two entry points** (both verified):
- LandingScreen.tsx:966-980 — "Become A Chef" CTA on Home tab
- ProfileScreen.tsx:272-273 — tile

**Steps:**
1. → [chefRegisterRequestScreen]
2. Mixpanel event `BecomeAChefScreen` fires on focus (with userPhone/userCity if logged in, else string-event for guest)
3. Form fields: `contactName` (required, alpha+space), `vegKitchen` (required), `fssai` (required)
4. Tap Submit → POST `/contact_us/save_chef_register_request_contact` with `user: { uid: reduxUsrData?.uid || 'GUEST', userName: 'GUEST' }`
5. BE writes lead to `contact_us` table
6. Success: `callDynamicModal('SUCCESS', ..., json.messageTxt, 'Close')` → `goBack()`
7. Mixpanel event `ChefRegisterRequestSubmission` fires

**Negative paths:**
- Form validation: red "Required / Invalid" under invalid field, submit blocked
- **Network failure: silently logged to crashlytics only — no user-visible error** (`ChefRegisterRequestScreen.tsx:106-108`). **Bug — should be a negative TC.**
- Guest submission accepted with uid='GUEST'.

---

# D. SUBSCRIPTION SELF-SERVE — DORMANT (only active if BE flag flips)

Today this flow is gated OFF. Included for completeness so test catalog covers the flag-on scenario.

**Activation:** BE response `json.isSelfSubscriptionEnabled === true` on `/home_v3/get_landing_page_data` (`LandingScreen.tsx:225-227`).

When ON, SubscriptionScreen runs a multi-step state machine (`SubscriptionScreen.tsx:1138` `switch (currentStep)`):

1. **Step 1 SubscriptionOverview** — "Let's Go" → `setCurrentStep(2)` + `leadDraftCreation()` (POST `/contact_us/subscription_contact` draft)
2. **Step 2 MealSelection** — preferences
3. **Step 3 FoodChoices** — two outgoing edges:
   - "Next" → Step 4
   - "Want to customize?" → `setCurrentStep(9)` (Step 9 form path)
4. **Step 4 ChooseFrequency** — pick plan + start date → Step 5 + `updateLeadDraft()`
5. **Step 5 Customization** — dietary notes, delivery instructions → "Review Cart" → Step 6
6. **Step 6 CartOverview** — totals, address, T&Cs → tap "Pay ₹X" → `generateSubscriptionOrder()` → POST `/subscription/generate_subscription_order`
   - if `response.success && response.payment` → `initiatePhonePePayment()` → PhonePe SDK → `checkPaymentStatus()` → POST `/subscription/check_subscription_payment_status` → navigate to [orderAcknowledgementScreen] (subscription variant: copy says "Subscription #ID starts from {date}")
   - else → `Alert.alert("Error", response.message || "Failed to create subscription...")` — flow halts. **This is likely what would fire today since payment is BE-disabled.**
7. **Step 7 AddressChange** — side-path from Step 6
8. **Step 8 Checkout** — DEAD CODE. Not reachable; no `setCurrentStep(8)` exists.
9. **Step 9 CustomizeDishes (form)** — `handleCusReqSubmit` → POST `/contact_us/subscription_contact` → success modal → `goBack()`

**Renewal sub-flow** (`RenewalCheckoutScreen.tsx`):
- Reached from [SubscriptionDetailScreen] when renewal due.
- Same payment endpoints: `/subscription/generate_subscription_order`, `/check_subscription_payment_status`.
- Same dormancy caveat applies.

---

# E. POST-ORDER LIFECYCLE — server-side observability

FE doesn't drive these. Listed so test-case-generator knows what's verifiable from FE vs needs separate hooks.

| Order status | FE shows? | What test can do |
|---|---|---|
| `Payment Completed` (immediate after pay) | Yes — orderAck success | Maestro: assert success GIF rendered |
| `OrderPickedUp` | Only via ordersScreen revisit + push notification on device | DB hook: `orders.order_picked_up_timestamp` |
| `Delivered` | Only via ordersScreen revisit + push | DB hook: `orders.chef_payout`, `net_profit`, `chef_payment_status` |
| `Cancelled` | Only via ordersScreen + push | DB hook: new `subscription_orders` row for auto-reschedule |
| `Exception` | Push + SMS | Push receipt + status field |

> Worker rejects `final_state → Payment Completed` reverts (root CLAUDE.md §5.1). Do not synthesize.

---

# F. Cart-tab action (logged-out)

- Preconditions: no `regUserData`
- Tap Cart tab → listener detects no user → `navigation.navigate("login")` → [login]
- If logged-in but cart empty → silent no-op (toast)
- If logged-in with items → → [CartScreen]

# G. Profile-tab gate (login-skipped)

- Preconditions: `isUserLoginSkipped === true`
- Tap Profile tab → listener gate → `navigation.navigate("login")`

# H. Festival booking (contact form, not purchase)

- Reached via deep link / banner → [FestiveDishDetailScreen]
- Login required (`FestiveDishDetailScreen.tsx:51-52`) — guest redirected to login
- Submit form → POST `/contact_us/save_festival_request` → BE writes to `festival_dish_bookings`
- Back to [LandingScreen]

# I. Address management

- [addressListScreen] (in Profile stack) — list saved addresses, add new, delete
- [addAddressScreen] — Google Maps + form
- Used by: ProfileScreen, CartScreen (change address mid-checkout), AddressCollectionScreen (add from picker)

# J. Coupon apply

- Inside CartScreen → coupon input
- POST `/orders/validate_coupon` → success applies discount; failure shows inline error

# K. Veg Mode toggle (two-valued)

- "Veg from all kitchens" vs "Veg from Pure Veg kitchens" — root CLAUDE.md §5 — not boolean
- Toggle on discovery screens; persists via Redux Persist

# L. Support / contact submission

- [ProfileScreen] → [contactUsScreen] → POST `/general_contact_us/save_customer_request` → `user_query` table

---

## Coverage notes for `test-case-generator`

Locked gotchas every test set must respect (root CLAUDE.md §5 + app CLAUDE.md §5):

- **Order status strings are exact**: `Payment Completed`, `Delivered`, `Cancelled`, `OrderPickedUp`, `Exception` — no normalization.
- **Veg Mode is two-valued**, not boolean.
- **Time slots are user-selected** and server-validated.
- **Tax breakup fixed**: Food GST 5%, Delivery GST 18%.
- **Address is the anchor** for serviceability, dish availability, delivery fee, slots.
- **Cart tab is an action**, not a screen.
- **Profile tab respects login-skip**.
- **Boot routing is Redux-Persist-dependent** — new-user TCs must clear persisted state.
- **Subscription self-serve PhonePe path is BE-flag-controlled.** Default TCs should cover the form-submit path (today). Add a tagged flag-on TC for the dormant payment path.
- **AddressCollectionScreen is NOT in checkout.** Don't write TCs that traverse Cart → AddressCollection → Payment.
- **Festival booking is a lead form**, not a transaction.
- **Search is supplementary** — write its TCs separately, not as a sub-step in checkout journeys.

**Negative-path candidates:**
- Invalid phone, OTP retry/fail/timeout, payment cancelled/failed/pending
- Address out-of-serviceable-area, slot expiry
- Coupon invalid/used/min-cart-not-met
- Network offline at each lead-form submit
- Chef-register form validation, **chef-register network failure (silent bug)**
- Force-close mid-checkout
- Subscription self-serve while BE flag=false (verifies redirect to form)
