#!/usr/bin/env python3
"""lint — the index rule: state is observed, never written into the index.

  python -m engine.lint --store DIR         exit 0 clean, 1 findings (printed)

An index line is a pointer: a title, a file, one hook that says what the memory is FOR. It may not say what state a
thing is in — an uppercase LIVE / DONE / ARMED / PENDING in a hook is a sentence pretending to be an observation, and a
date or time in a hook is a status report that will be wrong by next week. State comes from probes (a CLAIMS.yml and
the `claims` instrument, see docs/DESIGN.md); the index carries none. Also checked: every index line names a file that
exists, every memory has one index line, no slug twice, lines under 200 characters, frontmatter complete
(name = filename, a description, a known type, a project).
"""
import argparse, os, re, sys

from . import store as S

STATE_WORDS = re.compile(r"\b(LIVE|DONE|BUILT|ARMED|UNARMED|PENDING|PARKED|BLOCKED|STAGED|INSTALLED|IN PROGRESS|NOT STARTED|"
                         r"COMPLETE|SHIPPED|RETIRED|TAKEN DOWN|SUPERSEDED|MERGED|DEPLOYED|RUNNING|DOWN|UP)\b")
STAMP_RE = re.compile(r"\b(20\d\d-\d\d-\d\d|\d{1,2}-\d{2}\b(?![\d-])|\d{1,2}:\d{2}\s*(?:UTC|Z)?\b)")
MAXLEN = 200


def lint(store):
    """A list of (kind, where, message). Empty = clean."""
    out = []
    idx_path = os.path.join(store, S.INDEX_FILE)
    if not os.path.exists(idx_path):
        return [("index", S.INDEX_FILE, "no index file")]
    seen = {}
    files = {f[:-3] for f in os.listdir(store) if f.endswith(".md") and f != S.INDEX_FILE}
    for n, line in enumerate(open(idx_path, encoding="utf-8").read().split("\n"), 1):
        m = S.INDEX_LINE.match(line)
        if not m:
            continue
        slug, hook = m.group("slug"), m.group("hook")
        if slug in seen:
            out.append(("duplicate", f"{S.INDEX_FILE}:{n}", f"{slug} already indexed at line {seen[slug]}"))
        seen[slug] = n
        if slug not in files:
            out.append(("missing-file", f"{S.INDEX_FILE}:{n}", f"{slug}.md does not exist"))
        words = sorted(set(STATE_WORDS.findall(hook)))
        if words:
            out.append(("state-stamp", f"{S.INDEX_FILE}:{n}", f"{slug}: {', '.join(words)} — state belongs to a probe, not the index"))
        if STAMP_RE.search(hook):
            out.append(("date-stamp", f"{S.INDEX_FILE}:{n}", f"{slug}: a date or time in the hook"))
        if len(line) > MAXLEN:
            out.append(("long-line", f"{S.INDEX_FILE}:{n}", f"{slug}: {len(line)} chars (max {MAXLEN})"))
    for slug in sorted(files - set(seen)):
        out.append(("unindexed", f"{slug}.md", "no index line"))
    memories, skipped = S.load(store)
    for fname, why in skipped:
        out.append(("frontmatter", fname, why))
    for m in memories:
        name = str(m.frontmatter.get("name") or "")
        if name != m.slug:
            out.append(("frontmatter", f"{m.slug}.md", f"name is {name!r}, the file is {m.slug}"))
        if not m.description.strip():
            out.append(("frontmatter", f"{m.slug}.md", "no description"))
        if m.type not in S.TYPES:
            out.append(("frontmatter", f"{m.slug}.md", f"metadata.type {m.type!r} is not one of {', '.join(S.TYPES)}"))
        if not m.project:
            out.append(("frontmatter", f"{m.slug}.md", "no metadata.project (the evidence scope)"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", required=True)
    a = ap.parse_args(argv)
    findings = lint(a.store)
    for kind, where, msg in findings:
        print(f"{kind:13} {where}: {msg}")
    print(f"lint: {'clean' if not findings else str(len(findings)) + ' finding(s)'}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
