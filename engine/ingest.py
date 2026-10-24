#!/usr/bin/env python3
"""ingest — files → graph. Idempotent; run it as often as you like (nightly, or on every push of the store).

  python -m engine.ingest --store DIR [--graph graph.json] [--no-embed]

One node per memory, upserted on slug; [[links]] become relates_to edges (a link to a memory not yet written dangles,
which is a TODO you can query); `supersedes:` closes the target's validity window; a file that left the store is
archived, never deleted; a node whose content changed loses its embedding and is re-embedded here. One bad frontmatter
skips that file loudly and the rest go on.
"""
import argparse, sys

from . import embed as E, store as S
from .graph import open_graph


def ingest(store, graph, do_embed=True, embed_fn=None):
    memories, skipped = S.load(store)
    if not memories:
        raise SystemExit(f"ingest: no memories in {store!r}" + (f" ({len(skipped)} skipped)" if skipped else ""))
    changed = 0
    for m in memories:
        changed += graph.upsert({"slug": m.slug, "title": m.title, "description": m.description, "body": m.body, "type": m.type,
                                 "project": m.project, "refs": m.refs, "frontmatter": m.frontmatter})
        graph.set_links(m.slug, m.links)
    closed, reopened = graph.apply_supersedes({m.slug: m.supersedes for m in memories if m.supersedes})
    archived = graph.archive_missing({m.slug for m in memories})
    embedded = 0
    if do_embed:
        fn = embed_fn or (lambda text: E.embed(text, kind="document"))
        for slug, text in graph.unembedded():
            graph.set_embedding(slug, fn(text)); embedded += 1
    graph.save()
    out = {"nodes": len(memories), "changed": changed, "embedded": embedded, "archived": archived, "closed": closed,
           "reopened": reopened, "skipped": skipped, "dangling": sum(1 for m in memories for l in m.links if l not in {x.slug for x in memories})}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", required=True); ap.add_argument("--graph"); ap.add_argument("--no-embed", action="store_true")
    a = ap.parse_args(argv)
    g = open_graph(a.graph)
    try:
        r = ingest(a.store, g, do_embed=not a.no_embed)
    finally:
        g.close()
    print(f"ingested {r['nodes']} nodes ({r['changed']} new or changed, {r['embedded']} embedded, {r['dangling']} dangling links)"
          + (f", {r['archived']} archived" if r["archived"] else "") + (f", {r['closed']} superseded" if r["closed"] else ""))
    for fname, why in r["skipped"]:
        print(f"SKIPPED {fname}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
