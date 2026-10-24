---
name: waste-log-append-only
description: "RULE: the waste_log table is append-only — a wrong row gets a correcting row, never an UPDATE or DELETE"
metadata:
  type: feedback
  project: crumbledger
---
The `waste_log` table in `src/schema.sql` is append-only. A mistaken entry is corrected by a second row with a negative
quantity and a reason that names the first; nothing is ever updated or deleted. The owner uses the log at tax time and
wants to see what was recorded on the day, not what someone later decided it should have been.
