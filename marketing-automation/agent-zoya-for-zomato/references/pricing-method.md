# Pricing method

## The gross-up

The customer price has to be set so that what survives both commissions equals the chef's rate.

```
total_deduction = zomato_pct + bhookle_pct        # default 0.27 + 0.18 = 0.45
gross_price     = chef_rate / (1 - total_deduction)
customer_price  = ROUNDUP(gross_price, rounding)  # default nearest ₹1
zomato_cut      = customer_price × zomato_pct
bhookle_cut     = customer_price × bhookle_pct
net_to_chef     = customer_price - zomato_cut - bhookle_cut
```

Verify `net_to_chef >= chef_rate` on every row. If any row fails, stop.

## Why not just add 45%

Because they are different bases and the difference is the chef's money.

A ₹120 chef rate, marked up 45%, gives ₹174. Take 45% of ₹174 and ₹95.70 is left — she is ₹24
short. Divide ₹120 by 0.55 and you get ₹219; take 45% of ₹219 and ₹120.45 is left. At a 45%
combined take the real multiplier is **1.818**, an 81.8% mark-up.

This is worth explaining to the chef in her own numbers rather than as a formula. It is the single
most useful paragraph in the chef-facing sheet.

## The three bases

| Basis | What it is | Tell |
|---|---|---|
| Bhookle rate | Internal rate the menu is built on | Round: 120, 150, 180, 225 |
| Chef rate | What she receives | = Bhookle rate × 0.8. Often unround: 96, 104, 144, 168 |
| Her platform price | What she already lists at | Sits within ~10% of her live Zomato/Swiggy price |

The relationship `chef_rate = bhookle_rate × 0.8` is usually written into the source spreadsheet
as a formula like `=E2-(E2*20%)`. When the formula is present, the basis is settled — read it.

Two mechanical checks:

- **Divide by 0.8.** Every value landing on a round number means chef rates derived from Bhookle
  rates. (104 → 130, 108 → 135, 136 → 170, 72 → 90.)
- **Compare against her live listing.** If the values sit at roughly 1.0–1.1× what she charges
  publicly today, they are platform prices with commission already inside them.

## Repairing a contaminated rate

When the supplied "chef rate" turns out to be her own platform price, the gross-up produces
customer prices at roughly 2× her live listing for the same dish from the same kitchen. Do not
ship that.

Invert the process instead. Set the customer price against the neighbourhood (step 6), then take
55% of it as the chef rate. Then prove it is not a pay cut:

```
her_net_today = her_live_price × (1 - her_current_zomato_commission)
gain           = new_chef_rate - her_net_today
```

Her commission rate is usually unknown — show 25% and 30% as a range and mark it as an assumption.
This comparison is what makes the change defensible: in one case the new prices beat her actual
take-home by 2–32% even though the headline "rate" looked lower, because her headline rate was
never take-home in the first place.

If any item comes out negative on that comparison, raise the customer price until it does not, so
long as the result stays inside the local band. Say which prices you raised and why.

## Presenting the gain

In the chef sheet, put the per-serving gain under the chef price as a ticker — `▲ ₹8.95/serving`.
It reads as a movement rather than a number, and it answers the question she is actually asking,
which is "am I better off than I am now".

State the basis for the comparison in a footnote. A gain measured against an assumed 30% commission
becomes a loss if hers is 20%, and the smallest gains are the ones that flip.
