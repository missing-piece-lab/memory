"""gardener + review — a temp git repo of the example store, a flagged memory, proposals as branches, the guard, the cold
read (fake), the merge. Needs git on PATH. Run: python tests/test_gardener_review.py (or pytest)."""
import json, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import gardener as G, ingest as I, review as R  # noqa: E402
from engine.graph_mem import MemoryGraph  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example", "store")
SLUG = "spreadsheet-export-retired"
os.environ["EMBED_KIND"] = "fake"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def world():
    tmp = tempfile.mkdtemp(); repo = os.path.join(tmp, "store")
    shutil.copytree(EXAMPLE, repo)
    git(repo, "init", "-q", "-b", "main"); git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "the store")
    g = MemoryGraph(os.path.join(tmp, "g.json")); I.ingest(repo, g, do_embed=False)
    import time; time.sleep(0.01)
    run = g.start_run("report")
    details = [{"ref": "src/export_xlsx.py", "kind": "path", "status": "missing", "found_in": None}]
    fid = None
    for _ in range(2):
        fid = g.add_finding(run, SLUG, "drift", details); g.set_verdict(fid, "STALE", "the export module is gone")
    assert [f["slug"] for f in g.flagged()] == [SLUG]
    return tmp, repo, g


def good_draft(system, user):
    text = user.split("<file>\n", 1)[1].split("\n</file>", 1)[0]
    new = text.replace("writes one workbook a month", "wrote one workbook a month (was the live export; as of 2026-10-24 the module is gone)")
    return f"here you go\n<file>\n{new}\n</file>"


def test_gardener_draft_note_dry_and_ledger():
    tmp, repo, g = world(); out = os.path.join(tmp, "proposals")
    opened, log = G.run(repo, g, out, complete=good_draft, today="2026-10-24")
    assert opened == [f"gardener/{SLUG}-20261024"] and any("draft accepted" in l for l in log)
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and not git(repo, "status", "--porcelain")   # the checkout is untouched
    diff = git(repo, "diff", f"main...{opened[0]}")
    assert "as of 2026-10-24" in diff and "-name:" not in diff and "+++ b/" + SLUG + ".md" in diff
    body = open(os.path.join(out, f"gardener--{SLUG}-20261024.md")).read()
    assert "STALE in 2/2" in body and "`src/export_xlsx.py`" in body and "Your move" in body
    rows = [json.loads(l) for l in open(os.path.join(out, "proposals.jsonl"))]
    assert rows[0]["state"] == "open" and rows[0]["mode"] == "draft"
    opened2, log2 = G.run(repo, g, out, complete=good_draft, today="2026-10-25")                   # open proposal → skip
    assert opened2 == [] and any("open or was closed" in l for l in log2)
    # a draft that touches the frontmatter is rejected → note-only; the dry run opens nothing
    tmp, repo, g = world(); out = os.path.join(tmp, "p")
    bad = lambda s, u: good_draft(s, u).replace("name: " + SLUG, "name: renamed")
    opened, log = G.run(repo, g, out, complete=bad, today="2026-10-24")
    assert any("draft rejected (frontmatter changed)" in l for l in log) and json.loads(open(os.path.join(out, "proposals.jsonl")).readline())["mode"] == "note"
    diff = git(repo, "diff", f"main...{opened[0]}")
    assert "> Verifier 2026-10-24: judged **STALE**" in diff and diff.count("\n-") <= 1
    tmp, repo, g = world()
    opened, log = G.run(repo, g, os.path.join(tmp, "p"), complete=None, dry_run=True, today="2026-10-24")
    assert opened and "DRY RUN" in " ".join(log) and git(repo, "branch", "--list", "gardener/*") == ""
    # sane(): the 40% wall and an empty body
    old = open(os.path.join(repo, SLUG + ".md")).read(); fm, body = old.split("---\n", 2)[1], old.split("---\n", 2)[2]
    assert G.sane(old, f"---\n{fm}---\n" + "\n".join("new line" for _ in body.splitlines()) + "\n")[0] is False
    assert G.sane(old, f"---\n{fm}---\n")[0] is False and G.sane(old, old)[0] is True


def test_ledger_sync_merged_closed_withdrawn():
    tmp, repo, g = world(); out = os.path.join(tmp, "p")
    (branch,), _ = G.run(repo, g, out, complete=None, today="2026-10-24")
    assert G.Ledger(out).blocked(SLUG, "2026-10-24")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", branch)
    I.ingest(repo, g, do_embed=False)                                                     # the merged edit moves updated_at → the flag is void
    assert g.flagged() == [] and G.run(repo, g, out, today="2026-10-25")[0] == []
    assert [json.loads(l)["state"] for l in open(os.path.join(out, "proposals.jsonl"))] == ["merged"]
    tmp, repo, g = world(); out = os.path.join(tmp, "p")
    (branch,), _ = G.run(repo, g, out, today="2026-10-24"); git(repo, "branch", "-D", branch)
    G.run(repo, g, out, today="2026-10-25")
    assert json.loads(open(os.path.join(out, "proposals.jsonl")).readline())["state"] == "closed"
    assert G.Ledger(out).blocked(SLUG, "2026-11-20") and not G.Ledger(out).blocked(SLUG, "2026-11-25")    # 30 days of peace
    tmp, repo, g = world(); out = os.path.join(tmp, "p")
    G.run(repo, g, out, today="2026-10-24")
    notes = G.Ledger(out).sync(repo, "main", {}, "2026-10-25")
    assert notes and "withdrawn" in notes[0]


