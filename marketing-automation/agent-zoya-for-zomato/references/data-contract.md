# menu.json

The three scripts share this file. `price_menu.py` fills in the computed fields; the builders read
them. Write it once from the chef's source file and everything downstream composes.

```json
{
  "chef": {
    "name": "Meera Sample",
    "brand": "Meera Sample",
    "city": "Bengaluru",
    "locality": "HSR Layout",
    "kitchen_hours": "9 AM to 9 PM",
    "listing_id": null
  },
  "rates": {
    "zomato": 0.27,
    "bhookle": 0.18,
    "chef_share_of_bhookle_rate": 0.8,
    "rounding": 1,
    "assumed_current_commission": 0.30
  },
  "items": [
    {
      "s_no": 1,
      "name": "Methi Thepla",
      "category": "Breakfast",
      "subcategory": "Theplas & Chillas",
      "serving_size": "4 pieces - Serves 1",
      "description": "Four methi thepla served with masala dahi and achaar",
      "dietary": "Veg",
      "bhookle_rate": 125,
      "chef_rate": null,
      "customer_price": null,
      "her_live_price": null,
      "units": [4, "piece"]
    }
  ],
  "held_back": [
    {
      "s_no": 15,
      "name": "Rava Handvo",
      "bhookle_rate": 150,
      "missing": "Serving size — the dish story gives no piece count or volume.",
      "ask": "How many pieces, or what box size, is one order?"
    }
  ]
}
```

## Field notes

**`bhookle_rate` vs `chef_rate`** — supply whichever the source file actually gives you, and leave
the other null. `price_menu.py` derives the missing one using `chef_share_of_bhookle_rate`. If the
source gives chef rates directly, set `bhookle_rate` to null rather than back-computing it by hand.

**`customer_price`** — leave null and let the script compute it. Set it explicitly only when you
are working backwards from the market (the contaminated-rate case), in which case the script
derives `chef_rate` from it instead and flags the direction it worked in.

**`her_live_price`** — what she charges on her own existing listing for the comparable item, where
known. Drives the take-home comparison and the break-even check. Null is fine and common.

**`units`** — `[count, label]` for the quantity fairness check, e.g. `[4, "piece"]`,
`[5, "100 ml"]`, `[2.5, "100 g"]`. Omit where the portion is genuinely unknown; the script will
report it as uncheckable rather than assuming.

**`held_back`** — items that are priced but cannot go live because a mandatory Zomato field is
unresolvable. They stay out of the CSV and appear in the workbook and the handover. Each needs the
one question that unblocks it.
