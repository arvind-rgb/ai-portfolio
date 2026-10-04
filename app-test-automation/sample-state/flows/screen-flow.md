# Bhookle Consumer App — Screen Flow Map (v3, verified)

- **Generated:** 2026-06-07 (by `test-scan-app`, full-repo verification pass)
- **App commit:** `9dc0c88`
- **App dir:** `<path-to>/bhookleApp-v2`
- **Visual:** open [`journey-flow.html`](./journey-flow.html) in a browser.

**Major corrections vs v2** (every claim now has file:line):
1. **AddressCollectionScreen is NOT in the order checkout path.** Payment runs entirely inside CartScreen → PhonePe → orderAck. AddressCollectionScreen is the post-login address-picker / no-location fallback.
2. **Subscription self-serve payment is DORMANT.** The Step1→Step6 PhonePe path is gated by `reduxIsSelfSubscriptionEnabled` (default `false`, set from BE). Today, Subscribe tab silently redirects to `subscriptionRequestScreen` → form submit.
3. **Search is supplementary**, not a fulfilment lane — it's an always-on search bar widget on Landing/Home/GetNow.
4. **FestiveDishDetailScreen is a contact form**, not a purchase. POSTs to `/contact_us/save_festival_request`.

---

## 1. Boot routing — the "new" vs "existing" user split

`AppNavigator.tsx:646`:
```
const initialScreen = reduxRegUserData ? "main" : "GetStartedScreen";
```

| Boot state | Initial screen |
|---|---|
| Persisted `regUserData` (Redux Persist) | `main` — skips GetStarted/Login/Welcome entirely |
| No `regUserData` | `GetStartedScreen` — onboarding chain |

---

## 2. Onboarding chain (NEW USER ONLY)

```
GetStartedScreen ──tap Get Started──> login (LoginScreen)
                                       │
                                       ├─ enter phone (<TEST_PHONE>)  → /registered_users/send_otp
                                       ├─ enter OTP (<TEST_OTP>)        → /registered_users/check_user
                                       │                            → /registered_users/register_user
                                       │                            → /registered_users/update_user_login
                                       │
                                       ├─ tap "Skip"  ──> WelcomeScreen (skip-mode, isUserLoginSkipped=true)
                                       └─ OTP success ──> WelcomeScreen (userDet + userAddressDataList)
```

`WelcomeScreen.tsx:33-62` — 3-way branch:

| `userAddressDataList` | Action | Destination |
|---|---|---|
| `length == 1` | Auto-pick that address, set Redux location | `main` (Bhookle tab) |
| `length > 1` | User picks which | `AddressCollectionScreen` (picker) |
| `undefined` / skip-mode | No address yet | `main` (Bhookle tab, `navigatedFrom: WelcomeScreenSkip`) |

> WelcomeScreen suppresses hardware back: `WelcomeScreen.tsx:68-73`.

### 2.1 VERIFIED runtime auth path + selectors (iOS sim, SIT, 2026-06-08)

The structural chain above is correct, but two states only surface at runtime and broke automation:

- **(a) WelcomeScreen shows an intro carousel** ("Discover hundreds of home chefs…") with a **PROCEED** button *before* the address branch — tap PROCEED to advance.
- **(b) Multi-address accounts hit a location gate.** Test acct `<TEST_PHONE>` has >1 saved address in `public.user_address` → after PROCEED it lands on the location picker ("What's your location?") with **CHOOSE ADDRESS / ADD ADDRESS**. Must CHOOSE ADDRESS → pick a saved row → only then does LandingScreen render dishes. Single-address accounts auto-pick and skip this.

**Verified Maestro selectors** — ALWAYS substring regex `.*X.*` (iOS prefixes labels with `"In progress "`; full-match fails):

| Step | Selector | Notes |
|---|---|---|
| GetStarted CTA | `.*Get Started.*` | full-match `"Get Started"` FAILS on iOS |
| Phone field | iOS `point: 50%,38%` · Android `.*Phone Number.*` | iOS input not text-addressable (RN a11y grouping) |
| Get OTP | `.*Get OTP.*` | empty/invalid phone → `"Phone Number Required / Invalid"` |
| OTP view anchor | `.*Resend OTP.*` | countdown = OTP sent |
| OTP input | `.*One-Time Password.*` then `inputText <TEST_OTP>` | `react-native-otp-entry`, **auto-submits onFilled**; MUST focus-tap first |
| WelcomeScreen | `.*PROCEED.*` | intro carousel |
| Location gate | `.*CHOOSE ADDRESS.*` → point-tap saved row (iOS `50%,52%`) | only when no address selected |
| Landing anchor | `.*Get It Today.*` | authenticated Landing (real data: 14 chefs/146 dishes, Chennai) |

