"""graph_mem + embed + llm helpers — upserts, supersedes, archive, hybrid recall, the 2-of-3 rule, persistence.
Run: python tests/test_graph.py (or pytest)."""
import os, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import embed as E, llm  # noqa: E402
from engine.graph_mem import MemoryGraph  # noqa: E402


def node(slug, body, type="project", project="p", title=None, description=""):
    return {"slug": slug, "title": title or slug, "description": description, "body": body, "type": type, "project": project,
            "refs": [], "frontmatter": {}}


def test_upsert_changed_and_embedding_reset():
    g = MemoryGraph()
    assert g.upsert(node("a", "one")) is True
    g.set_embedding("a", E.fake_embed("one"))
    assert g.upsert(node("a", "one")) is False and g.d["nodes"]["a"]["embedding"] is not None   # a no-op ingest keeps the vector
    before = g.d["nodes"]["a"]["updated_at"]; time.sleep(0.01)
    assert g.upsert(node("a", "two")) is True and g.d["nodes"]["a"]["embedding"] is None            # an edit drops it
    assert g.d["nodes"]["a"]["updated_at"] > before
    assert g.unembedded() == [("a", "a\n\ntwo")]


def test_supersedes_and_archive():
    g = MemoryGraph()
    for s in ("old", "new", "other"):
        g.upsert(node(s, s))
    assert g.apply_supersedes({"new": ["old"]}) == (1, 0)
    assert g.d["nodes"]["old"]["valid_to"] and g.d["nodes"]["old"]["invalidated_by"] == "new"
    assert {n["slug"] for n in g._live()} == {"new", "other"}
    assert g.apply_supersedes({}) == (0, 1) and g.d["nodes"]["old"]["valid_to"] is None   # the field removed → reopened
    assert g.archive_missing({"new", "old"}) == 1 and g.d["nodes"]["other"]["status"] == "archived"
    g.upsert(node("other", "other"))
    assert g.d["nodes"]["other"]["status"] == "active"                                      # the file came back → live again


def test_hybrid_recall_and_neighbors():
    g = MemoryGraph()
    docs = {"flour": "the reorder point for bread flour uses seven days of usage", "yeast": "fresh yeast is kept cold and counted daily",
            "butter": "butter arrives in 25 kg blocks from the dairy", "private-note": "a private note about the owner's holiday"}
    for s, b in docs.items():
        g.upsert(node(s, b, type="private" if s == "private-note" else "project"))
        g.set_embedding(s, E.fake_embed(b))
    g.set_links("flour", ["yeast", "nowhere"])
    rows = g.recall("when do we reorder flour", E.fake_embed("when do we reorder flour"), k=3)
    assert rows[0]["slug"] == "flour" and rows[0]["sim"] is not None and rows[0]["score"] > rows[-1]["score"]
    assert all(r["type"] != "private" for r in g.recall("owner holiday", E.fake_embed("owner holiday"), k=4, exclude_types=["private"]))
    assert g.neighbors(["flour"]) == {"flour": [{"slug": "yeast", "title": "yeast"}]}                 # the dangling link is not a neighbour
    g.log_recall("test", "s1", "q", ["flour"], 0.5)
    assert g.d["events"][0]["returned"] == ["flour"] and g.count_active() == 4


def test_flagged_two_of_three_after_edit():
    g = MemoryGraph(); g.upsert(node("m", "body")); time.sleep(0.01)
    run = g.start_run("report")
    ids = [g.add_finding(run, "m", "drift", []) for _ in range(3)]
    g.set_verdict(ids[0], "STALE", "r1"); g.set_verdict(ids[1], "CONFIRMED", "r2")
    assert g.flagged() == []                                              # one bad vote is not a flag
    g.set_verdict(ids[2], "CONTRADICTED", "r3")
    f = g.flagged()
    assert len(f) == 1 and f[0]["verdict"] == "CONTRADICTED" and f[0]["bad_votes"] == 2 and f[0]["votes"] == 3
    time.sleep(0.01); g.upsert(node("m", "edited body"))
    assert g.flagged() == []                                              # an edit voids every verdict
    g.finish_run(run, {"nodes": 1}); assert g.last_run()["nodes"] == 1
    assert [x["id"] for x in g.findings("m", before_id=ids[2])] == [ids[1], ids[0]]


def test_persistence_roundtrip():
    path = os.path.join(tempfile.mkdtemp(), "g.json")
    g = MemoryGraph(path); g.upsert(node("a", "x")); g.set_anchor("a", "src/x.py", "p/src/x.py", "abc"); g.save()
    h = MemoryGraph(path)
    assert "a" in h.d["nodes"] and h.anchors("a")["src/x.py"][0] == "abc" and h.anchors("a")[ "src/x.py"][2] == "p/src/x.py"


def test_embed_and_llm_helpers():
    v = E.fake_embed("bread flour", 32)
    assert len(v) == 32 and abs(sum(x * x for x in v) - 1) < 1e-6 and v == E.fake_embed("bread flour", 32)
    assert E.cosine(v, v) > 0.999 and E.cosine(E.fake_embed("flour"), E.fake_embed("flour sack")) > E.cosine(E.fake_embed("flour"), E.fake_embed("butter"))
    os.environ.pop("EMBED_KIND", None); assert E.config()["kind"] == "fake" and E.embed("x", "document") == E.fake_embed("x")
    os.environ["EMBED_KIND"] = "ollama"; assert E.config()["prefix"] is True and E.config()["model"] == "nomic-embed-text"
    os.environ["EMBED_KIND"] = "openai"; assert E.config()["prefix"] is False; os.environ.pop("EMBED_KIND")
    assert llm.parse_json('```json\n{"verdict": "STALE", "reason": "a path C:\\Users\\x"}\n```')["verdict"] == "STALE"
    assert llm.parse_json("no json here") is None
    for k in ("MODEL_API_KEY", "MODEL_NAME"):
        os.environ.pop(k, None)
    assert llm.available() is False
    os.environ["MODEL_NAME"] = "m"; os.environ["VERIFIER_MODEL"] = "v"
    assert llm.model_for("verifier") == "v" and llm.model_for("gardener") == "m"
    os.environ.pop("MODEL_NAME"); os.environ.pop("VERIFIER_MODEL")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
