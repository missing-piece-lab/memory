#!/usr/bin/env python3
"""verify — the nightly check of every memory's claims against its evidence scope. Report-only: it never edits a memory.

  python -m engine.verify --store DIR --evidence DIR [--graph graph.json] [--out reports] [--accepted accepted.yml]
                          [--judge-max 10] [--sample 3] [--no-judge]

Evidence = `--evidence DIR` holding one tree per scope (`DIR/<project>/` = the repo or directory a memory's
`metadata.project` names), or `--scope name=path` repeated. Two tiers:

Tier 1, deterministic. Every reference the body asserts (engine.store.extract_refs) is classified and checked in the
memory's own scope first: a path exists (`ok`) · its basename exists elsewhere (`moved`) · it is gone (`missing`); a
dotted symbol greps on a word boundary across code files (`ok`/`missing`); flags, URLs, templates, absolute paths, data
files are `uncheckable`. An `ok` reference is pinned to the git blob of the file it resolved to; a different blob next
night is `changed`. A `missing` reference whose scope is not mounted here is `unverifiable` — an evidence gap, never
drift. A moved reference is re-anchored to where the file now is and reported as `moved` under its own heading — drift-
lite: not judged, not counted as ok; the memory needs its path fixed. Per memory: any missing → drift; else any changed →
changed; else any moved → moved; else any ok → ok; else uncheckable_only.

Tier 2, a model judge, optional (MODEL_* env; skipped cleanly without). It reads drift and changed memories only, plus a
few random `ok` ones each night (a memory wrong from birth whose files never change is otherwise never re-read), with
the body, the reference results and the current content or diff, and answers CONFIRMED / STALE / CONTRADICTED /
UNCLEAR. A judge error is not a verdict. CONFIRMED re-anchors a changed reference. Verdicts accumulate on the finding
rows; a memory is flagged when 2 of its last 3 post-edit verdicts are STALE or CONTRADICTED (graph.flagged()).
"""
import argparse, hashlib, os, random, re, subprocess, sys
from datetime import datetime, timezone

from . import llm, store as S
from .config import load_env
from .graph import open_graph

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
CODE_EXT = {"py", "sql", "js", "ts", "tsx", "json", "yml", "yaml", "sh", "md", "cfg", "ini", "toml"}
DATA_EXT = {"png", "jpg", "jpeg", "gif", "svg", "ico", "mp4", "mp3", "wav", "pdf", "csv", "xlsx", "xls", "parquet",
            "zip", "gz", "tar", "bin", "exe", "dll", "so", "pt", "pth", "safetensors", "db", "sqlite"}
FILENAME_TAILS = {"log", "conf", "txt", "out", "err", "pid", "lock", "bak", "tmp", "old", "html", "htm", "css", "xml",
                  "jsonl", "tsv", "service", "timer", "socket", "example", "template", "ps1", "bat", "cmd"}
THIRD_PARTY = {"site-packages", "dist-packages", "node_modules", "venv"}
FILENAME_RE = re.compile(rf"^[\w.-]+\.(?:{S.EXT})$")
SYMBOL_RE = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_][\w.]*$")
MAX_FILE = 2 * 1024 * 1024

SYSTEM = ("You audit an engineering memory store. Each memory asserts facts about code (files, flags, functions). A deterministic "
          "checker has already resolved the memory's references against the memory's own evidence scope and reports them below. "
          "Decide whether the MEMORY is still true. Only the memory's own scope is evidence: never draw conclusions from another "
          "tree. If the scope is not mounted, or a reference is marked unverifiable, say UNCLEAR. Prefer UNCLEAR over guessing.")
INSTRUCTIONS = ('Respond with STRICT JSON only: {"verdict":"CONFIRMED|STALE|CONTRADICTED|UNCLEAR","reason":"one sentence"}. '
                "CONFIRMED = still true (a file moved or changed but the claim holds). STALE = the asserted thing is gone and the "
                "fact is outdated. CONTRADICTED = the evidence shows something that conflicts with the fact. UNCLEAR = not enough evidence.")


