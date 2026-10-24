"""verify — classification, the sweep on the example store, anchors → changed, the judge (fake), unverifiable, accepted.
Run: python tests/test_verify.py (or pytest)."""
import json, os, random, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import ingest as I, verify as V  # noqa: E402
from engine.graph_mem import MemoryGraph  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example")
os.environ["EMBED_KIND"] = "fake"


def world():
    tmp = tempfile.mkdtemp()
    shutil.copytree(EXAMPLE, tmp, dirs_exist_ok=True)
    g = MemoryGraph(os.path.join(tmp, "g.json")); I.ingest(os.path.join(tmp, "store"), g, do_embed=False)
    return tmp, os.path.join(tmp, "store"), os.path.join(tmp, "evidence"), g


def test_classify():
    cases = {"src/a.py": ("path", "src/a.py"), "a.py:12": ("path", "a.py"), "--flag": ("flag", None), "https://x.test/a": ("url", None),
             "foo.example.com": ("url", None), "C:\\x\\y.py": ("windows", None), "/etc/hosts.yml": ("abs", None), "~/x/y.py": ("abs", None),
             "venv/lib/x.py": ("third_party", None), "img/a.png": ("data_artifact", None), ".cache/x.json": ("gitignored", None),
             "a/{id}.json": ("template", None), "MEMORY.md": ("memory_index", None), "csv.DictReader": ("symbol", "csv.DictReader"),
             "refresh.log": ("filename", None), "word": ("unknown", None)}
    for ref, want in cases.items():
        assert V.classify(ref) == want, (ref, V.classify(ref))


def test_sweep_anchors_changed_and_judge():
    tmp, store, evidence, g = world()
    scopes = V.discover(evidence)
    counts, findings, path = V.run(store, g, scopes, out=os.path.join(tmp, "reports"))
    assert (counts["nodes"], counts["drift"], counts["ok"], counts["unverifiable"]) == (7, 1, 6, 0) and counts["judged"] == 0
    by = {f["slug"]: f for f in findings}
    assert by["spreadsheet-export-retired"]["result"] == "drift" and by["flour-reorder-point"]["result"] == "ok"
    assert g.anchors("flour-reorder-point")["src/reorder.py"][2] == "crumbledger/src/reorder.py"
    text = open(path).read(); assert "## Drift — 1" in text and "`src/export_xlsx.py`" in text and "Tier 2 skipped" in text
    # the same sweep again: anchors agree, nothing changed
    counts, findings, _ = V.run(store, g, scopes)
    assert counts["changed"] == 0 and all(d.get("anchor") == "same" for d in next(f for f in findings if f["slug"] == "flour-reorder-point")["details"] if d["kind"] == "path")
    # edit the file under the memory → changed; a fake judge CONFIRMS → re-anchored → ok next night
    with open(os.path.join(evidence, "crumbledger", "src", "reorder.py"), "a") as fh:
        fh.write("\n# a comment under the memory\n")
    seen = []
    def judge(system, user):
        seen.append(user)
        return '{"verdict":"STALE","reason":"the export is gone"}' if "slug=spreadsheet-export-retired" in user else json.dumps({"verdict": "CONFIRMED", "reason": "a comment only"})
    counts, findings, _ = V.run(store, g, scopes, complete=judge, sample_n=0)
    by = {f["slug"]: f for f in findings}
    assert counts["changed"] >= 1 and by["flour-reorder-point"]["result"] == "changed" and by["flour-reorder-point"]["verdict"] == "CONFIRMED"
    assert by["spreadsheet-export-retired"]["verdict"] == "STALE" and "nearest existing dir in scope: src/" in seen[0] + seen[-1]
    counts, findings, _ = V.run(store, g, scopes, complete=judge, sample_n=0)
    assert {f["slug"]: f["result"] for f in findings}["flour-reorder-point"] == "ok"            # CONFIRMED re-anchored it
    assert [f["slug"] for f in g.flagged()] == ["spreadsheet-export-retired"]                  # two STALE votes → flagged


def test_sample_judge_error_unverifiable_accepted():
    tmp, store, evidence, g = world()
    scopes = V.discover(evidence)
    def boom(system, user):
        if "wrong-from-birth" in user:
            raise RuntimeError("timeout")
        return "not json at all"
    counts, findings, _ = V.run(store, g, scopes, complete=boom, sample_n=2, rng=random.Random(1))
    sampled = [f for f in findings if f.get("sample")]
    assert len(sampled) == 2 and all(f["verdict"] is None and f["reason"].startswith("judge error") for f in sampled)   # an error is not a vote
    drift = next(f for f in findings if f["result"] == "drift")
    assert drift["verdict"] == "UNCLEAR"                                                                              # unparseable → UNCLEAR
    assert g.flagged() == []
    # no scope mounted → every missing ref is unverifiable, never drift
    counts, findings, _ = V.run(store, g, {}, out=os.path.join(tmp, "r2"))
    assert counts["drift"] == 0 and counts["unverifiable"] == 10 and counts["unch"] == 7      # every ref, not just the wrong one
    # an accepted ref is neither drift nor evidence
    counts, findings, _ = V.run(store, g, scopes, accepted={"spreadsheet-export-retired": {"*": "the export lives in the accountant's own repo"}})
    f = next(f for f in findings if f["slug"] == "spreadsheet-export-retired")
    assert counts["accepted"] == 1 and f["result"] == "uncheckable_only" and f["details"][0]["status"] == "accepted"
    # a moved file is found by basename; the memory stays ok
    os.rename(os.path.join(evidence, "crumbledger", "configs", "thresholds.yml"), os.path.join(evidence, "crumbledger", "thresholds.yml"))
    counts, findings, _ = V.run(store, g, V.discover(evidence))
    d = next(f for f in findings if f["slug"] == "thresholds-live-in-yaml")["details"]
    assert any(x["status"] == "moved" and x["found_in"] == "crumbledger/thresholds.yml" for x in d)
    assert V.main(["--store", store, "--evidence", evidence, "--graph", os.path.join(tmp, "g.json"), "--out", os.path.join(tmp, "r3"), "--no-judge"]) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
