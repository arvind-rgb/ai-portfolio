#!/usr/bin/env python3
"""Write the Zomato upload CSV from a priced menu.json.

    python build_upload_csv.py menu.json [-o Chef_Zomato_Upload.csv]

Held-back items are left out on purpose — an item missing a mandatory field must not go live.
"""
import argparse, csv, json, sys

H1 = ["Mandatory information", "", "", "", "", "",
      "Optional information", "", "", "", "", ""]
H2 = ["Item name", "Category", "Item price", "Dietary Tag (veg/non veg/egg)",
      "Item Type (Goods / Services)", "Serving Size", "Subcategory", "Item description",
      "Variant", "Variant Price", "Add Ons", "Add on Prices"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("menu")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    menu = json.load(open(a.menu, encoding="utf-8"))
    chef = menu.get("chef", {})
    out = a.out or f"{chef.get('name','Chef').split()[0]}_Zomato_Upload.csv"

    problems = []
    for i in menu["items"]:
        for field in ("name", "category", "subcategory", "serving_size", "description", "dietary"):
            if not str(i.get(field) or "").strip():
                problems.append(f"{i.get('name','(unnamed)')}: missing {field}")
        if not i.get("customer_price"):
            problems.append(f"{i.get('name')}: not priced — run price_menu.py first")
        if i.get("category") and i.get("category") == i.get("subcategory"):
            problems.append(f"{i.get('name')}: subcategory must be more specific than category")
    if problems:
        print("Cannot write the upload file:", file=sys.stderr)
        for p in problems:
            print("   " + p, file=sys.stderr)
        print("\nFix these, or move the item to held_back with the question that unblocks it.",
              file=sys.stderr)
        sys.exit(1)

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(H1)
        w.writerow(H2)
        for i in menu["items"]:
            w.writerow([
                i["name"], i["category"], i["customer_price"], i["dietary"],
                i.get("item_type", "Services"), i["serving_size"], i["subcategory"],
                i["description"],
                i.get("variant", "-"), i.get("variant_price", "-"),
                i.get("add_ons", "-"), i.get("add_on_prices", "-"),
            ])

    held = menu.get("held_back", [])
    print(f"Wrote {out} — {len(menu['items'])} items"
          + (f", {len(held)} held back" if held else ""))
    for h in held:
        print(f"   held: {h['name']} — {h.get('missing','(reason not recorded)')}")
        if h.get("ask"):
            print(f"          ask her: {h['ask']}")


if __name__ == "__main__":
    main()
