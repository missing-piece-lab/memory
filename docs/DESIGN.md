# Design decisions, dated

*The engine was built from June to October 2026 against one pair's live store (a few hundred memories, two machines,
a nightly). Each decision below carries the date it was made and the thing that made it. Stories are kept generic; the
dates are real.*

## The shape

- **Files are canonical; the database is a view** (2026-09-07). The June design said the opposite — database canonical,
  markdown exported from it. The build inverted it: a git repo of markdown files is the memory, the Postgres graph is
  derived and rebuilt by `ingest` in seconds. Three reasons: `docker compose down -v` loses nothing; git is free
  provenance; and a fix can be a pull request on a file, which is what makes the Gardener's gate real. The one thing the
  database holds that the files do not is the findings history, so the compose file keeps a volume and you dump it.
- **One flat, hand-written index** (2026-09-08). A generated three-layer index (a small always-loaded core, a catalog, a
  long tail) was built and rolled back the same night: it thinned the identity layer the index exists to carry. One
  `MEMORY.md`, one line per memory, loaded whole, every session. Bodies come through recall. The lint keeps the lines
  under 200 characters and the hooks free of state.
- **Every memory declares its evidence scope** (2026-09-07, `metadata.project`). The Verifier checks a memory only
  against the tree it names, searches that tree first, and tells the judge whether it is mounted. A memory about the pair
  itself names an identity scope that has no tree — unverifiable by construction, which is correct: nothing fact-checks a
  relationship against a repository.
- **The four types stay** (2026-06-22): `user` (about the human), `feedback` (how to work), `project` (what is built),
  `reference` (where things are). They were the convention before the engine existed; the engine extends, never replaces.
- **Fail soft per file** (2026-08-30). One unquoted colon in one description froze the whole graph for a day and skipped
  the Verifier. `store.load` skips the file, says so, and the rest go on; the node's previous version stays in the graph.
- **Build, do not adopt** (2026-06-22). Off-the-shelf memory products were read as reference architecture (hybrid recall
  with rank fusion, validity windows). The two things that make this ours — a Verifier that re-checks claims against the
  code, and a review-gated Gardener — are exactly what none of them do, so the plumbing is copied and the effort goes there.

## Recall

- **Reciprocal rank fusion of two legs and nothing more** (2026-06-23, confirmed 2026-09-30). Keyword and vector, top 50
  each, `1/(60+rank)` summed. A goal-conditioned leg (a second query from the agent's current task) was built and killed
  on measurement: every weight that lifted the ambiguous cases leaked the current topic into unrelated prompts. Ranking
  knobs (title boost, recency, verdict penalty, forgetting as a re-rank) exist in our running system behind flags that
  default to zero and change only when a golden-set A/B says so; none of them is in this repo.
- **`sim` beside `score`** (2026-09-08). A rank-based score cannot say "nothing relevant"; the cosine from the vector leg
  can. The hook abstains below a floor (0.60 on our golden set: correct answers median 0.75, abstentions max 0.64).
- **Asymmetric task prefixes** (2026-09-07). Some local embedding models are trained with `search_document:` /
  `search_query:` prefixes and retrieve off-distribution without them; we had none. On for ollama, off for OpenAI-style.
- **An edited memory is re-embedded** (2026-09-07). The upsert wrote the new body and kept the old vector; the embed step
  only filled nulls. A corrected memory kept recalling like the wrong one. Now a content change nulls the embedding.
- **Types are excluded on every path** (2026-09-07). The default exclusion lived in one client; the raw query, the
  nightly smoke and the API all saw everything. `exclude_types` is a parameter of the graph itself.
- **One hop, not two** (2026-09-06). `related` is the memory's own `[[links]]`. Graph expansion beyond that was never
  shown to help and is not here.
- **A verdict travels with the memory** (2026-09-06). A flagged memory is still recalled — it may still be the best
  answer — but it arrives with the judge's verdict, votes and reason so the session reads the doubt.

## The Verifier

- **Uncheckable is not missing** (2026-07-05, the first sweep). Twenty drift findings, half of them the checker's own
  noise: domain names read as files, URL paths, data files, templates. Classification before checking; a flag, a URL, a
  template, an absolute host path, a data artifact is `uncheckable`, not `missing`. Drift 20 → 10, all ten honest.
- **Unverifiable is not stale** (2026-09-07). A memory whose scope is not mounted on this host cannot be wrong here. Its
  missing references are `unverifiable`: own report section, never judged, never gardened. "Can't see it" and "it's
  gone" are different sentences. (Our running system also treats a reference that never existed in the scope's history
  while the memory is newer than the clone as unpushed work; that needs git history and is not here.)
