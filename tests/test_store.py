"""store + lint — frontmatter parsing, reference extraction, the index, the lint. Temp dirs, no network.
Run: python tests/test_store.py (or pytest)."""
import os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import lint as L, store as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example", "store")


def test_parse_and_split():
    text = '---\nname: a-b\ndescription: "x: y"\nmetadata:\n  type: project\n  project: p\n---\n\nbody `src/a.py`\n'
    fm, body = S.parse(text)
    assert fm["name"] == "a-b" and fm["metadata"]["type"] == "project" and body.startswith("body")
    block, rest = S.split(text)
    assert block.startswith("---\n") and block.endswith("---\n") and rest.startswith("\nbody")
    assert S.parse("no frontmatter here") == ({}, "no frontmatter here")
    for bad in ("---\n- a list\n---\nbody", "---\nname: [unclosed\n---\nbody", "---\nmetadata: 3\n---\nbody"):
        try:
            S.parse(bad); assert False, bad
        except S.FrontmatterError:
            pass


def test_extract_refs():
    body = ("See `src/reorder.py` and `point_for`, the flag `--print`, the symbol `csv.DictReader`, a template `/forms/{id}.json`, "
            "a URL https://example.test/x.py, `configs/thresholds.yml`, a sentence `with spaces/in.it`, and plain scripts/nightly_count.sh.\n"
            "```\ncode `fenced/ignored.py`\n```")
    refs = S.extract_refs(body)
    assert "src/reorder.py" in refs and "configs/thresholds.yml" in refs and "scripts/nightly_count.sh" in refs
    assert "--print" in refs and "csv.DictReader" in refs
    assert "point_for" not in refs                       # a bare identifier is not a reference
    assert not any("{" in r or "example.test" in r or "fenced" in r or " " in r for r in refs)
    assert S.links_of("a [[one]] and [[two]] and `[[not-a-link]]` ```[[nor-this]]```") == ["one", "two"]


def test_load_example_and_index():
    memories, skipped = S.load(EXAMPLE)
    assert len(memories) == 10 and not skipped
    by = {m.slug: m for m in memories}
    assert by["flour-reorder-point"].type == "project" and by["flour-reorder-point"].project == "crumbledger"
    assert by["flour-reorder-point"].title == "Flour reorder point"          # the title comes from the index line
    assert "thresholds-live-in-yaml" in by["flour-reorder-point"].links
    assert "src/export_xlsx.py" in by["spreadsheet-export-retired"].refs
    idx = S.read_index(EXAMPLE)
    assert len(idx) == 10 and idx["stock-in-grams"][0] == "Stock is grams"


def test_load_skips_one_bad_file():
    tmp = tempfile.mkdtemp()
    shutil.copytree(EXAMPLE, tmp, dirs_exist_ok=True)
    open(os.path.join(tmp, "broken.md"), "w").write("---\ndescription: a: b: c\n  bad\n---\nbody\n")
    memories, skipped = S.load(tmp)
    assert len(memories) == 10 and skipped and skipped[0][0] == "broken.md"


def test_lint_clean_and_findings():
    assert L.lint(EXAMPLE) == []
    tmp = tempfile.mkdtemp()
    shutil.copytree(EXAMPLE, tmp, dirs_exist_ok=True)
    with open(os.path.join(tmp, "MEMORY.md"), "a") as fh:
        fh.write("- [Ghost](ghost.md) — a file that is not there\n"
                 "- [Stamped](holiday-multiplier.md) — DONE 2026-10-01, LIVE since 9-19 at 03:30 UTC\n")
    open(os.path.join(tmp, "unindexed.md"), "w").write("---\nname: wrong-name\ndescription: \"\"\nmetadata:\n  type: nope\n---\nbody\n")
    kinds = {}
    for kind, where, msg in L.lint(tmp):
        kinds.setdefault(kind, []).append(msg)
    assert "missing-file" in kinds and "duplicate" in kinds and "unindexed" in kinds
    assert any("DONE" in m and "LIVE" in m for m in kinds["state-stamp"])
    assert kinds["date-stamp"]
    fm = " ".join(kinds["frontmatter"])
    assert "wrong-name" in fm and "no description" in fm and "'nope'" in fm and "metadata.project" in fm
    assert L.main(["--store", tmp]) == 1 and L.main(["--store", EXAMPLE]) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
