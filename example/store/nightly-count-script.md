---
name: nightly-count-script
description: "the nightly job is scripts/nightly_count.sh — yesterday's closing counts into the store, then the morning reorder list; it is a cron line, not a service"
metadata:
  type: project
  project: crumbledger
---
`scripts/nightly_count.sh` runs the two steps in order: `crumb.count` for yesterday's date, then `crumb.reorder --print`
for the morning list. It is one cron line on the shop laptop. If the list is missing in the morning, the count step
failed; the reorder step never runs without it. See [[count-before-ordering]].
