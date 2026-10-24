# crumbledger — memory index (one line per memory; what each is FOR, never what state it is in)

## rules
- [Stock is grams](stock-in-grams.md) — every stored quantity is grams; kilograms only on the screen
- [Waste log is append-only](waste-log-append-only.md) — a wrong row gets a correcting row, never an update
- [Count before ordering](count-before-ordering.md) — the physical count comes first; a stale count is no count

## the owner
- [The owner reads plain tables](owner-reads-plain-tables.md) — paper, monospace, sorted by what runs out first

## the tool
- [Flour reorder point](flour-reorder-point.md) — seven days of usage, lead time, a 20% cushion
- [Thresholds live in YAML](thresholds-live-in-yaml.md) — hand-set minimums per item, read on every run
- [Nightly count script](nightly-count-script.md) — counts in, reorder list out, one cron line
- [Supplier CSV columns](supplier-csv-columns.md) — the five columns the Monday price list must have
- [Holiday multiplier](holiday-multiplier.md) — one constant, applied on marked days
- [Spreadsheet export](spreadsheet-export-retired.md) — the monthly workbook for the accountant (wrong on purpose)
