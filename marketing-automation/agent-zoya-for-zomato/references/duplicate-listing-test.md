# Duplicate listing test

Only relevant when a chef who already sells on Zomato wants a second brand from the same kitchen.
Zomato rejects a second listing that reads as a clone of the first.

## What actually has to be true

The two menus need a **real separation axis**. Two work:

**Daypart.** The existing listing sells breakfast tiffins and evening snacks; the new brand sells
lunch rice-meals only. Zero item overlap, different times of day. This clears cleanly.

**Format.** The existing listing sells single components — one rice bath, one rotti, one bowl of
gravy. The new brand sells only composed meal boxes: rice bath of the day plus kosambari plus curd
plus pickle plus a sweet bite, as one SKU. Different product, same kitchen.

What does not work: renaming dishes, splitting one menu in half, or "the new one is the premium
version".

## How to run it

1. Get the existing menu. The Zomato listing page print is usually the **Overview** tab, which has
   no items on it — the menu lives behind *Order Online*. If that print is all you have, say so
   and use whatever documented repertoire exists (a kitchen intelligence report, a Swiggy listing,
   an older upload file), labelling which overlaps are confirmed and which are inferred.
2. Mark every proposed item against it: **already sells** / **same dish family** / **looks clear** /
   **not a dish**.
3. Count. Confirmed overlap of more than a handful, or no available separation axis, means it
   fails.

## Reporting the verdict

Lead with pass or fail, then the evidence. A comparison against a chef who *did* clear the test
is the most useful framing an operator can get — it shows what the bar looks like rather than
just where this one fell short.

Flag two specifics that recur:

- **Packaged retail goods** (spice powders, protein powders) are not dishes. They need
  `Item Type: Goods`, they carry a hard ingredient cost that a 45% take may not survive, and they
  may not belong on a food listing at all.
- **Her highest-rated items should stay where they are.** A dish rated 4.6 on the existing listing
  is earning trust there. Moving or copying it costs more than it gains.

## When it fails

Say so, then design the passing version rather than stopping. Build it on the separation axis that
is actually available — usually format, since daypart is often already taken. Draw components only
from dishes the kitchen demonstrably cooks, give every SKU a name that appears nowhere on the
existing listing, and mark the whole thing as needing the chef's confirmation on portions before
it goes anywhere.

Leave box prices blank with a live formula, and give the required chef rate at each target price
band instead. Box pricing depends on portion sizes the chef sets; that is hers to decide, not
yours to assume.
