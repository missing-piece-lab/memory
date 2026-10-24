"""ingest → recall → the HTTP API → the hook, end to end on the example store with the fake embedder. A real local socket,
no network beyond loopback. Run: python tests/test_recall_hook.py (or pytest)."""
import io, json, os, sys, tempfile, threading, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import hook as H, ingest as I, recall as R  # noqa: E402
from engine.embed import fake_embed  # noqa: E402
from engine.graph_mem import MemoryGraph  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example", "store")
os.environ["EMBED_KIND"] = "fake"


def graph():
    g = MemoryGraph(os.path.join(tempfile.mkdtemp(), "g.json"))
    r = I.ingest(EXAMPLE, g)
    assert r["nodes"] == 10 and r["embedded"] == 10 and r["dangling"] == 1 and not r["skipped"]
    return g


def test_ingest_idempotent_and_recall():
    g = graph()
    assert I.ingest(EXAMPLE, g)["changed"] == 0
    rows = R.recall(g, "how do we decide when to reorder flour", k=3)
    assert rows[0]["slug"] == "flour-reorder-point" and rows[0]["related"][0]["slug"] == "thresholds-live-in-yaml"
    assert "verdict" not in rows[0] and g.d["events"][-1]["source"] == "cli"
    assert all(r["type"] != "user" for r in R.recall(g, "what does the owner read in the morning", k=5, exclude_types=["user"]))
    run = g.start_run("report")                                   # a sweep after the ingest: its verdicts count
    for _ in range(2):
        g.set_verdict(g.add_finding(run, "flour-reorder-point", "drift", []), "STALE", "the cushion is gone")
    rows = R.recall(g, "reorder flour", k=1)
    assert rows[0]["verdict"] == {"verdict": "STALE", "reason": "the cushion is gone", "votes": "2/2", "last_seen": rows[0]["verdict"]["last_seen"]}
    assert R.status(g)["flagged"][0]["slug"] == "flour-reorder-point"


def test_api_and_hook():
    g = graph()
    srv = R.serve(g, "secret", "127.0.0.1", 0, embed_fn=lambda t: fake_embed(t))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"

    def call(path, data=None, token="secret"):
        req = urllib.request.Request(url + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    assert call("/healthz", token="")[1]["nodes"] == 10
    assert call("/status", token="wrong")[0] == 401 and call("/recall", {"query": "x"}, token="")[0] == 401
    assert call("/recall", {"k": 2})[0] == 400 and call("/nope")[0] == 404
    code, out = call("/recall", {"query": "flour reorder cushion", "k": 2, "source": "test", "session": "s1"})
    assert code == 200 and out["results"][0]["slug"] == "flour-reorder-point" and "body" in out["results"][0]
    assert call("/status")[1]["nodes"] == 10

    os.environ.update(RECALL_URL=url, RECALL_TOKEN="secret", HOOK_MIN_SIM="0.0")
    sid = f"t{port}"
    def run_hook(d):
        buf = io.StringIO(); old = sys.stdout; sys.stdout = buf
        try:
            H.main(io.StringIO(json.dumps(d)))
        finally:
            sys.stdout = old
        return json.loads(buf.getvalue())["hookSpecificOutput"]["additionalContext"] if buf.getvalue() else ""
    ctx = run_hook({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "how do we decide when to reorder flour?"})
    assert "flour-reorder-point" in ctx and "[crumbledger]" in ctx and "Decided 2026" not in ctx       # slug + description, never the body
    ctx2 = run_hook({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "how do we decide when to reorder flour?"})
    assert "flour-reorder-point" not in ctx2                                                             # shown once per session
    assert run_hook({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "short"}) == ""
    assert run_hook({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "/slash command with a long prompt text"}) == ""
    ctx3 = run_hook({"hook_event_name": "SessionStart", "session_id": sid + "b", "cwd": os.path.join(ROOT, "example", "evidence", "crumbledger")})
    assert "for this project" in ctx3
    os.environ["RECALL_TOKEN"] = ""
    assert run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "x", "prompt": "how do we decide when to reorder flour?"}) == ""
    os.environ["RECALL_URL"] = "http://127.0.0.1:1"; os.environ["RECALL_TOKEN"] = "secret"
    assert run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "y", "prompt": "how do we decide when to reorder flour?"}) == ""  # API down → silent
    srv.shutdown()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
