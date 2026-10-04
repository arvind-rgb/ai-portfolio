# Data-Gathering Playbook — Zomato / Swiggy / Google

Both aggregators hard-block scripted HTTP (datacenter IPs, non-browser TLS). The Browser
pane is a real browser, so everything below runs through `mcp__Claude_Browser__*` tools.
The high-leverage trick: once a page from an origin is open, `javascript_tool` can call
that origin's **internal JSON APIs** with a same-origin `fetch()` — structured data, no
screen-scraping.

Save every useful raw response to `leads/kitchen-intel/<slug>/raw/` immediately
(write the JSON out via the Write tool after reading it in the browser).

---

## 0. Locate the kitchen (before opening the browser)

WebSearch — these work because Google's index is accessible even when the sites aren't:

- `site:zomato.com "<kitchen name>" <city>`
- `site:swiggy.com "<kitchen name>" <city>`
- `"<kitchen name>" <area> <city> google maps`
- `"<kitchen name>" <city> instagram`

Search snippets often already reveal rating + cost-for-two — note them as cross-checks.
If nothing on either aggregator: that's a finding (platform-invisible kitchen), pivot the
report toward "you're missing X orders/day of demand" framing.

## 1. Zomato — target kitchen

1. `preview_start {url: "<zomato restaurant URL>"}` (or `navigate` if pane already open).
2. `get_page_text` → rating, review count, cuisine tags, cost-for-two, address, timings.
3. Structured data (preferred over page text) via `javascript_tool`:
   ```js
   // From the restaurant page — the SPA preloads everything:
   JSON.stringify(window.__PRELOADED_STATE__ || {}).slice(0, 200)  // probe shape first
   ```
   If `__PRELOADED_STATE__` exists, extract from it: `pages.restaurant[resId]` holds
   res_id, rating breakdown, top dishes, highlights. Pull targeted slices, not the whole
   blob (it's MBs — slice or pick keys, never return it raw into context).
4. Menu + prices: navigate to the `/order` sub-path of the restaurant URL, then either
   read `__PRELOADED_STATE__` menu items or `get_page_text` (items + ₹ prices render as text).
5. Reviews: navigate to `/reviews` sub-path. `get_page_text` gives the visible page;
   for more, same-origin fetch:
   ```js
   fetch('/webroutes/reviews/loadMore?res_id=<RES_ID>&page=2&sort=dd&filter=reviews-dd',
     {headers:{'accept':'application/json'}}).then(r=>r.json())
   ```
   Collect 20–40 reviews across recent pages; capture text, rating, date, dish mentions.
6. Note what's on the page BESIDE data: photo quality, whether menu has photos, offers
   banner, "Pro" participation, response-to-reviews behavior — feeds Branding Critique.

## 2. Swiggy — target kitchen + lat/lng

1. Open the Swiggy restaurant page. The URL ends in `-rest<ID>` — that's the restaurantId.
2. Full menu JSON (item-level prices, per-item ratings, bestseller flags, veg flags):
   ```js
   fetch('/dapi/menu/pl?page-type=REGULAR_MENU&complete-menu=true&lat=<LAT>&lng=<LNG>&restaurantId=<ID>')
     .then(r=>r.json())
   ```
   Restaurant info block inside it: rating, totalRatingsString, costForTwo, cuisines,
   feeDetails, availability, offers (`aggregatedDiscountInfo`).
3. lat/lng: from Google Maps (step 3) or the Swiggy page's own state
   (`window.___INITIAL_STATE___`) — probe its shape the same way as Zomato's.
4. Swiggy shows rating count but not review text — review text comes from Zomato + Google.

## 3. Google Maps — reviews + coordinates

1. Navigate to `https://www.google.com/maps/search/<kitchen>+<area>+<city>`.
2. `get_page_text` → rating, review count, category, address. The URL after it resolves
   contains `@<lat>,<lng>` — grab coordinates from there.
3. Click the reviews section (`read_page` → `find "reviews"` → `computer` click) and
   `get_page_text` for review text; scroll for more. Google reviews skew more candid than
   Zomato's — best source for hygiene/packaging complaints.

## 4. Competitor sweep (5–8 kitchens)

Goal: same cuisine, same delivery radius, mix of (a) other home/cloud kitchens and
(b) the 1–2 dominant restaurant brands the kitchen loses orders to.

- **Swiggy listing API** (from swiggy.com origin, using target's lat/lng):
  ```js
  fetch('/dapi/restaurants/list/v5?lat=<LAT>&lng=<LNG>&page_type=DESKTOP_WEB_LISTING')
    .then(r=>r.json())
  ```
  → nearby restaurants with name, cuisines, avgRating, totalRatings, costForTwo, sla
  (delivery time), aggregatedDiscountInfo. Filter to the target's cuisine.
- **Swiggy search API** for cuisine keyword:
  ```js
  fetch('/dapi/restaurants/search/v3?lat=<LAT>&lng=<LNG>&str=<cuisine>&submitAction=ENTER')
    .then(r=>r.json())
  ```
- **Zomato**: open `zomato.com/<city>/delivery-in-<area>` or search page for the cuisine;
  `get_page_text` for the listing grid (name, rating, cost).
- For the 3 closest competitors, pull their Swiggy menu JSON too (step 2 technique) —
  that's the item-level price intelligence table.

## 5. Instagram / social presence (branding signal)

WebSearch for the handle; if found, one browser visit to the profile is enough:
follower count, post cadence, content quality, whether they push their own ordering
channel. No handle found = finding: zero owned audience, fully platform-dependent.

## Fallbacks when something blocks

- Approval card not granted / origin refuses: fall back to WebSearch snippets +
  Google cache + magicpin/EazyDiner mirrors (`site:magicpin.in "<kitchen>"`) — mark such
  numbers as "indicative" in the report.
- `__PRELOADED_STATE__` / dapi shape changed: degrade gracefully to `get_page_text` on
  rendered pages. Slower but always works.
- CAPTCHA appears: STOP on that origin, tell the user, continue with other sources.
  Never attempt to solve it.

## Budget

A full run is roughly: 2 search rounds + ~6 Zomato/Google pages + ~4 Swiggy API calls +
3 competitor menus. If an origin is being slow, prioritize: target Swiggy menu JSON →
target Zomato reviews → competitor list API → everything else.
