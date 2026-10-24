---
name: holiday-multiplier
description: "the holiday demand multiplier is 1.6 — `HOLIDAY_MULTIPLIER` in src/forecast.py, applied only on days the owner marks"
metadata:
  type: project
  project: crumbledger
---
`demand` in `src/forecast.py` averages the last four same-weekdays and multiplies by `HOLIDAY_MULTIPLIER` (1.6) on a day
the owner has marked as a holiday. The number came from three holidays in 2026 where the bakery sold out by ten; it is
a single constant on purpose, to be revisited with a fourth data point, not a per-item table.
