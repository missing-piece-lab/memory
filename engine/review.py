#!/usr/bin/env python3
"""review — the lane a Gardener branch goes through: a deterministic guard, then a cold model read, then a merge or a hold.

  python -m engine.review <branch> --repo DIR [--base main] [--out reviews] [--human NAME] [--identity-scope identity]
                                   [--proposal FILE] [--dry-run]            exit 0 MERGE · 2 HOLD · 1 could not read

The GUARD holds, with no model involved, anything a human must see: more than one file; a file that is not a memory at
the store root; the index; a memory of type `user` or in the identity scope; any frontmatter line; any line that
mentions the human by name; more than 40% of the body; a new memory that is not plain project/reference fact, or
that would supersede another. The guard is code, not a prompt, so a persuasive diff cannot talk its way past it.

The REVIEWER is a second mind that sees the proposal's evidence and the diff and nothing else — no history of its own
verdicts, nothing of the author's reasoning. It answers one line: `MERGE: <reason>` or `HOLD: <reason>`. Only
fact-class changes (paths, names, dates, status) that leave the memory truer merge; anything about intent, opinion or
the people is held. No model configured → everything is held with that reason.

MERGE merges the branch into `--base` in the checkout (`--no-ff`; the checkout must be on base and clean), writes
`<out>/<date>-<branch>.md`; HOLD writes the same file with the reason and leaves the branch where it is.
"""
import argparse, datetime as dt, os, re, subprocess, sys

from . import llm, store as S
from .config import load_env

MAX_CHANGE = 0.40
FRONTMATTER_LINE = re.compile(r"^[+-](---$|name:|description:|metadata:|supersedes:|\s+(type|project|origin|session|modified|box|model|harness):)")
PROMPT = """You are the reviewer on a memory store's review lane: a second mind, not the author. The nightly verifier judged a memory
STALE or CONTRADICTED against the code; the branch proposes a minimal edit or a dated note. Decide MERGE or HOLD. MERGE only if the
evidence in the proposal supports the edit, the edit changes facts (paths, names, dates, status) and nothing about intent, opinion or
the people involved, and the memory would be truer afterwards. Otherwise HOLD. Answer with exactly one line: MERGE: <reason> or HOLD: <reason>.

PROPOSAL
{proposal}

DIFF
{diff}
"""


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def changed_files(repo, base, branch):
    out = sh(["git", "diff", "--name-status", f"{base}...{branch}"], cwd=repo)
    return [(l.split("\t")[0][:1], l.split("\t")[-1]) for l in out.splitlines() if l.strip()]


def frontmatter_of(repo, base, name):
    try:
        fm, body = S.parse(sh(["git", "show", f"{base}:{name}"], cwd=repo))
    except Exception:
        return {}, 1
    meta = fm.get("metadata") or {}
    return {"type": meta.get("type") or fm.get("type"), "project": meta.get("project") or fm.get("project")}, max(1, len(body.splitlines()))


def new_file_frontmatter(diff):
    fm = {}
    for l in diff.splitlines():
        m = re.match(r"^\+\s*(type|project):\s*(\S+)", l)
        if m:
            fm.setdefault(m.group(1), m.group(2).strip("\"'"))
    return fm


