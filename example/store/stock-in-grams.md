---
name: stock-in-grams
description: "RULE: every quantity in the store is grams; kilograms exist only on the screen — never store a converted number"
metadata:
  type: feedback
  project: crumbledger
---
Every quantity in the store is grams. The screen shows kilograms for anything over a thousand grams, and that conversion
happens at render time only. Learned 2026-07-30 when a count was entered as `25` meaning kilograms and the reorder list
went blank for a week: a mixed-unit column cannot be repaired after the fact because nobody knows which rows were which.
Related: the `unit` column in [[sqlite-schema]] defaults to `g` and nothing writes anything else.
