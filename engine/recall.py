#!/usr/bin/env python3
"""recall — hybrid recall over the graph, as a function, a CLI and a small HTTP API (stdlib only).

  python -m engine.recall "how do we reorder flour" [-k 3] [--graph graph.json]
  python -m engine.recall --serve [--bind 127.0.0.1] [--port 8450]       RECALL_TOKEN required

  POST /recall  {"query": "...", "k": 3, "exclude_types": [], "source": "hook|cli|...", "session": "..."}
                → {"results": [{slug, title, description, body, project, type, score, sim, related, verdict?}]}
  GET  /status  → {"ok", "nodes", "last_run", "flagged": [...]}      GET /healthz → {"ok", "nodes}   (no token)
  Every request but /healthz carries `Authorization: Bearer $RECALL_TOKEN`. Bind to loopback or a private interface,
  never 0.0.0.0 — the API returns memory bodies.

Ranking is reciprocal rank fusion of two legs (keyword, vector), nothing more: no recency, no confidence, no weights.
`score` is rank-based and cannot say "nothing relevant"; `sim` (cosine from the vector leg, None for a keyword-only
hit) can — the hook uses it as a floor. An unreachable embedder degrades to the keyword leg alone, with one stderr line. `related` = one hop along [[links]], under the same type exclusion as the results. `verdict` appears only when the Verifier has
flagged the memory (2-of-3), so a session reads the doubt beside the memory instead of trusting it blind.
"""
import argparse, json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import embed as E
from .config import load_env
from .graph import open_graph

MAX_K = 8


def recall(graph, query, k=3, exclude_types=(), source="cli", session=None, embed_fn=None):
    try:
        qvec = (embed_fn or (lambda t: E.embed(t, kind="query")))(query)
    except Exception as e:                      # the embedder is down: keyword leg only, said once on stderr, never a failure
        print(f"recall: embedder unreachable ({type(e).__name__}) — keyword-only for this query", file=sys.stderr)
        qvec = None
    rows = graph.recall(query, qvec, min(int(k), MAX_K), exclude_types)
    related = graph.neighbors([r["slug"] for r in rows], exclude_types)
    flagged = {f["slug"]: f for f in graph.flagged()}
    for r in rows:
        r["related"] = related.get(r["slug"], [])
        if r["slug"] in flagged:
            f = flagged[r["slug"]]
            r["verdict"] = {"verdict": f["verdict"], "reason": f["reason"], "votes": f"{f['bad_votes']}/{f['votes']}", "last_seen": f["last_seen"]}
    graph.log_recall(source, session, query, [r["slug"] for r in rows], rows[0]["sim"] if rows else None)
    graph.save()
    return rows


def status(graph):
    return {"ok": True, "nodes": graph.count_active(), "last_run": graph.last_run(), "flagged": graph.flagged()}


def make_handler(graph, token, embed_fn=None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, payload):
            data = json.dumps(payload, ensure_ascii=False, default=str).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _authed(self):
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, {"ok": True, "nodes": graph.count_active()})
            if self.path != "/status":
                return self._send(404, {"error": "not found"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            self._send(200, status(graph))

        def do_POST(self):
            if self.path != "/recall":
                return self._send(404, {"error": "not found"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                query = str(body.get("query") or "").strip(); excl = body.get("exclude_types") or []
                k = int(body.get("k", 3))
                if not query or not isinstance(excl, list):
                    raise ValueError
            except Exception:
                return self._send(400, {"error": "query required"})
            try:
                rows = recall(graph, query, k, [str(t) for t in excl], str(body.get("source") or "api"), body.get("session"), embed_fn)
            except Exception as e:          # the error type, never the query or the trace
                return self._send(500, {"error": f"recall failed: {type(e).__name__}"})
            self._send(200, {"query": query, "results": rows})

        def log_message(self, *a):      # queries are private; no per-request log line
            pass
    return Handler


def serve(graph, token, bind="127.0.0.1", port=8450, embed_fn=None):
    srv = ThreadingHTTPServer((bind, port), make_handler(graph, token, embed_fn))
    return srv


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query", nargs="?"); ap.add_argument("-k", type=int, default=3); ap.add_argument("--graph")
    ap.add_argument("--exclude", action="append", default=[], help="a type to exclude (repeatable)")
    ap.add_argument("--serve", action="store_true"); ap.add_argument("--bind", default=os.environ.get("RECALL_BIND", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("RECALL_PORT", "8450")))
    a = ap.parse_args(argv)
    graph = open_graph(a.graph)
    if a.serve:
        token = os.environ.get("RECALL_TOKEN")
        if not token:
            sys.exit("recall: RECALL_TOKEN is not set (the API refuses to start without one)")
        print(f"recall api on {a.bind}:{a.port}", flush=True)
        serve(graph, token, a.bind, a.port).serve_forever()
        return 0
    if not a.query:
        ap.error("a query, or --serve")
    for r in recall(graph, a.query, a.k, a.exclude):
        flag = f"  ⚠ {r['verdict']['verdict']} ({r['verdict']['votes']})" if r.get("verdict") else ""
        print(f"{r['score']:.5f}  sim={r['sim'] if r['sim'] is not None else '-':<7} [{r['project']}/{r['type']}] {r['slug']} — {r['description'][:100]}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
