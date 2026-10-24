"""The three contracts from the second cold read: type exclusion reaches `related`; `.env` loads and the embedding
dimension is checked up front; a moved reference is re-anchored, reported as `moved`, never judged, never ok.
Run: python tests/test_contracts.py (or pytest)."""
import json, os, shutil, sys, tempfile, threading, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import config as C, embed as E, ingest as I, recall as R, verify as V  # noqa: E402
from engine.graph_mem import MemoryGraph  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example")
os.environ["EMBED_KIND"] = "fake"


def test_excluded_type_never_appears_in_related():
    g = MemoryGraph(); I.ingest(os.path.join(EXAMPLE, "store"), g)
    g.set_links("flour-reorder-point", ["thresholds-live-in-yaml", "owner-reads-plain-tables"])      # a link to a `user` memory
    assert {n["slug"] for n in g.neighbors(["flour-reorder-point"])["flour-reorder-point"]} == {"thresholds-live-in-yaml", "owner-reads-plain-tables"}
    assert {n["slug"] for n in g.neighbors(["flour-reorder-point"], ["user"])["flour-reorder-point"]} == {"thresholds-live-in-yaml"}
    rows = R.recall(g, "flour reorder cushion", k=1, exclude_types=["user"])
    assert rows[0]["slug"] == "flour-reorder-point" and "owner-reads-plain-tables" not in {n["slug"] for n in rows[0]["related"]}
    srv = R.serve(g, "t", "127.0.0.1", 0, embed_fn=E.fake_embed); threading.Thread(target=srv.serve_forever, daemon=True).start()
    def call(excl):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/recall", data=json.dumps({"query": "flour reorder cushion", "k": 1, "exclude_types": excl}).encode(),
                                     headers={"Authorization": "Bearer t", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return {n["slug"] for n in json.load(r)["results"][0]["related"]}
    assert "owner-reads-plain-tables" in call([]) and "owner-reads-plain-tables" not in call(["user"])
    srv.shutdown()


def test_dotenv_and_dimension_check():
    tmp = tempfile.mkdtemp(); path = os.path.join(tmp, ".env")
    open(path, "w").write('# comment\nDEMO_A=one\nDEMO_B="two words"  # trailing\nDEMO_C=\'three\'\nEMBED_KIND=openai\nbroken line\n')
    os.environ["DEMO_C"] = "already"
    assert C.load_env(path) == 2 and os.environ["DEMO_A"] == "one" and os.environ["DEMO_B"] == "two words" and os.environ["DEMO_C"] == "already"
    assert os.environ["EMBED_KIND"] == "fake" and C.load_env(os.path.join(tmp, "missing")) == 0   # a set variable wins; no file → nothing
    for k in ("DEMO_A", "DEMO_B", "DEMO_C"):
        os.environ.pop(k)
    assert C.check_embedding_dim() == 64 and E.config()["dim"] == 64
    os.environ["EMBED_DIM"] = "32"; assert C.check_embedding_dim() == 32
    real = E.embed; E.embed = lambda text, kind="query", cfg=None: [0.0] * 10
    try:
        C.check_embedding_dim(); assert False
    except SystemExit as e:
        assert "returns 10 floats but EMBED_DIM is 32" in str(e)
    finally:
        E.embed = real
    g = MemoryGraph(); g.upsert({"slug": "a", "title": "a", "description": "", "body": "b", "type": "project", "project": "p", "refs": [], "frontmatter": {}})
    try:
        g.set_embedding("a", [0.0] * 64); assert False
    except ValueError as e:
        assert "EMBED_DIM is 32" in str(e)
    g.set_embedding("a", [0.0] * 32)
    os.environ.pop("EMBED_DIM")
    os.environ["EMBED_KIND"] = "ollama"; assert E.config()["dim"] == 768; os.environ["EMBED_KIND"] = "fake"


def test_moved_is_drift_lite():
    tmp = tempfile.mkdtemp(); shutil.copytree(EXAMPLE, tmp, dirs_exist_ok=True)
    store, evidence = os.path.join(tmp, "store"), os.path.join(tmp, "evidence")
    g = MemoryGraph(); I.ingest(store, g, do_embed=False)
    os.rename(os.path.join(evidence, "crumbledger", "configs", "thresholds.yml"), os.path.join(evidence, "crumbledger", "thresholds.yml"))
    judged = []
    def judge(system, user):
        judged.append(user.split("slug=", 1)[1].split(",", 1)[0]); return '{"verdict":"STALE","reason":"x"}'
    counts, findings, path = V.run(store, g, V.discover(evidence), out=os.path.join(tmp, "r"), complete=judge, sample_n=0)
    f = next(f for f in findings if f["slug"] == "thresholds-live-in-yaml")
    d = next(d for d in f["details"] if d["ref"] == "configs/thresholds.yml")
    assert f["result"] == "moved" and counts["moved"] == 1 and counts["ok"] == 5 and counts["drift"] == 1
    assert d["status"] == "moved" and d["anchor"] == "moved" and g.anchors("thresholds-live-in-yaml")["configs/thresholds.yml"][2] == "crumbledger/thresholds.yml"
    assert f["verdict"] is None and "thresholds-live-in-yaml" not in judged and judged == ["spreadsheet-export-retired"]
    text = open(path).read()
    assert "## Moved (drift-lite" in text and "`thresholds-live-in-yaml`: `configs/thresholds.yml` — crumbledger/thresholds.yml" in text and "moved 1," in text
    counts2, findings2, _ = V.run(store, g, V.discover(evidence), complete=judge, sample_n=0)                 # night two: still moved, still not changed
    assert next(f for f in findings2 if f["slug"] == "thresholds-live-in-yaml")["result"] == "moved" and counts2["changed"] == 0
    assert [x["slug"] for x in g.flagged()] == ["spreadsheet-export-retired"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
