---
name: supplier-csv-columns
description: "the supplier's Monday price list has exactly five columns — sku, name, unit, price_per_unit, pack_size — `COLUMNS` in src/supplier_csv.py refuses anything else"
metadata:
  type: reference
  project: crumbledger
---
The supplier emails a CSV every Monday. `src/supplier_csv.py` reads it with `csv.DictReader` and checks the header against
`COLUMNS`: sku, name, unit, price_per_unit, pack_size. A missing column raises instead of guessing — the one time a
column was renamed (price → price_per_unit, 2026-09-02) the order went out with last month's prices.
