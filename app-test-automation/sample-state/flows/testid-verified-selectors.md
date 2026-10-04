# testID-verified selectors & divergences — 2026-06-09 (iOS sim, testID standalone build)

Source of truth for the **runtime selector layer** on the testID build. Verified by
live runs on iPhone 15 Pro Max (iOS 17.2), bundle `com.app.Bhookle`, SIT backend.
testIDs surface in the Maestro hierarchy as **`resource-id`** and `id:` is a
**full-match regex** (exact ids are exact; templated ids match via `.*`).

## ✅ Proven end-to-end (the smoke spine)
Auth → Landing → Chef menu → add dish → cart bar → Cart screen → proceed-to-pay.
All on `id:` selectors. The pre-testID point-tap/substring era is retired.

| Screen | Verified ids (live) |
|---|---|
| GetStarted | `getstarted-screen`, `getstarted-cta` |
| Login (phone) | `login-screen`, `login-phone-input`, `login-get-otp-btn`, `login-back-btn`, `login-skip-btn` |
| Login (OTP) | `otp-input` (accepts `inputText`, auto-submits onFilled) |
| Welcome | `welcome-proceed-btn` |
| AddressCollection | `addresscollection-screen`, `address-choose-btn`, `address-add-another-btn`, `address-add-new-btn` |
| Landing | `landing-screen`, `landing-get-today-card`, `landing-get-later-card`, `landing-subscribe-btn`, `landing-app-update-skip-btn` (force-update modal) |
| GetNow | `get-now-screen`, `chef-card-<chef_id>` (regex `chef-card-.*` + index) |
| ChefFoodList | `cheffoodlist-screen`, `chef-back-btn`, `chef-header-name`, `chef-fssai-toggle`, `chef-share-btn`, `chef-bio-expand`, `dish-expand-<dishId>` |
| Dish ADD / stepper | `dish-add-btn` (STATIC, shared per card → index), → after add: `dish-qty-minus-btn`, `dish-qty-value`, `dish-qty-plus-btn` |
| Global cart bar | **`bottom-cart-btn`** (+ `bottom-cart-count`) — BottomCartComponent |
| Cart screen | `cart-screen`, `cart-proceed-to-pay-btn` (stop here — PhonePe is external) |

## 🔑 Key runtime truths (cost us time — captured so we never re-derive)
1. **Drive ADD by `id:`, never by coordinate.** A point-tap on the ADD pill is
   swallowed by the dish-card touchable; a Maestro `id: dish-add-btn` tap dispatches
   to the element and adds the dish. **testIDs solved the card-swallow** — for the
   addressable cards (see divergence #1).
2. **Cart bar = `bottom-cart-btn`, not `cart-bar`.** Two components exist; the chef
   menu/global bar is BottomCartComponent. It's global and persists until cart clear.
3. **`dish-add-btn` is static**, not `dish-add-<id>` (this screen uses CartButton_2).
   Multiple dishes share the id → select by `index`.
4. **iOS still prefixes labels with "In progress "** — irrelevant now (we use `id:`),
   but it's why old full-match text selectors missed.
5. **First-launch dialogs**: Notifications ("Allow") then ATT ("Ask App Not to Track")
   — handled by `subflows/dismiss-permissions.yaml`.

## 🚩 DIVERGENCES — FLAG TO APP DEV (un-instrumented controls; we point-tap as workaround)
1. **"Get It Today" (instant) dish cards group ADD out of the a11y tree.** At the top
   of ChefFoodList the instant-section cards expose `dish-expand-<id>` but NO
   `dish-add-btn` node (ADD text is grouped into the card's accessibilityText). The
   lower "Get It Later" CartButton_2 cards DO expose `dish-add-btn`. → The instant
   card wrapper likely has `accessible={true}`; add `accessible={false}` so the ADD
   testID surfaces (TESTID-PLAN §0). Workaround: `scrollUntilVisible dish-add-btn`.
2. **AddressCollection "Choose Address" sheet rows are not addressable.** Tapping
   `address-choose-btn` opens a bottom sheet of saved addresses, but the rows have
   NO testID and NO text node in the iOS tree (only the sheet container surfaces).
   the app dev's `saved-address-row-<index>` ids are on AddressListBottomSheet /
   AddressListScreen — a DIFFERENT component than this sheet. → Add
   `saved-address-row-<index>` (and `accessible={false}` on row wrappers) to the
   component AddressCollectionScreen opens. Workaround: point-tap row 0 at `50%,56%`.

## Cross-platform grading findings (run #21, 14-TC validation batch, both platforms)
- **iOS CI is the reliable grading platform** (10/14 PASS, clean assertion failures).
  Android emulator (single shard, 14 sequential `clearState` relaunches) threw
  "Unknown error" (driver-level, no screenshot) on the heavier flows GETNOW/CHEF/CART
  — **which PASS on iOS** → flows are sound; Android needs SMALLER shards (fewer
  clearState cycles per shard) for stability.
- **Verified nav corrections (folded into generate-flows.js):**
  - `landing-subscribe-btn` → **Subscription REQUEST** (`subrequest-screen`), NOT
    SubscriptionScreen. SubscriptionScreen proper = the **`tab-subscribe`** tab.
  - `landing-become-chef-card` is **below the fold** → `scrollUntilVisible` first.
  - **Landing IS the Home tab** (`landing-screen`). `home-screen` (HomeScreen) is the
    "Get It Later" browse → reach via **`tab-get-later`**.
  - The **bottom tab bar renders** with `tab-home/get-today/get-later/subscribe/cart/profile`;
    `tab-profile` confirmed working.
  - TODO: `landing-search-bar` does NOT land on `search-screen` (anchor wrong — likely
    `get-now-search-screen` or inline search). Needs one more check.

## Page-object map (composed by TCs)
`subflows/dismiss-permissions.yaml` · `auth-login.yaml` (→ authed Landing) ·
`landing.yaml` · `open-first-chef.yaml` · `add-first-dish.yaml` · `open-cart.yaml`.
Single-session smoke composite: `smoke-ios.yaml`.
