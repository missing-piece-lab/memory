---
name: flour-reorder-point
description: "how the reorder point for an item is computed: seven days of usage, the supplier's lead time, a 20% cushion — `point_for` in src/reorder.py"
metadata:
  type: project
  project: crumbledger
---
The reorder point is not a fixed number. `point_for` in `src/reorder.py` takes the last seven days of usage in grams, the
supplier's lead time in days, and multiplies by a 1.2 cushion (`CUSHION`). A hand-set threshold in [[thresholds-live-in-yaml]]
wins over the computed point when it is higher — the owner set those after a flour shortage.

Decided 2026-08-14 after two mornings with no bread flour: the old rule was "order when the second sack opens".