Canonical subflow: `maestro/subflows/auth-login.yaml` (cross-platform, platform-branched for phone/address). Uses a dedicated SIT test account (credentials injected from the Maestro env file, never committed).

---

## 3. The three fulfilment modes (PARALLEL CHOICES from `main`)

From the `main` (BottomTabNavigator), user picks one of three modes. **They are not sequential — they are independent journeys.** Get Today and Get Later converge at `ChefFoodListScreen → CartScreen → Payment → orderAck`. Subscribe is a separate journey today (form-only).

```
                       main (BottomTabNavigator)
            ┌───────────────┼────────────┬──────────────┐
            ▼               ▼            ▼              ▼
       Bhookle           GetNow         Home         Subscribe
      (LandingScreen)   (Get Today)   (Get Later)   (form today)
            │               │            │              │
            │               │            │              ▼
            │               │            │      reduxIsSelfSubscriptionEnabled?
            │               │            │          ├── true → Step1→6 PhonePe (DORMANT)
            │               │            │          └── false (TODAY) ────────────┐
            │               │            │                                        ▼
            │               │            │                          subscriptionRequestScreen
            │               │            │                                  (form submit)
            │               │            │                                        │
            │               │            │                              POST /contact_us/
            │               │            │                              subscription_contact
            │               │            │                                        │
            │               │            │                              SUCCESS modal → goBack
            │               │            │
            ▼               ▼            ▼
         ┌────── search widget (supplementary) ──────┐
         │  Top of Landing/Home/GetNow:              │
         │  → GetNowSearchScreen (if chefs > 0)      │
         │  → SearchScreen (else)                    │
         │  Both → ChefFoodListScreen                │
         └───────────────────────────────────────────┘
                 │             │            │
       Category lists → ChefFoodListScreen ← Category lists
                            │
                 add dish (Redux cart) → tap Cart tab → CartScreen
                                                          │
                                                          ▼
                              ┌─────── INSIDE CartScreen ───────┐
                              │ - validate coupon               │
                              │ - change address (→ addressList)│
                              │ - "Proceed to Pay"              │
                              │ - PhonePePaymentSDK              │
                              │ - /orders/generate_order...     │
                              │ - /orders/check_payment_status  │
                              └─────────────────────────────────┘
                                                          │
                                                          ▼
                                          orderAcknowledgementScreen
                                          (paymentStatus param)
                                                          │
                                                          ▼
                                          tap "My Orders" → ordersScreen
```

### 3a. Get Today (GetNow) lane

- `GetNowScreen.tsx:126` calls `/home_v3/get_now_home_data`.
- Subnav: category → `CategoryGetNowChefListScreen`; search → `GetNowSearchScreen`.
- Convergence: all routes → `ChefFoodListScreen`.

### 3b. Get Later (Home) lane

- `HomeScreen.tsx:263, 342` call `/home_v3/get_home_chef_dish_list[_more_data]`.
- Subnav: dish category → `CategoryFoodListScreen`; chef category → `CategoryChefListScreen`; search → `SearchScreen` (route `SearchStackSearch`); reviews → `ChefReviewListScreen`.
- HomeScreen carousel banner: ad_type `DISH | CHEF | DISH_CATEGORY | CHEF_CATEGORY` drive different nav targets (`HomeScreen.tsx:954-984`).
- Convergence: all routes → `ChefFoodListScreen`.

### 3c. Subscribe lane — DORMANT vs ACTIVE

`SubscriptionScreen.tsx:842-850` on focus:
```js
if (reduxIsSelfSubscriptionEnabled) {
  fetchSubscriptionEss(defSubData.user_city);   // Step1→Step6 (PhonePe path)
} else {
  props.navigation.navigate("Profile", {
    screen: "subscriptionRequestScreen",          // form-only path (TODAY)
  });
}
```

Flag origin: `LandingScreen.tsx:225-227` reads `json.isSelfSubscriptionEnabled` from `/home_v3/get_landing_page_data`. Default `false` in `reducers/appConfigTempReducer.ts:18`.

**Today (flag=false):** Subscribe tab → `subscriptionRequestScreen` → fill form → POST `/contact_us/subscription_contact` → success modal → goBack. No payment.