class Scope:
    """One evidence tree, walked once."""
    def __init__(self, name, root):
        self.name, self.root, self.basenames, self.code_files = name, root, {}, []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                self.basenames.setdefault(fn, []).append(rel)
                if fn.rsplit(".", 1)[-1].lower() in CODE_EXT:
                    self.code_files.append(rel)

    def exists(self, rel):
        return os.path.isfile(os.path.join(self.root, rel)) or os.path.isdir(os.path.join(self.root, rel))

    def blob_sha(self, rel):
        """The git blob id of the file as it is on disk (hashlib; no git needed) — None for a directory or unreadable."""
        try:
            data = open(os.path.join(self.root, rel), "rb").read()
        except (OSError, IsADirectoryError):
            return None
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    def old_blob(self, sha):
        """The content behind an old anchor, if the scope is a git repo that still holds that object."""
        try:
            r = subprocess.run(["git", "-C", self.root, "cat-file", "-p", sha], capture_output=True, timeout=10)
            return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
        except Exception:
            return None

    def grep_symbol(self, ident):
        pat = re.compile(rb"\b" + re.escape(ident.encode()) + rb"\b")
        for rel in self.code_files:
            if rel.rsplit(".", 1)[-1].lower() in ("md", "txt"):
                continue                                  # prose is not symbol evidence
            full = os.path.join(self.root, rel)
            try:
                if os.path.getsize(full) <= MAX_FILE and pat.search(open(full, "rb").read()):
                    return rel
            except OSError:
                continue
        return None


def discover(evidence=None, scopes=()):
    found = {}
    if evidence and os.path.isdir(evidence):
        for name in sorted(os.listdir(evidence)):
            if not name.startswith(".") and os.path.isdir(os.path.join(evidence, name)):
                found[name] = Scope(name, os.path.join(evidence, name))
    for spec in scopes:
        name, _, path = spec.partition("=")
        if os.path.isdir(path):
            found[name] = Scope(name, path)
        else:
            print(f"verify: scope {name!r}: {path!r} is not a directory — treated as not mounted (its memories are unverifiable)", file=sys.stderr)
    return found


def classify(ref):
    """(kind, payload): payload is the checkable path or symbol, None when the kind is uncheckable."""
    r = ref.strip().strip("`").strip()
    if not r:
        return "unknown", None
    if os.path.basename(r) == S.INDEX_FILE:
        return "memory_index", None
    if any(c in r for c in "<>*{}@"):
        return "template", None
    if r.startswith("-"):
        return "flag", None
    low = r.lower()
    if low.startswith(("http", "www.")) or any(x in low for x in (".com", ".org", ".net", ".io/")):
        return "url", None
    if "\\" in r or re.match(r"^[A-Za-z]:", r):
        return "windows", None
    if any(seg in THIRD_PARTY for seg in r.split("/")):
        return "third_party", None
    if r.startswith(("/", "~/")):
        return "abs", None                                # a host path, not a repo path: uncheckable by construction
    p = re.sub(r":\d+(?::\d+)?$", "", r)                    # drop a file.py:LINE suffix
    if ("/" in p and "." in p) or FILENAME_RE.match(p):
        if os.path.basename(p).rsplit(".", 1)[-1].lower() in DATA_EXT:
            return "data_artifact", None
        if any(seg.startswith(".") for seg in p.split("/")):
            return "gitignored", None
        return "path", p
    if SYMBOL_RE.match(r):
        return ("filename", None) if r.rsplit(".", 1)[-1].lower() in FILENAME_TAILS else ("symbol", r)
    return "unknown", None


def order(project, scopes):
    return [project] + [n for n in scopes if n != project] if project in scopes else list(scopes)


