"""graph_mem — the in-process graph: the same interface as graph_pg, in plain Python, persisted to one JSON file.

This is the graph the tests run on and the one a stranger tries first (`GRAPH_PATH=graph.json`). Keyword leg = BM25,
vector leg = cosine, fused with reciprocal rank fusion exactly as the Postgres graph does it. It is not the production
path: it reloads the whole file per process and holds everything in memory. Postgres is (docs/DESIGN.md).
"""
import json, math, os, re
from collections import Counter
from datetime import datetime, timezone

from .embed import cosine

RRF_K, LEG = 60, 50


def now():
    return datetime.now(timezone.utc).isoformat()


def tokens(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


class MemoryGraph:
    def __init__(self, path=None):
        self.path = path
        self.d = {"nodes": {}, "edges": [], "runs": [], "findings": [], "anchors": {}, "events": []}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.d = json.load(fh)

    def save(self):
        if self.path:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.d, fh)
            os.replace(tmp, self.path)

    close = save

    # ── ingest ──────────────────────────────────────────────────────────────────────────────────────────────────
    def upsert(self, m):
        n = self.d["nodes"].get(m["slug"])
        content = (m["title"], m["description"], m["body"])
        changed = n is None or (n["title"], n["description"], n["body"]) != content
        if n is None:
            n = self.d["nodes"][m["slug"]] = {"slug": m["slug"], "written_at": now(), "embedding": None, "valid_to": None,
                                              "invalidated_by": None, "updated_at": now()}
        n.update(title=m["title"], description=m["description"], body=m["body"], type=m["type"], project=m["project"],
                 refs=list(m.get("refs") or []), frontmatter=m.get("frontmatter") or {}, status="active")
        if changed:
            n["updated_at"], n["embedding"] = now(), None
        return changed

    def set_links(self, slug, links):
        self.d["edges"] = [e for e in self.d["edges"] if not (e["src"] == slug and e["rel"] == "relates_to")]
        self.d["edges"] += [{"src": slug, "dst": l, "rel": "relates_to"} for l in links]

    def apply_supersedes(self, pairs):
        """pairs = {slug: [targets]}. A superseded node's validity window closes (out of recall and the Verifier, never
        deleted); dropping the field reopens it."""
        self.d["edges"] = [e for e in self.d["edges"] if e["rel"] != "supersedes"]
        closed = {}
        for src, targets in pairs.items():
            for dst in targets:
                self.d["edges"].append({"src": src, "dst": dst, "rel": "supersedes"})
                if dst in self.d["nodes"] and self.d["nodes"][src]["status"] == "active":
                    closed[dst] = src
        reopened = 0
        for slug, n in self.d["nodes"].items():
            if slug in closed:
                n["valid_to"], n["invalidated_by"] = n.get("valid_to") or now(), closed[slug]
            elif n.get("invalidated_by"):
                n["valid_to"], n["invalidated_by"] = None, None; reopened += 1
        return len(closed), reopened

    def archive_missing(self, keep):
        n = 0
        for slug, node in self.d["nodes"].items():
            if node["status"] == "active" and slug not in keep:
                node["status"], node["updated_at"] = "archived", now(); n += 1
        return n

    def unembedded(self):
        return [(s, f"{n['title']}\n{n['description']}\n{n['body']}") for s, n in self.d["nodes"].items() if n["embedding"] is None]

    def set_embedding(self, slug, vec):
        self.d["nodes"][slug]["embedding"] = list(vec)

    # ── recall ──────────────────────────────────────────────────────────────────────────────────────────────────
    def _live(self, exclude_types=()):
        return [n for n in self.d["nodes"].values() if n["status"] == "active" and n["valid_to"] is None
                and (n.get("type") or "") not in set(exclude_types)]

    def _bm25(self, query, pool, k1=1.5, b=0.75):
        docs = {n["slug"]: tokens(f"{n['title']} {n['description']} {n['body']}") for n in pool}
        if not docs:
            return []
        avg = sum(len(t) for t in docs.values()) / len(docs)
        df = Counter(w for t in docs.values() for w in set(t))
        q = [w for w in set(tokens(query)) if w in df]
        scored = []
        for slug, t in docs.items():
            tf = Counter(t); s = 0.0
            for w in q:
                idf = math.log(1 + (len(docs) - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
            if s > 0:
                scored.append((s, slug))
        return [slug for _, slug in sorted(scored, reverse=True)[:LEG]]

    def recall(self, query, qvec, k=5, exclude_types=()):
        pool = self._live(exclude_types)
        sims = {n["slug"]: cosine(qvec, n["embedding"]) for n in pool if n["embedding"] is not None} if qvec else {}
        vec = [s for s, _ in sorted(sims.items(), key=lambda kv: -kv[1])[:LEG]]
        kw = self._bm25(query, pool)
        score = Counter()
        for leg in (vec, kw):
            for rank, slug in enumerate(leg, 1):
                score[slug] += 1.0 / (RRF_K + rank)
        out = []
        for slug, sc in score.most_common(k):
            n = self.d["nodes"][slug]
            out.append({"slug": slug, "title": n["title"], "description": n["description"], "body": n["body"],
                        "project": n["project"], "type": n["type"], "score": round(sc, 5),
                        "sim": round(sims[slug], 4) if slug in vec else None})
        return out

    def neighbors(self, slugs):
        out = {}
        for e in self.d["edges"]:
            dst = self.d["nodes"].get(e["dst"])
            if e["src"] in slugs and e["rel"] == "relates_to" and dst and dst["status"] == "active" and dst["valid_to"] is None:
                out.setdefault(e["src"], []).append({"slug": e["dst"], "title": dst["title"]})
        return out

    def log_recall(self, source, session, query, returned, top_sim):
        self.d["events"].append({"ts": now(), "source": source[:32], "session": (session or "")[:64], "query": query[:2000],
                                 "returned": list(returned), "top_sim": top_sim})

    def count_active(self):
        return len(self._live())

    # ── verifier ────────────────────────────────────────────────────────────────────────────────────────────────
    def active_with_refs(self):
        return [{"slug": s, "project": n["project"], "type": n["type"], "refs": n["refs"], "updated_at": n["updated_at"],
                 "frontmatter": n["frontmatter"], "body": n["body"]}
                for s, n in sorted(self.d["nodes"].items()) if n["status"] == "active" and n["valid_to"] is None and n["refs"]]

    def anchors(self, slug):
        return {ref: tuple(v) for ref, v in self.d["anchors"].get(slug, {}).items()}

    def set_anchor(self, slug, ref, repo_path, sha):
        self.d["anchors"].setdefault(slug, {})[ref] = [sha, now(), repo_path]

    def start_run(self, mode):
        self.d["runs"].append({"id": len(self.d["runs"]) + 1, "started_at": now(), "finished_at": None, "mode": mode})
        return self.d["runs"][-1]["id"]

    def finish_run(self, run_id, counts):
        self.d["runs"][run_id - 1].update(finished_at=now(), **counts)

    def last_run(self):
        return self.d["runs"][-1] if self.d["runs"] else None

    def add_finding(self, run_id, slug, result, details):
        f = {"id": len(self.d["findings"]) + 1, "run_id": run_id, "slug": slug, "result": result, "details": details,
             "verdict": None, "reason": None, "created_at": now()}
        self.d["findings"].append(f)
        return f["id"]

    def set_verdict(self, finding_id, verdict, reason):
        self.d["findings"][finding_id - 1].update(verdict=verdict, reason=reason)

    def findings(self, slug, before_id=None, limit=3):
        rows = [f for f in self.d["findings"] if f["slug"] == slug and (before_id is None or f["id"] < before_id)]
        return sorted(rows, key=lambda f: -f["id"])[:limit]

    def flagged(self):
        """The one definition of flagged: among the findings written after the memory's last content change, at least
        2 of the last 3 carry STALE or CONTRADICTED. A flapping judge never flags alone; an edit voids everything."""
        out = []
        for slug, n in sorted(self.d["nodes"].items()):
            if n["status"] != "active" or n["valid_to"] is not None:
                continue
            recent = [f for f in self.findings(slug) if f["created_at"] > n["updated_at"]][:3]
            bad = [f for f in recent if f["verdict"] in ("STALE", "CONTRADICTED")]
            if len(bad) >= 2:
                out.append({"slug": slug, "project": n["project"], "verdict": bad[0]["verdict"], "reason": bad[0]["reason"],
                            "finding_id": bad[0]["id"], "bad_votes": len(bad), "votes": len(recent), "last_seen": recent[0]["created_at"]})
        return out
