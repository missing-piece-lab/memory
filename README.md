# The missing piece — a verified memory

*2026-10-24 · the engine without the store: files, a graph, recall, a nightly Verifier, a Gardener, a review lane · MIT*

A long-running agent remembers in files: one markdown file per durable fact, with frontmatter, and an index of one-line
pointers it loads at the start of every session. That part is easy and everyone has it. The part almost nobody has is
what happens to those files on night forty: the path a memory names has moved, the flag it describes was removed, the
"rule" it states was reversed in a conversation nobody wrote down. Recall then serves a confident, stale fact, and the
human pays for it. This repo is the engine we run against our own store to keep that from happening, with our store
taken out and a fictional one put in its place. It is the second repo from the same pair as
[`instruments`](https://github.com/missing-piece-lab/instruments); state-is-observed, the claims runner and the cold
judges live there and are used here by reference.

| piece | one line | the design decision at its heart |
|---|---|---|
| [`engine/store.py`](engine/store.py) + [`lint.py`](engine/lint.py) | a memory = a markdown file with frontmatter; `MEMORY.md` = one pointer per memory | files are canonical, the database is derived and rebuildable; the index carries no state stamps — state comes from probes |
| [`ingest.py`](engine/ingest.py) → [`graph_pg.py`](engine/graph_pg.py) / [`graph_mem.py`](engine/graph_mem.py) | files → Postgres + pgvector (or an in-process graph for tests and a first try) | an edited memory loses its embedding; a deleted file is archived, never deleted; `supersedes:` closes a validity window |
| [`recall.py`](engine/recall.py) + [`hook.py`](engine/hook.py) | hybrid recall (keyword + vector, reciprocal rank fusion, one hop of links) over a token-gated HTTP API; a session hook that recalls N memories for a prompt | rank fusion and nothing cleverer; a flagged memory arrives with its verdict beside it; the hook shows slugs and descriptions, never bodies |
| [`verify.py`](engine/verify.py) | nightly: every reference a memory asserts, checked in its evidence scope; a model judge on what is missing or changed | uncheckable ≠ missing ≠ unverifiable ≠ drift; blob anchors catch a file edited under a memory; a moved reference is re-anchored to where the file now is and reported as `moved` under its own heading — drift-lite: not judged, not counted as ok; a random `ok` memory is re-read each night; report-only, never edits a memory |
| [`gardener.py`](engine/gardener.py) | a flagged memory → one branch with the minimal dated correction, never a deletion | frontmatter byte-identical, ≤40% of the body, else a dated note; a rejected branch parks the memory for 30 days |
| [`review.py`](engine/review.py) | a deterministic guard, then a cold model read, then merge or hold | the guard is code, not a prompt: identity, the index, frontmatter, the human's name and big edits are always a human's |

## Install and run

Python 3.11+, one dependency (`pyyaml`); `psycopg[binary]` for the Postgres graph. Everything below runs offline with
the in-process graph and the fake embedder; the tests never touch Postgres or a model.

```
git clone <this repo> && cd missing-piece-memory
pip install pyyaml
python tests/run.py        # every test, offline, then tools/check.sh: the scrub gate (secret-shaped strings and the size
                           #   cap always; your own private-words list only when one is present — its summary line says which)
bash tools/demo.sh         # the whole loop, offline, in a temp dir: lint → ingest → recall → verify (twice, with a scripted
                           #   judge) → the Gardener's branch → the review lane's merge. Read it; it is the first hour.
```

The example store is ten memories about a fictional bakery's inventory tool. Seven of them carry references into the
evidence tree and the Verifier checks those seven; one names a file that is not there and comes back as drift. The demo
uses `EMBED_KIND=fake` and `MODEL_KIND=fake` — a hashed bag-of-words embedder and a scripted judge that calls every
missing reference STALE — so nothing is called and nothing is learned about quality; the point is to see each piece
hand to the next. The same commands, one at a time:

```
python -m engine.lint   --store example/store                                 # the index rule and the frontmatter spec
python -m engine.ingest --store example/store --graph graph.json
python -m engine.recall "when do we reorder flour" --graph graph.json
python -m engine.verify --store example/store --evidence example/evidence --graph graph.json --no-judge
```

The Gardener and the review lane need a store that is a git checkout and a flagged memory (two STALE/CONTRADICTED
verdicts from a judge), so they are not in the four lines above; `tools/demo.sh` sets both up. With a real model
(`MODEL_KIND` anthropic or openai, `MODEL_NAME`, `MODEL_API_KEY` — the Messages API or any chat-completions door) the
same commands judge, draft and review for real.

Production is Postgres + pgvector and a real embedder: `cp .env.example .env`, `docker compose up -d`, then the same
commands — every CLI reads `.env` from the current directory first (a shell export still wins), and `ingest` checks the
embedder's vector length against `EMBED_DIM` before it touches the graph; the compose file also runs the recall API on
loopback. `engine/hook.py` is the session
hook: JSON in, JSON out, fail-silent; point your harness's prompt-submit and session-start hooks at it with
`RECALL_URL` and `RECALL_TOKEN` in its environment. [docs/DESIGN.md](docs/DESIGN.md) has the decisions and their
dates; [docs/FRONTMATTER.md](docs/FRONTMATTER.md) is the file spec.

## What a review said

In an internal review by several models in September 2026, reading a scrubbed documentation packet of the system this
is cut from, reviewers summarized the design as "a verified wiki with a janitor" and asked for: a random re-read of
memories whose checks pass (a memory wrong from birth whose files never change is otherwise never looked at again);
embeddings reset when a memory is edited; task prefixes for the embedding model; the type exclusion applied on every
recall path, not one client; and the documentation brought in line with the running system. All five are in this repo.
What the review found missing — anything that learns the person over time, and a way to measure it — is not.

## What this is not

Not a framework, not an agent, not a product. There is no write side here (memories are written by the agent as files,
through whatever tool it has), no dedupe, no summarisation, no forgetting, no MCP server, no forge client: the Gardener
leaves a branch and a proposal file, and pushing it and opening the pull request is one line of yours. Everything
specific to our own machines, forge, chat line and budget was cut, and the design doc says what.

## Who

Kevin, the human. Ariah, the AI collaborator.

## License

MIT, copyright 2026 Kevin and Ariah. See [LICENSE](LICENSE).
