---
name: thresholds-live-in-yaml
description: "the hand-set minimums per item are a YAML file, configs/thresholds.yml, grams on hand; read by `thresholds` in src/reorder.py, never hard-coded"
metadata:
  type: reference
  project: crumbledger
---
`configs/thresholds.yml` holds grams-on-hand minimums per item (bread flour, pastry flour, butter, fresh yeast). The
`thresholds` function in `src/reorder.py` reads it on every run; nothing else reads it. A new item needs no code — add a
line. See [[flour-reorder-point]] for how the file interacts with the computed point.