**If flag=true (dormant):** Step1 Overview → Step2 MealSelection → Step3 FoodChoices → Step4 ChooseFrequency → Step5 Customization → Step6 CartOverview → tap "Pay ₹X" → `/subscription/generate_subscription_order` → PhonePe SDK → `/subscription/check_subscription_payment_status` → `orderAcknowledgementScreen`.

**Always-available Step9 (Customization request form):** Step3 → tap "Want to customize?" → Step9 → POST `/contact_us/subscription_contact`.

**Step8Checkout** (`SubscriptionScreen.tsx:2145`) — **dead code**. No `setCurrentStep(8)` anywhere; pure UI mockup with `Alert.alert("Payment Simulated")`.

### 3d. Search — supplementary widget

`LandingScreen.tsx:683-692` — top-of-tab search bar routes contextually:
- `screenData.getNowHomeData?.chefs > 0` → GetNow stack → `GetNowSearchScreen` (same-day search)
- else → Home stack → `SearchScreen` (next-day search)

Same widget on `HomeScreen.tsx:810-813` and `GetNowScreen.tsx:457-458`.

The bottom-tab `Search` is commented out `AppNavigator.tsx:535-556`. **There is no standalone search journey.**

---

## 4. The one-off order checkout — **all inside CartScreen**

`CartScreen.tsx`. Endpoints + flow:

| Step | Code | Endpoint |
|---|---|---|
| Coupon validation | line 279 | `/orders/validate_coupon` |
| Cart-screen data (chef/dish refresh) | line 355 | `/chefs_v3_1/cart_screen_request` |
| Tap "Proceed to Pay" → `proceedToPay()` → `generateOrderIdAndSaveOrder()` | line 538-600 | `/orders/generate_order_id_and_save_order` |
| PhonePe SDK init + startTransaction | line 718-771 | (SDK) |
| `checkPaymentStatus()` | line 602-689 | `/orders/check_payment_status` |
| On success → navigate to orderAck | line 666-670 | — |

Address change from inside CartScreen → routes to `addressListScreen` (Profile stack), not `AddressCollectionScreen`.

**`AddressCollectionScreen` is NOT a step in checkout.** Its real uses:
- `WelcomeScreen.tsx:49-55` — multi-address picker after login.
- `LandingScreen.tsx:333-338` — no-location fallback at app open.

---

## 5. orderAcknowledgementScreen — payment-status branches

`OrderAcknowledgementScreen.tsx:15-16`:

| `paymentStatus` route param | UI | CTA target |
|---|---|---|
| `Payment Completed` | Success GIF + "Order Placed. Thank you!" | "My Orders" → `Profile > ordersScreen` (`screenFrom: upcoming_orders`) |
| `Payment Pending` | Failed GIF + "Recheck payment status on My Orders" (red) | "My Orders" → `ordersScreen` (`screenFrom: order_failed`) |
| `Not Processed` / other | Failed GIF + "Order Failed" + "contact us <support-email>" | "My Orders" → `ordersScreen` (`screenFrom: order_failed`) |

Subscription variant: when `cartData.chefName == "Subscription Chef"`, copy says "Subscription #ID starts from {date}" and CTA routes to Subscription tab instead.

---

## 6. Post-order lifecycle — server side, FE not involved

The FE does **not poll order status** post-orderAck. To see updates, user revisits `ordersScreen` which fetches `/orders/get_orders_list_by_uid` on focus.

All real-time post-order effects driven by `BhooklePostgresqlTriggers` worker (separate Node process; see root CLAUDE.md §5):

| Order status (set by BE) | Worker effects |
|---|---|
| `Payment Completed` | SendGrid order email · FCM push to chef · WHAPI WhatsApp note · Meta conversion event · `registered_users.user_source` normalize |
| `OrderPickedUp` | Sets `orders.order_picked_up_timestamp` · WhatsApp note to chef group · in-flight FCM + 2Factor SMS to customer |
| `Delivered` | Customer completion push · decrement `chefs.available_bags` · subscription rollups · Porter/Pidge fare → `chef_payout`, `net_profit`, `chef_payment_status` |
| `Cancelled` | Customer/ops notify · subscription daily-meal auto-reschedule (new `subscription_orders` row status `Yet to Create`) |
| `Exception` | Customer SMS + push with delay reason |

