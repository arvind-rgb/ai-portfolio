# Neighbourhood price check

Prices can be internally correct and still unsellable. A new listing with no ratings priced at the
level of an established 4.2-star kitchen does not get first orders.

## Finding the locality

If nobody knows offhand, her **FSSAI certificate** carries the kitchen address under "address of
location where food business is to be conducted". Use the business address, not the personal one,
and take only the locality — there is no reason to pull anything else off that document.

## Sources that work

**Zomato and Swiggy block automated fetching.** Zomato returns a robots.txt refusal and Swiggy is
JS-rendered, so their live menus cannot be read directly. Do not try to route around it with curl
or a scraping library.

What does work:

- **magicpin** — carries menus with prices, ratings and cost-for-two for most Bengaluru
  restaurants, and is fetchable
- **JustDial, restaurant-guru, Tripadvisor** — patchy but sometimes carry the menu
- **Aggregator blog roundups** — good for tiffin subscription rates
- **Search results themselves** — restaurant names in an area, useful for mapping the competitive
  set even when the menu is unreachable

Ask the operator to print the *Order Online* tab for two or three local kitchens if you need
precision. That is a two-minute job for them and it beats any amount of inference.

## Reading the result

Collect, per competitor: name, distance or locality, rating and rating count, three or four real
item prices, and cost for two. Rating count matters — a 4.5 with 151 ratings is a new entrant, a
4.3 with 45,000 is an institution and a much harder comparison.

**Do not benchmark against tiffin subscriptions.** They run ₹83–107 a meal in Bengaluru, roughly
40% of an à-la-carte price, because they are pre-paid monthly and carry no aggregator commission.
They are not what a Zomato customer is choosing between. Note them for context, then compare
against à-la-carte restaurants.

Band every item: **attractive** (below the local comparable), **at par**, **exposed** (above what
the area pays for a single serving). Report the counts, then name the exposed items individually.

## Reporting

Give the rate change that fixes each exposed item — "a ₹195 Bhookle rate brings this to ₹284" —
rather than repricing silently. At a 45% take every ₹1 off the customer price is 55 paise off the
chef, so it is her call.

Two patterns worth naming when they show up:

- **A direct local equivalent that is cheaper and better rated.** One chef had three poori with
  sabji at ₹262 against a nearby 4.1-star kitchen selling six poori with chole at ₹129. That is a
  portion problem, not a price problem, and it is the chef's decision.
- **A ceiling.** If the menu's top item now sits under the priciest comparable single dish in the
  area, say so — "nothing on your listing is the most expensive single dish in the neighbourhood"
  is a sentence the chef can act on.
