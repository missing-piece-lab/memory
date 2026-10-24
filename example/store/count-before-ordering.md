---
name: count-before-ordering
description: "RULE: never place an order from the computed list alone — the physical count comes first, and a count older than a day is no count"
metadata:
  type: feedback
  project: crumbledger
---
The reorder list ([[flour-reorder-point]]) is only as good as last night's count ([[nightly-count-script]]). Before any
order goes to the supplier, the count for yesterday must exist; if the nightly job failed, count by hand first. Learned
2026-08-20: a list computed from a two-day-old count ordered forty kilograms of flour the shop already had.
