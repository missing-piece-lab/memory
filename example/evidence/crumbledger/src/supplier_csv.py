"""The supplier's price list, as the CSV they email every Monday."""
import csv

COLUMNS = ["sku", "name", "unit", "price_per_unit", "pack_size"]


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    missing = [c for c in COLUMNS if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"price list is missing columns: {missing}")
    return rows