> **Critical:** worker guards against `final_state → Payment Completed` reverts (root CLAUDE.md §5.1). Tests must not synthesize that transition.

**For test-case-generator:** Maestro can verify the FE up to `orderAcknowledgementScreen` and a follow-up revisit to `ordersScreen`. Email/push/WhatsApp verification needs DB or mailbox hooks — out of scope for Maestro.

---

## 7. Become a Chef — supply-side lead form

Entry points (confirmed):
- `LandingScreen.tsx:966-980` — "Become A Chef" CTA
- `ProfileScreen.tsx:272-273` — tile

Behavior (`ChefRegisterRequestScreen.tsx`):
- Mixpanel: `BecomeAChefScreen` on focus.
- Form: `contactName`, `vegKitchen`, `fssai` (all required).
- Submit: POST `/contact_us/save_chef_register_request_contact` → BE writes to `contact_us` table (supply / chef-onboarding table, despite the name).
- Guest submissions accepted with `uid: 'GUEST'`.
- Success: `callDynamicModal('SUCCESS', ..., json.messageTxt, 'Close', ...)` → `goBack()`.
- **Network failure: only `crashlytics().recordError` + `console.log` — no user-visible retry. Bug to flag in test catalog.**

---

## 8. Festival booking — also a contact form

`FestiveDishDetailScreen.tsx:55` POSTs to `/contact_us/save_festival_request`. Not a purchase. Login required (line 51-52 redirects to login if `isUserLoginSkipped`). After submit → navigates back to LandingScreen.

---

## 9. Profile sub-screens

`ProfileScreen.tsx` is a menu, navigating to:
- `ordersScreen` — `/orders/get_orders_list_by_uid` with tab toggle `upcoming_orders | past_orders`
- `subscriptionDetailScreen` (also reachable from SubscriptionScreen)
- `addressListScreen` — `/user_address/get_address_list_by_uid` + delete
- `profileDetailsScreen` — read-only profile view
- `chefRegisterRequestScreen` (Become A Chef)
- `contactUsScreen` — POST `/general_contact_us/save_customer_request` → `user_query` table
- `faqScreen`, `privacyPolicyScreen`, `termsOfServiceScreen` — static content
- Logout (line 480) → `mixReset()` + navigate to `login`

---

## 10. Tab shell summary (`main` → BottomTabNavigator)

| Tab | Label | Stack | First screen | Behavior |
|---|---|---|---|---|
| `Bhookle` | **Home** | LandingStack | `LandingScreen` | Hosts Become A Chef CTA + search bar. Resets stack on tab press. |
| `GetNow` | **Get Today** | GetNowStack | `GetNowScreen` | Same-day. |
| `Home` | **Get Later** | HomeStack | `HomeScreen` | Slot-pick. |
| `Subscription` | **Subscribe** | SubscriptionStack | `SubscriptionScreen` | Today → silent redirect to `subscriptionRequestScreen` (form). |
| `Cart` | **Cart** | (action) | n/a | Logged-in + items → `CartScreen`; else → `login`. |
| `Profile` | **Profile** | ProfileStack | `ProfileScreen` | Login-skipped → `login`. |

Search tab commented out (`AppNavigator.tsx:535-556`).

---

## 11. Modals & overlays

- `RootLoadingComponent` — full-screen blocker, gated on `state.loader.isRootLoader`.
- `CartBarComponent` — persistent cart strip in tab header.
- `CommonHeader` — custom header above every tab; address selector.
- `callDynamicModal` (hook) — programmatic SUCCESS/ERROR modals (subscription, chef-register, etc.).

No stack-level `presentation: 'modal'`.

---

## 12. Verified API endpoint catalogue (FE → BE)

All via `FirebaseFunctionsEndpoint` (`EnvConstants.tsx`).

| Group | Endpoints |
|---|---|
| Auth/user | `/registered_users/app_config`, `/send_otp`, `/check_user`, `/register_user`, `/update_user_login` |
| Discovery | `/home_v3/get_landing_page_data`, `/get_home_chef_dish_list`, `/get_home_chef_dish_list_more_data`, `/get_now_home_data`, `/chefs_v3_1/get_kitchen_details` |
| Address | `/user_address/get_address_list_by_uid`, `/delete_address_list_by_uid` |
| Cart/order | `/orders/validate_coupon`, `/chefs_v3_1/cart_screen_request`, `/orders/generate_order_id_and_save_order`, `/check_payment_status`, `/get_orders_list_by_uid` |
| Subscription (dormant payment) | `/subscription/fetch_dishes_by_city`, `/generate_subscription_order`, `/check_subscription_payment_status`, `/fetch_subscription_details`, `/update_subscription_status`, `/update_order_delivery_date` |
| Leads/contact | `/contact_us/save_chef_register_request_contact`, `/contact_us/subscription_contact`, `/contact_us/update_subscription_contact_draft`, `/contact_us/save_festival_request`, `/general_contact_us/save_customer_request` |

