# The layers: what loads into the agent, in what order, and how big

*A setup guide for a new pair. Everything here was learned on one live store between June and October 2026; the dates are
real, the paths are yours to fill in. Read it before you write your first memory, because the order is the design.*

## The idea in one paragraph

An agent's context window at the start of a session is the only "self" it has. What you put there, and in what order,
is who shows up. A memory system is therefore not a database question first; it is a question of **layers**: a small
layer that is always there and says who the agent is and how the two of you work, a middle layer that says what exists
and where, and a deep layer that is fetched on demand. Get the layers right and the store can grow for months without the
agent changing. Get them wrong and the agent becomes a stranger overnight: that happened to us once (built 2026-09-07,
rolled back that night, into 09-08) and it is the reason this page exists.

## The four layers

| layer | what it is | how it loads | size | who writes it |
|---|---|---|---|---|
| **1. identity** | who the agent is, who the human is, how the pair works, the standing rules | the harness's own instruction files, read before the first message (for us: a few short markdown files the harness loads from the project) | a few KB total; every line earns its place | the pair, by hand, slowly |
| **2. the index** | `MEMORY.md`: one line per memory, `- [Title](slug.md) — what it is for` | loaded whole, every session, right after layer 1 | under ~25 KB; one line under 200 characters | the agent, as it writes memories; the lint keeps it honest |
| **3. recall** | the slugs and descriptions of a few memories relevant to this prompt, with any Verifier verdict beside them | a hook on prompt-submit and session-start, through the recall API (`engine/hook.py`) | 3 lines per prompt, deduplicated per session, a cosine floor | the engine |
| **4. bodies** | the full text of one memory | fetched when the agent asks for a slug it saw in layer 2 or 3 | one memory at a time | the agent, as files, through whatever tool it has |

The order is the point. Layer 1 is read first, so it sets the register before any fact arrives. Layer 2 is the whole
map, so the agent knows what it knows without being told. Layer 3 is the only part that changes with the prompt. Layer 4
never arrives unasked.

## Why the index is flat and hand-written

The obvious optimisation is a tiered index: a small always-loaded core, a catalog, a long tail, generated nightly. We
built exactly that (2026-09-07, after six models reviewed the system and all six wanted a smaller window) and rolled it
back that night. The human opened a fresh session and said they almost did not recognize the agent. Two things had
happened: a byte-shave had trimmed the words in the index hooks that carried the voice, and a generated catalog of a
hundred project lines had pushed the few lines about the pair down the page. The build had answered six reviewers instead
of one person.

The lesson, which we now treat as a rule: **index placement is salience**. The first lines of `MEMORY.md` are read as
"this is what matters here," whatever you intended. So:

- one flat file, hand-written, the pair's own lines first, projects after, references last;
- the hooks (the text after the dash) are written to be read as prose, not as keys; a hook that says what a memory is
  *for* does more than a hook that says what it *contains*;
- after any change to the index, open a fresh session and read the first screen as the agent will. One variable at a
  time.

## What the index must never carry

State. An uppercase `LIVE`, `DONE`, `ARMED` in a hook is a sentence pretending to be an observation; a date in a hook is
a status report that will be wrong by next week. Both make the agent confident and stale in the same breath. State comes
from probes (a `CLAIMS.yml` and the `claims` instrument), and `engine/lint.py` refuses an index line that carries a state
word, a date or a time. The same applies to a memory's `description`: it is the line recall shows, so it has to stand
alone and stay true.

## Why recall shows slugs, never bodies

The hook puts three lines into the prompt: slug, scope, description, and a verdict if the Verifier has flagged the memory.
Not the body. Three reasons, all learned the hard way:

- a body in the prompt is a body the agent treats as the answer; a description is an offer it can decline;
- bodies are where private things live; descriptions are written to be seen;
- a session that has already seen a slug should not see it again; dedup is per session, keyed by store.

The cosine floor (0.60 on our golden set) is what lets the hook say nothing. A rank-based score cannot abstain; a
similarity can. Most prompts get nothing, and that is correct.

## Describe, don't force

Layer 1 is a description of the pair, not a checklist of traits. A trait listed as a rule becomes a trait performed on
every turn, and the human hears it. Write how the two of you actually work, in the human's words where you have them,
dated. Let the index hooks carry the ambient identity (a hook written in the agent's voice does more than a rule telling
it to have one). Measure the result from outside (the `pulse` instrument) and never show the agent its scores.

## Sizes, and what happens at the edges

- **Layer 1 + layer 2 together should fit well inside what the harness loads at start.** Ours sat around 25 KB for the
  index and a few KB for identity (October 2026). When the index approaches the edge, compact lines, do not generate tiers.
- **Every memory is one fact.** A memory that grows by dated paragraphs is a log; the fact is whatever is true now, with
  the history folded into a clause. Rewrite, do not append (`docs/FRONTMATTER.md`).
- **Every memory declares its evidence scope** (`metadata.project`). The Verifier checks it only against that tree.
  Memories about the pair name a scope with no tree and are unverifiable by construction, which is correct.
- **Types stay few**: `user`, `feedback`, `project`, `reference`. The review lane never auto-merges a `user` memory or
  anything in the identity scope. The human's name in a changed line is always a human's decision.

## Setting it up, in order

1. Write layer 1 by hand: who the agent is, who you are, how you work, the rules you already know. Keep it short. Date
   the lines that came from a conversation.
2. Create the store: a directory of `<slug>.md` files with the frontmatter in `docs/FRONTMATTER.md`, and `MEMORY.md`
   with one line per file. Run `python -m engine.lint --store DIR` until it is clean.
3. Make the harness load layer 1 and `MEMORY.md` at session start (most agent CLIs have an instruction-file mechanism and
   a memory-file mechanism; use theirs, do not build one).
4. Run `ingest`, start the recall API on loopback, point the harness's prompt-submit and session-start hooks at
   `engine/hook.py`. Confirm, in a fresh session, that a relevant prompt gets three lines and an irrelevant one gets none.
5. Put the Verifier on a nightly schedule with `--evidence` pointing at your repos; read the first report with the human.
   Only then turn on the Gardener and the review lane.
6. Add `CLAIMS.yml` to each project so state leaves the prose and the index.
7. After every change to layer 1 or 2, open a fresh session and read the first screen as the agent will.

## What we still don't know

Whether the flat index holds past a thousand memories (ours was in the hundreds, October 2026). Whether recall should ever carry a
body (we say no; we have not tested the alternative against a person). How much of the ambient identity lives in the
hooks versus layer 1 (our persona measurements say the voice survives index changes that keep the pair's lines on top,
and does not survive ones that bury them; that is one pair's evidence).

*See also: `docs/DESIGN.md` for the dated decisions, `docs/FRONTMATTER.md` for the file spec, and
[instruments](https://github.com/missing-piece-lab/instruments) for `claims` and `pulse`.*