def guard(files, diff, repo, base, human=None, identity_scope="identity"):
    """None when the change is fact-class; else the reason to hold it for the human."""
    if len(files) != 1:
        return f"touches {len(files)} files"
    status, name = files[0]
    if not name.endswith(".md") or "/" in name:
        return f"not a memory file: {name}"
    if name == S.INDEX_FILE:
        return "touches the index"
    changed = [l for l in diff.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    human_re = re.compile(r"\b" + re.escape(human) + r"\b", re.I) if human else None
    if status == "A":
        fm = new_file_frontmatter(diff)
        if re.search(r"^\+\s*supersedes:", diff, re.M):
            return "a new memory that would supersede another"
        if fm.get("type") in ("project", "reference") and fm.get("project") != identity_scope and not (human_re and any(human_re.search(l) for l in changed)):
            return None
        return f"a new {fm.get('type', '?')} memory in scope {fm.get('project', '?')}"
    fm, body_lines = frontmatter_of(repo, base, name)
    if fm.get("type") == "user" or fm.get("project") == identity_scope:
        return f"{name} is type user / identity scope"
    if any(FRONTMATTER_LINE.match(l) for l in changed):
        return "changes frontmatter"
    if human_re and any(human_re.search(l) for l in changed):
        return f"changes a line that mentions {human}"
    if len(changed) / body_lines > MAX_CHANGE:
        return f"changes {len(changed)} lines of a {body_lines}-line body (> {int(MAX_CHANGE * 100)}%)"
    return None


def cold_read(complete, proposal, diff):
    try:
        text = complete("You review changes to a memory store. Answer in one line.", PROMPT.format(proposal=proposal[:6000], diff=diff[:8000]))
    except Exception as e:
        return "HOLD", f"reviewer error: {type(e).__name__}"
    m = re.search(r"\b(MERGE|HOLD)\s*:\s*(.+)", text or "")
    return (m.group(1), m.group(2).strip()[:300]) if m else ("HOLD", f"reviewer answered unclearly: {(text or '')[:120]}")


def run(branch, repo, base="main", out="reviews", human=None, identity_scope="identity", proposal="", complete=None, dry_run=False, today=None):
    today = today or dt.date.today().isoformat()
    files = changed_files(repo, base, branch)
    diff = sh(["git", "diff", f"{base}...{branch}"], cwd=repo)
    why = guard(files, diff, repo, base, human, identity_scope)
    trace = [f"files: {', '.join(n for _, n in files) or 'none'}"]
    if why:
        verdict, reason = "HOLD", f"guard: {why}"
    elif not complete:
        verdict, reason = "HOLD", "no reviewer configured (MODEL_API_KEY / MODEL_NAME) — held for the human"
    else:
        verdict, reason = cold_read(complete, proposal, diff)
        trace.append("cold read done")
    merged = False
    if verdict == "MERGE" and not dry_run:
        head = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
        dirty = sh(["git", "status", "--porcelain"], cwd=repo).strip()
        if head != base or dirty:
            verdict, reason = "HOLD", f"could not merge: checkout is on {head!r}{' and dirty' if dirty else ''}; needs to be clean on {base}"
        else:
            sh(["git", "-c", "user.name=review-lane", "-c", "user.email=review@localhost", "merge", "--no-ff", "-q", "-m",
                f"review lane: merge {branch} — {reason}", branch], cwd=repo)
            merged = True
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{today}-{branch.replace('/', '--')}.md")
    open(path, "w", encoding="utf-8").write("\n".join([f"# {branch} · {verdict}", "", f"- {reason}", f"- merged: {merged}", f"- trace: {'; '.join(trace)}", "",
                                                     "## Diff", "", "```diff", diff.rstrip(), "```", ""]))
    return verdict, reason, path


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("branch"); ap.add_argument("--repo", required=True); ap.add_argument("--base", default="main"); ap.add_argument("--out", default="reviews")
    ap.add_argument("--human", default=os.environ.get("REVIEW_HUMAN_NAME")); ap.add_argument("--identity-scope", default=os.environ.get("IDENTITY_SCOPE", "identity"))
    ap.add_argument("--proposal"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    proposal = open(a.proposal, encoding="utf-8").read() if a.proposal and os.path.exists(a.proposal) else "(no proposal file given)"
    complete = (lambda s, u: llm.complete(s, u, model=llm.model_for("review"), max_tokens=300)) if llm.available() else None
    try:
        verdict, reason, path = run(a.branch, a.repo, a.base, a.out, a.human, a.identity_scope, proposal, complete, a.dry_run)
    except Exception as e:
        print(f"review: could not read {a.branch}: {type(e).__name__}: {e}"); return 1
    print(f"review: {a.branch} → {verdict}: {reason} ({path})")
    return 0 if verdict == "MERGE" else 2


if __name__ == "__main__":
    sys.exit(main())