def check_ref(ref, project, scopes, store):
    kind, payload = classify(ref)
    if kind not in ("path", "symbol"):
        return {"ref": ref, "kind": kind, "status": "uncheckable", "found_in": None}
    names = order(project, scopes)
    if kind == "path":
        base = os.path.basename(payload)
        if base.endswith(".md") and "/" not in payload and os.path.isfile(os.path.join(store, base)):
            return {"ref": ref, "kind": "memory_ref", "status": "ok", "found_in": f"store/{base}"}
        head, _, tail = payload.partition("/")
        if head in scopes and tail and scopes[head].exists(tail):
            return {"ref": ref, "kind": kind, "status": "ok", "found_in": f"{head}/{tail}"}
        for n in names:
            if scopes[n].exists(payload):
                return {"ref": ref, "kind": kind, "status": "ok", "found_in": f"{n}/{payload}"}
        for n in names:
            hits = scopes[n].basenames.get(base)
            if hits:
                return {"ref": ref, "kind": kind, "status": "moved", "found_in": f"{n}/{sorted(hits)[0]}"}
        return {"ref": ref, "kind": kind, "status": "missing", "found_in": None}
    ident = payload.split(".")[-1]
    for n in names:
        hit = scopes[n].grep_symbol(ident)
        if hit:
            return {"ref": ref, "kind": kind, "status": "ok", "found_in": f"{n}/{hit}"}
    return {"ref": ref, "kind": kind, "status": "missing", "found_in": None}


def apply_accepted(slug, details, accepted):
    rules = accepted.get(slug) or {}
    n = 0
    for d in details:
        reason = (rules.get(d["ref"]) or rules.get("*")) if d["status"] == "missing" else (rules.get(d["ref"]) if d["status"] == "moved" else None)
        if reason:
            d["status"], d["found_in"] = "accepted", f"accepted: {reason}"; n += 1
    return n


def apply_coverage(project, details, scopes):
    n = 0
    for d in details:
        if d["status"] == "missing" and project not in scopes:
            d["status"], d["found_in"] = "unverifiable", f"scope {project!r} is not mounted here"; n += 1
    return n


def anchor(graph, slug, updated_at, details, scopes):
    """Pin every ok path/symbol to the blob it resolved to. A new ref, a relocated one, or a memory edited since the pin →
    (re)set. Same blob → ok. Different blob → `changed` (the file the memory relies on was edited; the judge decides)."""
    old = graph.anchors(slug)
    changed = 0
    for d in details:
        if d["status"] not in ("ok", "moved") or d["kind"] not in ("path", "symbol"):
            continue
        name, _, rel = d["found_in"].partition("/")
        sha = scopes[name].blob_sha(rel) if name in scopes else None
        if not sha:
            continue
        prev = old.get(d["ref"])
        if d["status"] == "moved":                              # re-anchored where it now is; never compared, never `changed`
            graph.set_anchor(slug, d["ref"], d["found_in"], sha); d["anchor"] = "moved"; continue
        if prev is None or prev[2] != d["found_in"] or (updated_at and prev[1] and updated_at > prev[1]):
            graph.set_anchor(slug, d["ref"], d["found_in"], sha); d["anchor"] = "set"
        elif prev[0] == sha:
            d["anchor"] = "same"
        else:
            d.update(status="changed", anchor="changed", old_sha=prev[0], new_sha=sha, scope=name, rel=rel,
                     found_in=f"{d['found_in']} (blob {prev[0][:7]}→{sha[:7]})"); changed += 1
    return changed


def rollup(details):
    st = {d["status"] for d in details}
    return ("drift" if "missing" in st else "changed" if "changed" in st else "moved" if "moved" in st
            else "ok" if "ok" in st else "uncheckable_only")


