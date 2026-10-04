#!/usr/bin/env python3
"""Price every row of a menu.json, verify it, and write the computed fields back.

    python price_menu.py menu.json [--quiet]

Fills in chef_rate, customer_price and the commission split for each item, then runs the
checks that matter. Exits non-zero if any row would underpay the chef, because that file
must not ship.
"""
import argparse, json, math, sys


def derive(item, rates):
    """Work out chef_rate and customer_price from whichever field the source gave us."""
    share = rates.get("chef_share_of_bhookle_rate", 0.8)
    total = rates["zomato"] + rates["bhookle"]
    rounding = rates.get("rounding", 1)

    chef = item.get("chef_rate")
    bhookle = item.get("bhookle_rate")
    customer = item.get("customer_price")
    direction = "from chef rate"

    if chef is None and bhookle is not None:
        chef = bhookle * share
    if chef is None and customer is not None:
        # Working backwards from a market-set price. The chef rate is what survives.
        chef = customer * (1 - total)
        direction = "from market price"
    if chef is None:
        raise ValueError(f"{item['name']}: no bhookle_rate, chef_rate or customer_price to work from")

    if customer is None:
        customer = math.ceil(chef / (1 - total) / rounding) * rounding
    if bhookle is None and direction == "from chef rate":
        bhookle = chef / share

    item["chef_rate"] = round(chef, 2)
    item["bhookle_rate"] = round(bhookle, 2) if bhookle is not None else None
    item["customer_price"] = int(customer)
    item["zomato_cut"] = round(customer * rates["zomato"], 2)
    item["bhookle_cut"] = round(customer * rates["bhookle"], 2)
    item["net_to_chef"] = round(customer - item["zomato_cut"] - item["bhookle_cut"], 2)
    item["margin_vs_chef_rate"] = round(item["net_to_chef"] - chef, 2)
    item["_direction"] = direction
    return item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("menu")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    menu = json.load(open(a.menu, encoding="utf-8"))
    rates = menu["rates"]
    total = rates["zomato"] + rates["bhookle"]
    items = menu["items"]

    for it in items:
        derive(it, rates)
    for it in menu.get("held_back", []):
        try:
            derive(it, rates)
        except ValueError:
            pass  # a held-back row may legitimately have no price yet

    # --- the check that decides whether this file may ship ---
    underpaid = [i for i in items if i["margin_vs_chef_rate"] < -0.005]

    if not a.quiet:
        print(f"Zomato {rates['zomato']:.0%}  Bhookle {rates['bhookle']:.0%}  "
              f"total {total:.0%}  gross-up {1/(1-total):.4f}\n")
        hdr = f"{'Item':32}{'Chef':>9}{'Cust':>7}{'Zomato':>9}{'Bhookle':>9}{'Net':>9}{'Chk':>6}"
        print(hdr); print("-" * len(hdr))
        for i in items:
            ok = "ok" if i["margin_vs_chef_rate"] >= -0.005 else "FAIL"
            print(f"{i['name'][:32]:32}{i['chef_rate']:>9.2f}{i['customer_price']:>7}"
                  f"{i['zomato_cut']:>9.2f}{i['bhookle_cut']:>9.2f}{i['net_to_chef']:>9.2f}{ok:>6}")
        print("-" * len(hdr))

        cp = [i["customer_price"] for i in items]
        print(f"\n{len(items)} items priced"
              + (f", {len(menu['held_back'])} held back" if menu.get("held_back") else "")
              + f" | range ₹{min(cp)}-{max(cp)} | average ₹{sum(cp)/len(cp):.0f}")

        # per-unit pay, for the quantity fairness conversation
        withunits = [i for i in items if i.get("units")]
        if withunits:
            print("\nChef pay per unit:")
            for i in sorted(withunits, key=lambda x: x["chef_rate"] / x["units"][0]):
                n, lbl = i["units"]
                print(f"   ₹{i['chef_rate']/n:>7.2f} per {lbl:9} {i['name']}")
            print("   Lowest rates are worth a second look — is that portion what she serves today?")

        # take-home comparison where a live price is known
        live = [i for i in items if i.get("her_live_price")]
        if live:
            c = rates.get("assumed_current_commission", 0.30)
            print(f"\nVersus her take-home today (assuming {c:.0%} commission on her own listing):")
            for i in live:
                today = i["her_live_price"] * (1 - c)
                d = i["chef_rate"] - today
                print(f"   {i['name'][:30]:30} listed ₹{i['her_live_price']:>4} -> nets ₹{today:>7.2f}"
                      f"   new ₹{i['chef_rate']:>7.2f}   {d:+7.2f}  ({d/today*100:+.0f}%)")
            if any(i["chef_rate"] - i["her_live_price"] * (1 - c) < 0 for i in live):
                print("   Some items pay her LESS than today. Raise those customer prices or say so plainly.")

        back = [i["name"] for i in items if i["_direction"] == "from market price"]
        if back:
            print(f"\n{len(back)} item(s) priced backwards from a market price — label these chef "
                  f"rates as derived, not agreed: {', '.join(back[:6])}"
                  + (" ..." if len(back) > 6 else ""))

    for i in items:
        i.pop("_direction", None)
    for i in menu.get("held_back", []):
        i.pop("_direction", None)

    if underpaid:
        print("\nSTOP — these rows pay the chef less than her rate. Do not ship this file:",
              file=sys.stderr)
        for i in underpaid:
            print(f"   {i['name']}: net ₹{i['net_to_chef']:.2f} vs rate ₹{i['chef_rate']:.2f}",
                  file=sys.stderr)
        sys.exit(1)

    json.dump(menu, open(a.menu, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    if not a.quiet:
        print(f"\nAll rows clear. Written back to {a.menu}")


if __name__ == "__main__":
    main()