def test_review_guard_and_merge():
    tmp, repo, g = world(); out = os.path.join(tmp, "p")
    (branch,), _ = G.run(repo, g, out, complete=good_draft, today="2026-10-24")
    proposal = open(os.path.join(out, f"gardener--{SLUG}-20261024.md")).read()
    verdict, reason, path = R.run(branch, repo, proposal=proposal, complete=None, out=os.path.join(tmp, "r"))
    assert verdict == "HOLD" and "no reviewer" in reason
    verdict, reason, _ = R.run(branch, repo, proposal=proposal, complete=lambda s, u: "HOLD: the date is a guess", out=os.path.join(tmp, "r"))
    assert verdict == "HOLD" and reason == "the date is a guess" and git(repo, "rev-parse", "main") == git(repo, "rev-parse", "main~0")
    seen = {}
    def reviewer(system, user):
        seen["user"] = user; return "MERGE: the path is gone and the correction is dated"
    verdict, reason, path = R.run(branch, repo, proposal=proposal, complete=reviewer, out=os.path.join(tmp, "r"))
    assert verdict == "MERGE" and "as of 2026-10-24" in seen["user"] and "STALE in 2/2" in seen["user"]
    assert "as of 2026-10-24" in open(os.path.join(repo, SLUG + ".md")).read() and open(path).read().startswith(f"# {branch} · MERGE")
    # the guard: index, frontmatter, type user, the human's name, >40%, two files, a new memory (fact vs identity)
    def branch_with(name, edits):
        b = f"t/{name}"; git(repo, "checkout", "-q", "-b", b)
        for fn, text in edits.items():
            with open(os.path.join(repo, fn), "a" if text else "w") as fh:
                fh.write(text)
        git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", name); git(repo, "checkout", "-q", "main"); return b
    def held(name, edits, **kw):
        return R.run(branch_with(name, edits), repo, complete=lambda s, u: "MERGE: fine", out=os.path.join(tmp, "r"), **kw)[1]
    assert "touches the index" in held("idx", {"MEMORY.md": "- [X](holiday-multiplier.md) — again\n"})
    assert "touches 2 files" in held("two", {"holiday-multiplier.md": "\nmore\n", "stock-in-grams.md": "\nmore\n"})
    assert "type user" in held("user", {"owner-reads-plain-tables.md": "\nThe owner also likes the list stapled.\n"})
    assert "mentions Mara" in held("human", {"holiday-multiplier.md": "\nMara said 1.6 is right.\n"}, human="Mara")
    assert "> 40%" in held("big", {"holiday-multiplier.md": "\n" + "\n".join("line %d" % i for i in range(12)) + "\n"})
    fm_edit = open(os.path.join(repo, "holiday-multiplier.md")).read().replace("type: project", "type: reference")
    git(repo, "checkout", "-q", "-b", "t/fm"); open(os.path.join(repo, "holiday-multiplier.md"), "w").write(fm_edit)
    git(repo, "commit", "-q", "-am", "fm"); git(repo, "checkout", "-q", "main")
    assert "changes frontmatter" in R.run("t/fm", repo, complete=lambda s, u: "MERGE: ok", out=os.path.join(tmp, "r"))[1]
    new_fact = "---\nname: oven-temps\ndescription: \"oven temperatures per product\"\nmetadata:\n  type: reference\n  project: crumbledger\n---\nThe ovens run at 230 for bread.\n"
    v, r, _ = R.run(branch_with("newfact", {"oven-temps.md": new_fact}), repo, complete=lambda s, u: "MERGE: plain fact", out=os.path.join(tmp, "r"), dry_run=True)
    assert v == "MERGE"
    assert "a new user memory" in held("newuser", {"owner-mood.md": new_fact.replace("type: reference", "type: user").replace("oven-temps", "owner-mood")})
    assert "would supersede" in held("sup", {"oven-temps2.md": new_fact.replace("oven-temps", "oven-temps2").replace("---\nThe", "supersedes: [oven-temps]\n---\nThe")})
    assert "identity" in held("ident", {"we-two.md": new_fact.replace("oven-temps", "we-two").replace("project: crumbledger", "project: identity")})
    # a merge needs a clean checkout on base
    git(repo, "checkout", "-q", "-b", "elsewhere")
    assert "could not merge" in R.run("t/newfact", repo, complete=lambda s, u: "MERGE: ok", out=os.path.join(tmp, "r"))[1]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