def evidence_text(f, scopes):
    scope = scopes.get(f["project"])
    lines = [f"MEMORY (slug={f['slug']}, scope={f['project']}):", f["body"].strip(), "",
             f"SCOPES MOUNTED: {', '.join(sorted(scopes)) or 'none'}",
             f"THIS MEMORY'S SCOPE: {'mounted — its files are real evidence' if scope else 'NOT mounted — no evidence for its files exists here'}",
             "", "REFERENCE CHECK:"]
    for d in f["details"]:
        line = f"- `{d['ref']}` [{d['kind']}] -> {d['status']}" + (f" ({d['found_in']})" if d.get("found_in") and d["status"] != "ok" else "")
        if d["status"] == "missing" and scope:
            parts = classify(d["ref"])[1].split("/")[:-1]
            while parts and not os.path.isdir(os.path.join(scope.root, *parts)):
                parts.pop()
            try:
                line += f"\n    nearest existing dir in scope: {'/'.join(parts) or '.'}/ contains: {', '.join(sorted(os.listdir(os.path.join(scope.root, *parts)))[:25])}"
            except OSError:
                pass
        elif d["status"] == "changed":
            old = scopes[d["scope"]].old_blob(d["old_sha"])
            new = open(os.path.join(scopes[d["scope"]].root, d["rel"]), encoding="utf-8", errors="replace").read()
            if old is not None:
                import difflib
                diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "before", "after", lineterm="", n=2))[:150]
                line += "\n    diff:\n" + "\n".join("    " + l for l in diff)
            else:
                line += "\n    (old content unavailable) current content:\n" + "\n".join("    " + l for l in new.splitlines()[:40])
        elif d["status"] == "ok" and f.get("sample") and d["kind"] in ("path", "symbol"):
            name, _, rel = d["found_in"].partition("/")
            try:
                text = open(os.path.join(scopes[name].root, rel), encoding="utf-8", errors="replace").read().splitlines()
                line += "\n    current content:\n" + "\n".join(f"    {n+1:4d}  {l}" for n, l in enumerate(text[:40]))
            except OSError:
                pass
        lines.append(line)
    if f.get("sample"):
        lines += ["", "NOTE: every reference of this memory checked out. It was picked at random tonight as a wrong-from-birth check: "
                  "read the claim against the content above. CONFIRMED unless the content shows the memory was never right."]
    return "\n".join(lines)


def judge(graph, findings, scopes, complete, cap):
    n = 0
    for f in findings[:cap]:
        try:
            obj = llm.parse_json(complete(SYSTEM, evidence_text(f, scopes) + "\n\n" + INSTRUCTIONS)) or {}
            verdict = str(obj.get("verdict", "UNCLEAR")).upper()
            verdict = verdict if verdict in ("CONFIRMED", "STALE", "CONTRADICTED", "UNCLEAR") else "UNCLEAR"
            reason = str(obj.get("reason", ""))[:1000]
        except Exception as e:                          # a judge error is not a verdict (an UNCLEAR here would count as a vote)
            f["verdict"], f["reason"] = None, f"judge error: {type(e).__name__}"
            graph.set_verdict(f["finding_id"], None, f["reason"]); continue
        f["verdict"], f["reason"] = verdict, ("[sample] " if f.get("sample") else "") + reason
        graph.set_verdict(f["finding_id"], verdict, f["reason"]); n += 1
        if verdict == "CONFIRMED":
            for d in f["details"]:
                if d.get("anchor") == "changed":
                    graph.set_anchor(f["slug"], d["ref"], d["found_in"].split(" (")[0], d["new_sha"])
    return n


def report(ts, scopes, counts, findings, judged):
    L = [f"# Verifier report — {ts}", "", f"- scopes: {', '.join(sorted(scopes)) or 'none'}",
         f"- memories checked: {counts['nodes']} (ok {counts['ok']}, drift {counts['drift']}, changed {counts['changed']}, moved {counts['moved']}, "
         f"uncheckable-only {counts['unch']})",
         f"- references: {counts['refs']} · accepted {counts['accepted']} · unverifiable {counts['unverifiable']} · judged {counts['judged']}"
         + ("" if judged else " (no model configured — Tier 2 skipped)"), ""]
    for title, pick in (("Drift", lambda f: f["result"] == "drift"), ("Changed", lambda f: f["result"] == "changed"),
                        ("Sampled", lambda f: f.get("sample"))):
        rows = [f for f in findings if pick(f)]
        L += [f"## {title} — {len(rows)}", ""]
        for f in rows:
            L.append(f"### `{f['slug']}` [{f['project']}]" + (f" — **{f['verdict']}**: {f['reason']}" if f.get("verdict") else ""))
            L += ["", "| ref | kind | status | where |", "|---|---|---|---|"]
            L += [f"| `{d['ref']}` | {d['kind']} | {d['status']} | {d.get('found_in') or ''} |" for d in f["details"]] + [""]
        if not rows:
            L += ["_none_", ""]
    for title, st in (("Moved (drift-lite: re-anchored where the file now is, not judged, not ok — fix the path in the memory)", "moved"),
                      ("Unverifiable (evidence gap: mount the scope, push the work, or accept)", "unverifiable"), ("Accepted", "accepted")):
        rows = [(f["slug"], d) for f in findings for d in f["details"] if d["status"] == st]
        if rows:
            L += [f"## {title} — {len(rows)}", ""] + [f"- `{s}`: `{d['ref']}` — {d['found_in']}" for s, d in rows] + [""]
    return "\n".join(L) + "\n"


