# The memory file, specified

One file per durable fact, `<slug>.md` in the store directory, kebab-case slug, UTF-8, LF. The lint (`python -m
engine.lint --store DIR`) enforces everything marked **must**.

```markdown
---
name: flour-reorder-point                       # must equal the filename without .md
description: "one line: what this memory is FOR, as the index will show it"   # must be present; quote it if it has a colon
metadata:
  type: project                                 # must be one of: user | feedback | project | reference
  project: crumbledger                          # must be present: the evidence scope (see below)
  origin: {model: "...", harness: "..."}        # optional provenance — scope, never evidence
  session: "..."                                # optional: the session id that wrote it
supersedes: [old-slug]                          # optional: closes the named memory's validity window
---
The body: the fact, in prose, with the paths, flags and symbols it relies on in backticks, dated where a date matters.
Links to other memories as [[slug]]. One fact; a second fact is a second file.
```

## Fields

- **`name`** — the slug. The filename is the identity; `name` repeats it so the file is self-describing when copied.
- **`description`** — one line. This is what the recall hook shows a session (never the body), so it must stand alone.
  It is also what the index line's hook should echo. No state stamps, no dates (the lint applies the index rule here too
  in our running system; this repo's lint checks the index).
- **`metadata.type`** — `user`: about the human (preferences, context; the review lane never auto-merges these).
  `feedback`: how to work (rules learned; conventionally the description starts with `RULE:`). `project`: what is built
  and why. `reference`: where things are, what shape they have.
- **`metadata.project`** — the evidence scope: the name of the repository or directory the Verifier checks this memory
  against (`--evidence DIR/<project>/` or `--scope project=path`). A memory with no code evidence (about the pair, about a
  person) names a scope with no tree — `identity` by convention — and is unverifiable by construction. Never omit it: the
  Verifier's "mounted here or not" question needs an answer.
- **`metadata.origin`** — where the memory was written (which model, which harness, which machine class). The judge is
  shown it as scope, never as evidence; the review lane may hold memories from an origin it does not auto-merge.
- **`supersedes`** — a slug or list. Ingest adds a `supersedes` edge and closes the target's validity window: it leaves
  recall and the Verifier but stays in the graph, dated, pointing at what replaced it. Removing the field reopens it. The
  review lane holds any new memory that carries this field.

## The body

- Backtick every path, flag and dotted symbol the fact depends on: that is what `extract_refs` harvests and the Verifier
  checks. Prose that mentions a filename unbackticked is still harvested if it has a code extension.
- Do not quote a retired filename as a bare path ("renamed from `old.py`") — it becomes a missing reference. Describe it.
- Date the claim where the date matters ("since 2026-08-14", "decided 2026-07-30 after …"). A Gardener correction is
  written the same way: "(was X; as of 2026-10-24 Y)".
- Rewrite, do not append. A memory that grows by dated paragraphs is a log; the fact is whatever is true now, with the
  history folded into a clause.

## The index

`MEMORY.md` in the store directory. Free-form headings; every memory has exactly one line of this shape:

```
- [Title](slug.md) — what the memory is for, in one clause
```

The title becomes the node's title in the graph. The hook (after the dash) may not carry an uppercase state word or a
date or time, must keep the line under 200 characters, and must point at a file that exists; every file must have a
line. State lives in probes (a `CLAIMS.yml` and the `claims` instrument), not here.

## Archive, never delete

A file removed from the store is archived on the next ingest: out of recall and the Verifier, kept in the graph with its
findings history. Put the file back and it is live again. A fact that stopped being true is better superseded (a new
file with `supersedes:`) than removed, so the record keeps what was believed and when it changed.
