-- crumbledger store: one SQLite file. Quantities are grams, always.
CREATE TABLE IF NOT EXISTS items   (sku TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'g');
CREATE TABLE IF NOT EXISTS counts  (day DATE NOT NULL, sku TEXT NOT NULL REFERENCES items(sku), grams INTEGER NOT NULL, PRIMARY KEY (day, sku));
CREATE TABLE IF NOT EXISTS waste_log (ts TIMESTAMP NOT NULL, sku TEXT NOT NULL, grams INTEGER NOT NULL, reason TEXT);