def run(store, graph, scopes, out=None, accepted=None, complete=None, judge_max=10, sample_n=3, rng=random):
    if not graph.count_active():
        raise SystemExit("verify: nothing ingested yet: run ingest first (python -m engine.ingest --store DIR)")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = graph.start_run("report")
    counts = dict(nodes=0, refs=0, ok=0, drift=0, changed=0, moved=0, unch=0, accepted=0, unverifiable=0, judged=0)
    findings = []
    for n in graph.active_with_refs():
        details = [check_ref(r, n["project"], scopes, store) for r in n["refs"]]
        counts["accepted"] += apply_accepted(n["slug"], details, accepted or {})
        counts["unverifiable"] += apply_coverage(n["project"], details, scopes)
        anchor(graph, n["slug"], n["updated_at"], details, scopes)
        result = rollup(details)
        counts["nodes"] += 1; counts["refs"] += len(details)
        counts[{"ok": "ok", "drift": "drift", "changed": "changed", "moved": "moved", "uncheckable_only": "unch"}[result]] += 1
        fid = graph.add_finding(run_id, n["slug"], result, details)
        findings.append({**n, "finding_id": fid, "result": result, "details": details, "verdict": None, "reason": None})
    judged = bool(complete)
    if complete:
        todo = [f for f in findings if f["result"] == "drift"] + [f for f in findings if f["result"] == "changed"]
        counts["judged"] += judge(graph, todo, scopes, complete, judge_max)
        pool = [f for f in findings if f["result"] == "ok" and f["project"] in scopes]
        sample = rng.sample(pool, min(sample_n, len(pool))) if sample_n > 0 else []
        for f in sample:
            f["sample"] = True
        counts["judged"] += judge(graph, sample, scopes, complete, len(sample))
    graph.finish_run(run_id, counts)
    graph.save()
    text = report(ts, scopes, counts, findings, judged)
    path = None
    if out:
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, f"verifier-{ts}.md")
        open(path, "w", encoding="utf-8").write(text)
    return counts, findings, path


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", required=True); ap.add_argument("--evidence"); ap.add_argument("--scope", action="append", default=[])
    ap.add_argument("--graph"); ap.add_argument("--out", default="reports"); ap.add_argument("--accepted")
    ap.add_argument("--judge-max", type=int, default=10); ap.add_argument("--sample", type=int, default=3); ap.add_argument("--no-judge", action="store_true")
    a = ap.parse_args(argv)
    scopes = discover(a.evidence, a.scope)
    accepted = {}
    if a.accepted and os.path.exists(a.accepted):
        import yaml
        accepted = {k: (v or {}) for k, v in (yaml.safe_load(open(a.accepted)) or {}).items()}
    complete = None
    if not a.no_judge and llm.available():
        complete = lambda s, u: llm.complete(s, u, model=llm.model_for("verifier"), max_tokens=400)
    elif not a.no_judge:
        print("verify: no MODEL_API_KEY / MODEL_NAME — Tier 2 skipped, Tier 1 runs")
    g = open_graph(a.graph)
    try:
        counts, _, path = run(a.store, g, scopes, a.out, accepted, complete, a.judge_max, a.sample)
    finally:
        g.close()
    print(f"verify: {counts['nodes']} memories, {counts['refs']} refs — ok {counts['ok']}, drift {counts['drift']}, changed {counts['changed']}, moved {counts['moved']}, "
          f"uncheckable-only {counts['unch']}, unverifiable {counts['unverifiable']}, judged {counts['judged']} → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
