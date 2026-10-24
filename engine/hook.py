#!/usr/bin/env python3
"""hook — recall N memories for the prompt a session is about to answer, as a harness hook. Stdlib only, fail-silent.

Reads one JSON object on stdin. The default JSON shape is the common agent-CLI hook convention (session_id and prompt
in on stdin; additionalContext out); adapt the two field names for yours:
  {"hook_event_name": "UserPromptSubmit", "session_id": "...", "prompt": "...", "cwd": "..."}
  {"hook_event_name": "SessionStart",     "session_id": "...", "cwd": "..."}
and prints {"hookSpecificOutput": {"hookEventName": ..., "additionalContext": "..."}} with the slug, description and
any Verifier verdict of each memory — never bodies (the session pulls a body by asking). SessionStart recalls against
the launch directory's name and its last three commit subjects. A memory already shown this session is not shown again;
the seen-state is keyed by session AND by the recall URL, so two stores never share it.
Short prompts (< 20 chars) and slash-commands recall nothing. Any failure → no output, exit 0: a memory hook that can
break a session is worse than none.

Config: RECALL_URL (default http://127.0.0.1:8450), RECALL_TOKEN, HOOK_K (3), HOOK_MIN_SIM (0.60 — a cosine floor from a
vector-leg hit; keyword-only hits pass), HOOK_EXCLUDE_TYPES (comma list, default empty).
"""
import hashlib, json, os, re, subprocess, sys, tempfile, urllib.request

MIN_PROMPT = 20


def cfg():
    return {"url": os.environ.get("RECALL_URL", "http://127.0.0.1:8450").rstrip("/"), "token": os.environ.get("RECALL_TOKEN", ""),
            "k": int(os.environ.get("HOOK_K", "3")), "min_sim": float(os.environ.get("HOOK_MIN_SIM", "0.60")),
            "exclude": [t for t in os.environ.get("HOOK_EXCLUDE_TYPES", "").split(",") if t]}


def recall(query, c, session):
    body = json.dumps({"query": query, "k": c["k"], "exclude_types": c["exclude"], "source": "hook", "session": session}).encode()
    req = urllib.request.Request(c["url"] + "/recall", data=body,
                                 headers={"Authorization": "Bearer " + c["token"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.load(r).get("results", [])


def session_query(cwd):
    parts = [os.path.basename(cwd.rstrip("/"))]
    try:
        out = subprocess.run(["git", "-C", cwd, "log", "-3", "--format=%s"], capture_output=True, text=True, timeout=2).stdout
        parts += [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        pass
    return " ".join(parts)[:400]


def state_path(sid, url):
    return os.path.join(tempfile.gettempdir(), f"memory-hook-{hashlib.sha1(url.encode()).hexdigest()[:10]}-{re.sub(r'[^A-Za-z0-9_-]', '', sid)}.json")


def render(results, seen, min_sim, label):
    fresh = [r for r in results if r.get("slug") not in seen and (r.get("sim") is None or r["sim"] >= min_sim)]
    lines = []
    for r in fresh:
        v = r.get("verdict")
        flag = f"  ⚠ {v['verdict']} ({v.get('votes')}): {(v.get('reason') or '')[:120]}" if v else ""
        lines.append(f"- {r['slug']} [{r.get('project')}] — {(r.get('description') or '')[:200]}{flag}")
    text = (f"[memory] relevant memories {label} (hybrid recall; ask for a body by slug):\n" + "\n".join(lines)) if lines else ""
    return text, {r["slug"] for r in fresh}


def main(stdin=None, c=None, recall_fn=None):
    try:
        d = json.load(stdin or sys.stdin)
    except Exception:
        return 0
    c = c or cfg()
    event = d.get("hook_event_name", "UserPromptSubmit"); sid = str(d.get("session_id") or "nosession")
    if event == "SessionStart":
        query, label = session_query(d.get("cwd") or os.getcwd()), "for this project"
    else:
        p = (d.get("prompt") or "").strip()
        if len(p) < MIN_PROMPT or p.startswith(("/", "!")):
            return 0
        query, label = p[:600], "for this prompt"
    if not c.get("token"):
        return 0
    try:
        results = (recall_fn or recall)(query, c, sid)
    except Exception:
        return 0
    state = state_path(sid, c["url"])
    try:
        seen = set(json.load(open(state)))
    except Exception:
        seen = set()
    text, shown = render(results, seen, c["min_sim"], label)
    if not text:
        return 0
    try:
        json.dump(sorted(seen | shown), open(state, "w"))
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
