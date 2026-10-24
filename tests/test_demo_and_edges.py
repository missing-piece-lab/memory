"""tools/demo.sh end to end, and the sharp edges: a bad supersedes skips one file, null verdicts are not votes, a missing
scope path is 'not mounted', verify before ingest says so, the embedder down → keyword-only, hook state per store, the
scripted model door. Run: python tests/test_demo_and_edges.py (or pytest)."""
import io, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import hook as H, ingest as I, llm, recall as R, store as S, verify as V  # noqa: E402
from engine.graph_mem import MemoryGraph  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example", "store")
os.environ["EMBED_KIND"] = "fake"


def test_demo_runs_green():
    env = {k: v for k, v in os.environ.items() if k not in ("GRAPH_PATH", "MODEL_KIND")}
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "demo.sh")], capture_output=True, text=True, cwd=ROOT, env=env, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    out = r.stdout
    assert "lint: clean" in out and "drift 1," in out and "→ MERGE:" in out and "flagged now: nothing" in out and "demo: done" in out
    assert "review lane: merge gardener/spreadsheet-export-retired" in out


def test_bad_supersedes_skips_one_file():
    tmp = tempfile.mkdtemp(); shutil.copytree(EXAMPLE, tmp, dirs_exist_ok=True)
    open(os.path.join(tmp, "odd.md"), "w").write("---\nname: odd\ndescription: x\nmetadata:\n  type: project\n  project: p\nsupersedes: {a: 1}\n---\nbody\n")
    memories, skipped = S.load(tmp)
    assert len(memories) == 10 and skipped == [("odd.md", "supersedes is dict, not a slug or a list of slugs")]
    assert S._list("a.md") == ["a"] and S._list(["a", " b.md "]) == ["a", "b"] and S._list(None) == []


def test_null_verdicts_are_not_votes():
    g = MemoryGraph(); g.upsert({"slug": "m", "title": "m", "description": "", "body": "b", "type": "project", "project": "p", "refs": [], "frontmatter": {}})
    import time; time.sleep(0.01)
    run = g.start_run("report")
    for v in ("STALE", None, None, None, "STALE"):            # three unjudged nights between two STALE votes
        fid = g.add_finding(run, "m", "drift", []); g.set_verdict(fid, v, "r" if v else "judge error: Timeout")
    assert [f["slug"] for f in g.flagged()] == ["m"] and g.flagged()[0]["votes"] == 2
    fid = g.add_finding(run, "m", "drift", []); g.set_verdict(fid, "CONFIRMED", "ok")
    fid = g.add_finding(run, "m", "drift", []); g.set_verdict(fid, "CONFIRMED", "ok")
    assert g.flagged() == []                                  # the last three judged: CONFIRMED, CONFIRMED, STALE


def test_missing_scope_and_verify_before_ingest():
    err = io.StringIO(); old = sys.stderr; sys.stderr = err
    try:
        scopes = V.discover(None, [f"crumbledger={os.path.join(ROOT, 'example', 'evidence', 'crumbledger')}", "ghost=/nowhere/at/all"])
    finally:
        sys.stderr = old
    assert set(scopes) == {"crumbledger"} and "treated as not mounted" in err.getvalue()
    g = MemoryGraph()
    try:
        V.run(EXAMPLE, g, scopes); assert False
    except SystemExit as e:
        assert "nothing ingested yet: run ingest first" in str(e)
    I.ingest(EXAMPLE, g, do_embed=False)
    counts, findings, _ = V.run(EXAMPLE, g, scopes)
    assert counts["drift"] == 1


def test_embedder_down_falls_back_to_keywords():
    g = MemoryGraph(); I.ingest(EXAMPLE, g)
    def down(text):
        raise ConnectionError("refused")
    err = io.StringIO(); old = sys.stderr; sys.stderr = err
    try:
        rows = R.recall(g, "holiday multiplier", k=2, embed_fn=down)
    finally:
        sys.stderr = old
    assert rows and rows[0]["slug"] == "holiday-multiplier" and rows[0]["sim"] is None and "keyword-only" in err.getvalue()


def test_hook_state_is_per_store_and_fake_model_door():
    a, b = H.state_path("s1", "http://127.0.0.1:8450"), H.state_path("s1", "http://127.0.0.1:8451")
    assert a != b and a == H.state_path("s1", "http://127.0.0.1:8450") and os.path.basename(a).startswith("memory-hook-")
    os.environ["MODEL_KIND"] = "fake"
    for k in ("MODEL_API_KEY", "MODEL_NAME"):
        os.environ.pop(k, None)
    assert llm.available() is True
    assert llm.parse_json(llm.complete("s", "REFERENCE CHECK:\n- `x.py` [path] -> missing"))["verdict"] == "STALE"
    assert llm.parse_json(llm.complete("s", "REFERENCE CHECK:\n- `x.py` [path] -> ok"))["verdict"] == "CONFIRMED"
    assert llm.complete("s", "MEMORY FILE:\n<file>\n---\nname: a\n---\nbody\n</file>\n") == "<file>\n---\nname: a\n---\nbody\n</file>"
    assert llm.complete("s", "PROPOSAL\n...\n\nDIFF\n...").startswith("MERGE:")
    os.environ.pop("MODEL_KIND")
    assert llm.available() is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