---

## 13. Notes for `test-case-generator`

- **No `testID`s in any screen.** Maestro must drive by visible text. Recommend adding testIDs as a follow-up.
- **Boot routing is Redux-Persist-dependent.** New-user tests must clear persisted `regUserData`.
- **WelcomeScreen hardware back is suppressed.** Don't rely on it.
- **Subscription self-serve PhonePe path is BE-flag-controlled.** Test catalog should default to form-submit path (today's behavior) and treat the PhonePe path as a separate, flag-on scenario.
- **Search lane should be tested separately**, not as part of New/Existing User journey — it's supplementary.
- **Festival booking is a lead form**, not a transaction.
- **ChefRegisterRequest** has a silent-network-failure bug — should be a negative TC.
- **Post-order verification beyond orderAck** is out of scope for Maestro — separate DB/mailbox/FCM hooks needed.

---

## Appendix: Verified runtime anchors — logged-in screens (iOS sim, SIT, 2026-06-08)

Confirmed live; all use substring regex (iOS `"In progress "` prefix). Selected address persists in Redux, so warm relaunch returns to Landing.

| From → To | Tap | Destination anchor |
|---|---|---|
| Landing (hub) | — | `.*Get It Today.*`, `.*Get It Later.*`, `.*Subscribe.*`, `.*Become A Chef.*`; tabs `.*<Name>, tab, N of 6.*` |
| Landing → GetNowScreen | `.*Get It Today.*` (card) | `.*Search for GetToday.*` (search placeholder); results in bottom sheet |
| Landing → HomeScreen (get-later) | `.*Get It Later.*` (card) | `.*Nearby Chefs.*` + 7-day date row + category chips |
| Landing → SubscriptionScreen | `.*Subscribe Now.*` (card btn) | `.*KITCHEN TYPE.*` / `.*CUISINE.*` (quotation form: City, Members, Veg/Non-Veg/Both) |

**⚠️ Force-update modal:** on Landing the stale local build (2.0.17 < SIT required) shows **"Please Update Your APP"** with **SKIP / UPDATE**. Logged-in flows dismiss it with `tapOn: { text: ".*SKIP.*", optional: true }` (no-op when build is current). Worth a version-gate TC.

**Pending point-tap refinement (icon/toggle, not text-addressable):** VEG MODE toggle (`.*VEG MODE.*` matches the search group, not the switch) and the chef-hat icon (glyph `󰭼`, top-right → Chef Registration). TC-LAND-007 / TC-LAND-008 need point-tap coords dialed in.

TCs verified warm this session: **TC-LAND-001..004** (+ `auth-login.yaml` subflow, TC-WEL-003 location gate).

### Order path — partial map (explored 2026-06-08, add→cart not yet verified)

| From → To | Tap | Anchor / note |
|---|---|---|
| GetNow/HomeScreen → chef | `.*<Chef Name>.*` (e.g. `.*Sample Chef.*`) | chef cards "Name … 4.7 ~6.3 km" |
| chef → ChefFoodListScreen | (above) | header `.*HOME.*<name>`, `.*8 Dishes.*`, `.*FSSAI.*`; dish cards "…₹ 140 ADD" |
| add a dish | `.*ADD.*` (glyph `󰐕`; multiple — taps first) | per-dish add button |
| GetNow extras | — | meal-slot pill `.*DINNER.*`/`.*LUNCH.*`, `.*Show only Veg.*`, category chips `.*All.*`/`.*South Indian.*` |

**⚠️ Gotcha:** ChefFoodListScreen is a **pushed stack screen with NO bottom tab bar** → cannot reach Cart via `.*Cart, tab.*` from here; must use the on-screen cart control / go back to a tab screen first. **TODO next:** verify `ADD` registers (cart count/bar), find the cart entry from ChefFoodList, map CartScreen (`PROCEED TO PAY`, `VIEW ALL COUPONS`, `See summary` per prior notes). Payment = PhonePe SDK → external, not Maestro-automatable.
