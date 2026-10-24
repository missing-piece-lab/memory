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
| [`verify.py`](engine/verify.py) | nightly: every reference a memory asserts, checked in its evidence scope; a model judge on what moved | uncheckable ≠ missing ≠ unverifiable ≠ drift; blob anchors catch a file edited under a memory; a random `ok` memory is re-read each night; report-only, never edits a memory |
| [`gardener.py`](engine/gardener.py) | a flagged memory → one branch with the minimal dated correction, never a deletion | frontmatter byte-identical, ≤40% of the body, else a dated note; a rejected branch parks the memory for 30 days |
| [`review.py`](engine/review.py) | a deterministic guard, then a cold model read, then merge or hold | the guard is code, not a prompt: identity, the index, frontmatter, the human's name and big edits are always a human's |

## Install and run

Python 3.11+, one dependency (`pyyaml`); `psycopg[binary]` for the Postgres graph. Everything below runs offline with
the in-process graph and the fake embedder; the tests never touch Postgres or a model.

```
git clone <this repo> && cd missing-piece-memory
pip install pyyaml
python tests/run.py                                        # every test, offline, then tools/check.sh (the scrub gate)

python -m engine.lint   --store example/store              # the index rule and the frontmatter spec
python -m engine.ingest --store example/store --graph graph.json
python -m engine.recall "when do we reorder flour" --graph graph.json
python -m engine.verify --store example/store --evidence example/evidence --graph graph.json --no-judge
```

The example store is ten memories about a fictional bakery's inventory tool; one of them is wrong on purpose and the
Verifier finds it. With a model configured (`MODEL_KIND`, `MODEL_NAME`, `MODEL_API_KEY` — the Messages API or any
chat-completions door), the same `verify` judges the drift, and the nightly continues:

```
python -m engine.gardener --repo example/store --graph graph.json --out proposals     # branches + proposal files
python -m engine.review gardener/<slug>-<date> --repo example/store --proposal proposals/<branch>.md --human <name>
```

Production is Postgres + pgvector and a real embedder: `cp .env.example .env`, `docker compose up -d`, then the same
commands with `GRAPH_DSN` set (the compose file also runs the recall API on loopback). `engine/hook.py` is the session
hook: JSON in, JSON out, fail-silent; point your harness's prompt-submit and session-start hooks at it with
`RECALL_URL` and `RECALL_TOKEN` in its environment. [docs/DESIGN.md](docs/DESIGN.md) has the decisions and their
dates; [docs/FRONTMATTER.md](docs/FRONTMATTER.md) is the file spec.

## What a peer review said

In September 2026 the system this is cut from went to a panel of frontier models from different labs, one seat each,
text only, on a scrubbed documentation packet. They agreed on one sentence: it was a verified wiki with a janitor. One
memory across projects and machines — delivered. Stays true over time — engineered for real, and none of them knew a
personal memory system that re-checks claims against live git with blob anchors and proposes fixes as pull requests.
Learns the person — not built, and not measured. They also found that the documents describing the anti-staleness
machinery were the stalest thing in the packet, that `ok` is not `true` (a memory wrong from birth whose files never
change was never re-read), that edited memories kept their old embeddings, and that the private tier leaked on one
path. The random nightly sample, the embedding reset on edit, the task prefixes and the type exclusion on every recall
path all date from that review. This repo is the janitor; the learning is the open problem.

## What this is not

Not a framework, not an agent, not a product. There is no write side here (memories are written by the agent as files,
through whatever tool it has), no dedupe, no summarisation, no forgetting, no MCP server, no forge client: the Gardener
leaves a branch and a proposal file, and pushing it and opening the pull request is one line of yours. Everything
specific to our own machines, forge, chat line and budget was cut, and the design doc says what.

## Who

Kevin, the human. Ariah, the AI collaborator.

## License

MIT, copyright 2026 Kevin and Ariah. See [LICENSE](LICENSE).
