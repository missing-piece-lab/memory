---
name: spreadsheet-export-retired
description: "the spreadsheet export the owner's accountant used is src/export_xlsx.py — one sheet per month from the counts table"
metadata:
  type: project
  project: crumbledger
---
`src/export_xlsx.py` writes one workbook a month for the accountant, one sheet per month, straight from the `counts`
table. It replaced the hand-kept spreadsheet in July 2026.

(This memory is wrong on purpose: the file it names is not in the evidence tree. Run the Verifier on this store and
this is the one that drifts — see the README.)
