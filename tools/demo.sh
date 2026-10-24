#!/usr/bin/env bash
# demo.sh — the whole loop, offline, in a temp dir: lint → ingest → recall → verify (twice) → Gardener → review lane.
#   bash tools/demo.sh [--keep]        --keep leaves the temp dir behind and prints its path
# Fake everywhere: EMBED_KIND=fake (a hashed bag of words), MODEL_KIND=fake (a scripted judge: a missing reference is
# STALE, a draft comes back unchanged so the Gardener writes its dated note, a review is MERGE). Nothing is called;
# nothing here says anything about quality. It shows each piece handing to the next, and what every file looks like.
set -euo pipefail
cd "$(dirname "$0")/.."
T="$(mktemp -d)"; [ "${1:-}" = "--keep" ] || trap 'rm -rf "$T"' EXIT
export EMBED_KIND=fake MODEL_KIND=fake GRAPH_PATH="$T/graph.json" PYTHONPATH="$PWD"
say() { printf '\n\033[1m── %s\033[0m\n' "$*"; }

say "1. a store: example/store copied to $T/store and made a git repo on main (the Gardener branches off it)"
cp -r example/store "$T/store"; cp -r example/evidence "$T/evidence"
git -C "$T/store" init -q -b main
git -C "$T/store" -c user.name=demo -c user.email=demo@localhost add -A
git -C "$T/store" -c user.name=demo -c user.email=demo@localhost commit -q -m "the store"

say "2. lint: the index rule (no state stamps, no dates) and the frontmatter spec"
python3 -m engine.lint --store "$T/store"

say "3. ingest: files → the in-process graph (Postgres in production), [[links]] → edges, bodies embedded"
python3 -m engine.ingest --store "$T/store"

say "4. recall: keyword + vector, reciprocal rank fusion, one hop of links"
python3 -m engine.recall "when do we reorder flour" -k 3

say "5. verify, night one: seven of the ten memories carry references; one names a file that is not there"
python3 -m engine.verify --store "$T/store" --evidence "$T/evidence" --out "$T/reports" --sample 0
say "   night two: the same drift, the same verdict — 2 of the last 3 judged findings are STALE → flagged"
python3 -m engine.verify --store "$T/store" --evidence "$T/evidence" --out "$T/reports" --sample 0
sed -n '1,12p' "$(ls -t "$T"/reports/verifier-*.md | head -1)"

say "6. the Gardener: one branch per flagged memory, a dated note (the scripted model drafts nothing), a proposal file"
python3 -m engine.gardener --repo "$T/store" --out "$T/proposals"
branch="$(git -C "$T/store" branch --list 'gardener/*' --format='%(refname:short)' | head -1)"
[ -n "$branch" ] || { echo "demo: the Gardener opened no branch — the flag did not form"; exit 1; }
git -C "$T/store" diff "main...$branch" | sed -n '1,30p'

say "7. the review lane: the guard (code), then the cold read (scripted MERGE), then the merge into main"
python3 -m engine.review "$branch" --repo "$T/store" --out "$T/reviews" --proposal "$T/proposals/${branch//\//--}.md" --human Mara
git -C "$T/store" log --oneline -3

say "8. the next ingest sees the merged file, moves updated_at, and the flag is void"
python3 -m engine.ingest --store "$T/store"
python3 - <<'EOF'
import os, sys; sys.path.insert(0, os.getcwd())
from engine.graph import open_graph
print("flagged now:", [f["slug"] for f in open_graph().flagged()] or "nothing")
EOF
[ "${1:-}" = "--keep" ] && echo "kept: $T"
echo; echo "demo: done"
