#!/usr/bin/env python3
"""gardener — turns flagged verdicts into proposed fixes: one git branch per memory, never a direct edit, never a deletion.

  python -m engine.gardener --repo DIR [--graph graph.json] [--out proposals] [--base main] [--max 3] [--dry-run]

For every memory the Verifier flags (2 of the last 3 post-edit verdicts STALE or CONTRADICTED) that has no open
proposal and none closed in the last 30 days: a worktree on `gardener/<slug>-<yyyymmdd>` from `--base`; the model drafts
the MINIMAL edit — frontmatter byte-identical, at most 40% of body lines, YAML still parses, a superseded claim marked
in place as a dated correction ("was X; as of <date> Y"), never removed — or, when it cannot or will not, one dated
note under the frontmatter saying what the judge found and that a human edit is needed; a commit; a proposal file
`<out>/<branch>.md` carrying the evidence (verdict, reason, the flagged references). Pushing the branch and opening
the pull request on your forge is the caller's one line; the file is the PR body.

The ledger `<out>/proposals.jsonl` remembers every proposal. Each run first syncs it: a branch merged into base →
merged; a branch that is gone → closed (the memory is left alone for 30 days); a flag that cleared while the proposal
was open → withdrawn. A merged proposal changes the file, the next ingest moves updated_at, and the verdict is void —
exactly as a human edit would.
"""
import argparse, datetime as dt, difflib, json, os, re, subprocess, sys, tempfile

import yaml

from . import llm, store as S
from .graph import open_graph

MAX_CHANGE = 0.40
SYSTEM = ("You maintain one file of an engineering memory store: markdown with a YAML frontmatter block, one durable fact per "
          "file, written by an AI collaborator for itself and the human it works with. A nightly verifier judged this memory "
          "STALE or CONTRADICTED against the code, with evidence. Produce the MINIMAL edit that makes the memory true again.\n"
          "Rules:\n- The frontmatter block (between the first two '---' lines) must be returned byte-identical.\n"
          "- Change only the sentences the evidence contradicts. Keep voice, structure, links and every unrelated fact exactly.\n"
          "- Never delete history: mark a superseded claim in place, e.g. '(was X; as of {today} Y)'.\n"
          "- If the evidence does not say what the correct new fact IS, do not guess: add one line directly under the "
          "frontmatter — '> Verifier {today}: <verdict> — <reason>; needs a human edit.' — and change nothing else.\n"
          "- Never quote a retired filename as a bare path (it would be re-harvested as a reference); describe it.\n"
          "Output ONLY the complete new file inside <file> and </file> tags.")


def sh(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def sane(old, new):
    """The guard on a draft: same frontmatter bytes, YAML parses, a body, ≤40% of body lines changed."""
    ofm, obody = S.split(old); nfm, nbody = S.split(new)
    if not ofm or nfm != ofm:
        return False, "frontmatter changed"
    try:
        yaml.safe_load(nfm.strip("-\n"))
    except Exception as e:
        return False, f"frontmatter no longer parses: {e}"
    ol, nl = obody.splitlines(), nbody.splitlines()
    if not nl:
        return False, "empty body"
    sm = difflib.SequenceMatcher(None, ol, nl)
    changed = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
    ratio = changed / max(len(ol), 1)
    return (ratio <= MAX_CHANGE, f"{ratio:.0%} of body lines changed" + ("" if ratio <= MAX_CHANGE else f" (> {MAX_CHANGE:.0%})"))


def note_edit(old, verdict, reason, today):
    fm, body = S.split(old)
    return (fm or "") + f"\n> Verifier {today}: judged **{verdict}** — {reason} (no safe minimal edit could be drafted; needs a human edit.)\n" + body


def draft(complete, slug, text, verdict, reason, table, today):
    user = (f"MEMORY FILE `{slug}.md`:\n<file>\n{text}\n</file>\n\nVERDICT: {verdict}\nJUDGE'S REASON: {reason}\n\n"
            f"FLAGGED REFERENCES:\n{table}\n\nToday is {today}.")
    out = complete(SYSTEM.replace("{today}", today), user)
    m = re.search(r"<file>\n?(.*?)\n?</file>", out, re.S)
    if not m:
        return None, "no <file> block in the model's reply"
    new = m.group(1)
    return new if new.endswith("\n") else new + "\n", "ok"


def ref_table(details):
    rows = [d for d in details if d.get("status") in ("missing", "changed", "moved")]
    if not rows:
        return "_none_"
    return "\n".join(["| ref | kind | status | where |", "|---|---|---|---|"]
                     + [f"| `{d['ref']}` | {d.get('kind', '')} | **{d['status']}** | {d.get('found_in') or ''} |" for d in rows])


def proposal_body(slug, flag, table, mode, today):
    what = "a minimal edit drafted by the model" if mode == "draft" else "a dated note under the frontmatter (no safe minimal edit could be drafted)"
    return "\n".join([f"# gardener: `{slug}` is {flag['verdict']}", "",
                      f"**Verdict:** {flag['verdict']} in {flag['bad_votes']}/{flag['votes']} of the last nightly judgments since this memory's last edit "
                      f"(finding #{flag['finding_id']}, last seen {str(flag['last_seen'])[:10]}).", f"**Judge's reason:** {flag['reason']}", "",
                      "**Flagged references:**", table, "", f"**This branch:** {what}. Nothing on the base branch changed.", "",
                      "**Your move:** merge = accept. Delete the branch = reject; the Gardener leaves this memory alone for 30 days. "
                      "Editing the memory yourself also clears the flag on the next ingest.", "",
                      "_Possible false positive: the referenced work exists somewhere this host cannot see._", "", f"— the Gardener, {today}"])


class Ledger:
    def __init__(self, out):
        self.path = os.path.join(out, "proposals.jsonl"); os.makedirs(out, exist_ok=True)
        self.rows = [json.loads(l) for l in open(self.path, encoding="utf-8")] if os.path.exists(self.path) else []

    def save(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in self.rows)

    def blocked(self, slug, today):
        cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=30)).isoformat()
        return any(r["slug"] == slug and (r["state"] == "open" or (r["state"] == "closed" and r["created"] >= cutoff)) for r in self.rows)

    def sync(self, repo, base, flagged, today):
        branches = set(sh(["git", "branch", "--format=%(refname:short)"], cwd=repo).split())
        merged = set(sh(["git", "branch", "--merged", base, "--format=%(refname:short)"], cwd=repo).split())
        notes = []
        for r in self.rows:
            if r["state"] != "open":
                continue
            if r["branch"] in merged and r["branch"] != base:
                r["state"], r["closed"] = "merged", today
            elif r["branch"] not in branches:
                r["state"], r["closed"] = "closed", today
            elif r["slug"] not in flagged:
                r["state"], r["closed"] = "withdrawn", today
                notes.append(f"{r['slug']}: proposal withdrawn (the flag cleared; branch {r['branch']} left for you to delete)")
        return notes


