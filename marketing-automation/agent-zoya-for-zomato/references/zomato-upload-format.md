# Zomato upload file

## Exact format

Two header rows. Row 1 spans the mandatory block across A–F and the optional block across G–L.
Row 2 carries the column names, in this order:

```
Mandatory information,,,,,,Optional information,,,,,
Item name,Category,Item price,Dietary Tag (veg/non veg/egg),Item Type (Goods / Services),Serving Size,Subcategory,Item description,Variant,Variant Price,Add Ons,Add on Prices
```

Twelve columns on every row. `build_upload_csv.py` writes this; use it rather than hand-rolling
the CSV, since quoting matters — descriptions frequently contain commas.

## Field rules

**Item Type** — `Services` for a delivery kitchen. `Goods` is for packaged retail products, and
those raise a separate question about whether they belong on a food listing at all.

**Dietary Tag** — derive it from the stated ingredients, never from the dish name. Ask if unclear.
An item tagged veg that contains egg is a live complaint, not a spreadsheet error.

**Serving Size** — derive from the portion detail in the dish description and keep the format
consistent across the whole menu. `4 pieces - Serves 1`, `500 ml box - Serves 1`,
`2 phulkas + dal + sabji - Serves 1`. This field sits in the mandatory block, so an item whose
description carries no quantity cannot go live — hold it back and ask.

**Subcategory** — more specific than Category. Category is the menu section a customer scrolls
past; subcategory is what the dish actually is. `Main Course` / `Paratha Combos`, not
`Main Course` / `Main Course`.

**Item description** — sentence case, typos fixed, no prices, no phone numbers, no promotional
language. Keep the chef's own portion detail; she wrote it and it is accurate. Rewrite
"4 pcs with masala dahi and achaar" as "Four methi thepla served with masala dahi and achaar".

**Variant, Variant Price, Add Ons, Add on Prices** — `-` unless the menu genuinely has them.

## Also produce

A flat-value CSV is the upload file itself, so it is already formula-free. Alongside it, build the
pricing workbook (`Price Calculation` sheet) with the commission rates in labelled input cells and
every price as a live formula referencing them, so the whole menu re-prices when a rate changes.
Include the per-row net-to-chef verification column.

Where items were held back, give them their own sheet with the blocking question and a formula that
prices them the moment the missing field arrives.