- **Accepted drift is a reviewed file** (2026-09-03). `accepted.yml`: `{slug: {ref: reason}}`, `"*"` for every missing
  reference of a memory. Add a line when the human rules a reference permanent; never to silence a real rename.
- **Blob anchors** (2026-09-06). Every `ok` reference is pinned to the git blob id of the file it resolved to (computed
  with hashlib; no git needed). Same blob next night: `ok`. Different blob: `changed` — the file the memory relies on was
  edited, and the judge decides whether the claim survives, with a diff when the scope is a git repo. CONFIRMED
  re-anchors; anything else fires again. A memory edited since its anchor resets the anchor silently.
- **Moved is drift-lite** (2026-10-24, from the second cold read of this repo). A reference whose basename turns up
  elsewhere in the scope used to count as `ok` evidence. Now it is re-anchored to where the file is, reported under its
  own heading, never judged and never blessed: the fact may well hold, but the memory's path is wrong and a human or the
  Gardener should fix it. Both the README and `verify.py` say that sentence.
- **Prose is not symbol evidence** (2026-09-25). A dotted symbol grepped across markdown files string-matched a document
  about something else; the judge was shown that document and cried CONTRADICTED. Symbols grep code files only.
- **A memory that mentions a retired filename re-harvests it** (2026-09-03). "Renamed from `old.sql`" makes `old.sql` a
  reference, which is missing. Describe the old name; do not quote it as a path. The Gardener's prompt says the same.
- **Only judged verdicts flag; 2 of the last 3, after the last edit** (2026-09-06). Raw drift is never shown to a
  session. A judge that flaps never flags alone. An edit voids every vote.
- **A judge error is not a verdict** (2026-09-25). An UNCLEAR written on an API failure was a vote; three nights of
  outage would have silenced the judge for eleven. An error leaves the verdict null with the error as the reason.
- **A random `ok` memory is read in full each night** (2026-09-24, from the peer review). Tier 2 fired only on drift and
  changed, so a memory wrong from birth whose files never changed was never re-examined. Three per night, at random, with
  the current content; a STALE from a sample is re-judged until 2-of-3 can see it.
- **Report-only, always** (2026-07-05). The Verifier edits nothing and flips no status. It writes findings and a report.
  The Gardener proposes; a human or the review lane disposes.

## The Gardener and the review lane

- **A fix is a branch, never an edit** (2026-09-06). Frontmatter byte-identical; at most 40% of body lines; YAML still
  parses; a superseded claim is marked in place with the date, never removed. When the model cannot draft that, the
  branch carries one dated note under the frontmatter asking for a human edit. Push and PR are the caller's one line.
- **Blast radius** (2026-09-06). Its own branch namespace, never the base branch; a cap per night; a rejected proposal
  parks the memory for 30 days; a proposal whose flag clears is withdrawn by the Gardener itself (2026-09-07).
- **The guard is code, not a prompt** (2026-09-19). The human asked for the truth loop to close with the AI as the
  reviewer and the human as the reader. The lane holds, before any model is involved: more than one file, anything but a
  memory file, the index, a `user` memory or the identity scope, a frontmatter line, a line that names the human, more
  than 40% of a body, a new memory that is not plain project/reference fact or that would supersede another. A persuasive
  diff cannot talk its way past a regular expression.
- **The reviewer is cold** (2026-09-19). It sees the proposal's evidence and the diff — not the author's reasoning, not
  its own history of verdicts. One line: MERGE or HOLD, with a reason. No model configured means everything is held.
- **Merged is not running** (2026-10-03). A merged proposal changes the file; the next ingest moves `updated_at`; the
  verdict is void. Nothing is true until the ingest has run, which is why the nightly runs it first.

## The index rule: state is observed

- **The index carries no state** (2026-09-19/20). An uppercase LIVE, DONE, ARMED in an index hook is a sentence
  pretending to be an observation; a date in a hook is a status report that will be wrong by next week. State comes from
  probes: a `CLAIMS.yml` of sentences and the shell commands that check them, run by the `claims` instrument into a
  machine-written STATE file. A description that uses a word a probe contradicts is drift, and in our running system a
  second gardener proposes the one-line fix; it is not in this repo, but the lint that keeps stamps out of the index is.

## What was cut for this version

The multi-machine sync (hooks that commit and rebase the store from every box), the forge client (PR open, comment,
merge through an API), the MCP server, the golden-set eval and its nightly recall measurement, fault injection (plant
defects in a scratch copy, score the catch rate), verdict carry-forward (same verdict on identical evidence N nights →
no model call), the confidence writer, forgetting as a re-rank, the ranking knobs, the dreams/unverifiable-by-design
file class, the claims gardener, and provenance tags beyond `metadata.origin`. All real, all ours; none is the idea.