def run(repo, graph, out, base="main", complete=None, cap=3, dry_run=False, today=None):
    today = today or dt.date.today().isoformat()
    stamp = today.replace("-", "")
    ledger = Ledger(out)
    flagged = {f["slug"]: f for f in graph.flagged()}
    log = ledger.sync(repo, base, flagged, today)
    opened = []
    for slug, flag in sorted(flagged.items(), key=lambda kv: str(kv[1]["last_seen"]), reverse=True):
        if len(opened) >= cap:
            log.append(f"cap {cap} reached — {len(flagged) - len(opened)} left for the next run"); break
        if ledger.blocked(slug, today):
            log.append(f"{slug}: a proposal is open or was closed within 30 days — skip"); continue
        if not os.path.isfile(os.path.join(repo, f"{slug}.md")):
            log.append(f"{slug}: not a file on {base} — skip"); continue
        details = next((f["details"] for f in graph.findings(slug, limit=10) if f["id"] == flag["finding_id"]), [])
        table = ref_table(details)
        old = open(os.path.join(repo, f"{slug}.md"), encoding="utf-8").read()
        new, mode = None, "note"
        if complete:
            try:
                new, why = draft(complete, slug, old, flag["verdict"], flag["reason"], table, today)
            except Exception as e:
                new, why = None, f"model call failed: {type(e).__name__}"
            if new is not None:
                ok, why2 = sane(old, new)
                if ok and new != old:
                    mode = "draft"; log.append(f"{slug}: draft accepted ({why2})")
                else:
                    new = None; log.append(f"{slug}: draft rejected ({why2 if not ok else 'no change'}) — note-only")
            else:
                log.append(f"{slug}: no draft ({why}) — note-only")
        if new is None:
            new = note_edit(old, flag["verdict"], flag["reason"], today)
        branch = f"gardener/{slug}-{stamp}"
        if dry_run:
            log.append(f"{slug}: DRY RUN would open {branch} ({mode})"); opened.append(branch); continue
        wt = tempfile.mkdtemp(prefix="gardener-")
        try:
            sh(["git", "worktree", "add", "-q", "-B", branch, wt, base], cwd=repo)
            open(os.path.join(wt, f"{slug}.md"), "w", encoding="utf-8").write(new)
            sh(["git", "add", f"{slug}.md"], cwd=wt)
            sh(["git", "-c", "user.name=gardener", "-c", "user.email=gardener@localhost", "commit", "-q", "-m",
                f"gardener: {slug} judged {flag['verdict']} (finding #{flag['finding_id']})"], cwd=wt)
        finally:
            sh(["git", "worktree", "remove", "--force", wt], cwd=repo, check=False)
        open(os.path.join(out, branch.replace("/", "--") + ".md"), "w", encoding="utf-8").write(proposal_body(slug, flag, table, mode, today) + "\n")
        ledger.rows.append({"slug": slug, "branch": branch, "verdict": flag["verdict"], "finding_id": flag["finding_id"], "mode": mode,
                            "state": "open", "created": today})
        opened.append(branch); log.append(f"{slug}: branch {branch} ({mode}) — push it and open the PR with {out}/{branch.replace('/', '--')}.md")
    ledger.save()
    return opened, log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", required=True); ap.add_argument("--graph"); ap.add_argument("--out", default="proposals")
    ap.add_argument("--base", default="main"); ap.add_argument("--max", type=int, default=3); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    complete = (lambda s, u: llm.complete(s, u, model=llm.model_for("gardener"), max_tokens=8000)) if llm.available() else None
    if not complete:
        print("gardener: no MODEL_API_KEY / MODEL_NAME — note-only proposals")
    g = open_graph(a.graph)
    try:
        opened, log = run(a.repo, g, a.out, a.base, complete, a.max, a.dry_run)
    finally:
        g.close()
    print("\n".join(f"[gardener] {l}" for l in log) or "[gardener] nothing flagged")
    print(f"[gardener] {len(opened)} proposal(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
