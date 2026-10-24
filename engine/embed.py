"""embed — one function, three doors. `embed(text, kind="document"|"query")` returns a list of floats from

  EMBED_KIND=openai   any /v1/embeddings-compatible endpoint (EMBED_URL, EMBED_MODEL, EMBED_API_KEY)
  EMBED_KIND=ollama   a local ollama (EMBED_URL default http://127.0.0.1:11434, EMBED_MODEL default nomic-embed-text)
  EMBED_KIND=fake     a deterministic hashed bag-of-words vector (EMBED_DIM, default 64) — tests and a first try
  EMBED_DIM           the vector length the graph was created with (defaults: ollama 768, openai 1536, fake 64); checked at startup

Asymmetric prefixes: some local models are trained with a task prefix on each side ("search_document: " for stored text,
"search_query: " for the question) and retrieve off-distribution without them. EMBED_PREFIX=1 adds them; the default is
on for ollama and off for openai. Nothing here is cached or retried; the caller decides what a failure means.
"""
import hashlib, json, math, os, re, urllib.request

PREFIXES = {"document": "search_document: ", "query": "search_query: "}


def config():
    kind = os.environ.get("EMBED_KIND", "fake").lower()
    url = os.environ.get("EMBED_URL") or {"ollama": "http://127.0.0.1:11434", "openai": "https://api.openai.com/v1"}.get(kind, "")
    model = os.environ.get("EMBED_MODEL") or {"ollama": "nomic-embed-text", "openai": "text-embedding-3-small"}.get(kind, "fake")
    prefix = os.environ.get("EMBED_PREFIX", "1" if kind == "ollama" else "0") == "1"
    return {"kind": kind, "url": url.rstrip("/"), "model": model, "prefix": prefix,
            "key": os.environ.get("EMBED_API_KEY", ""),
            "dim": int(os.environ.get("EMBED_DIM") or {"ollama": 768, "openai": 1536}.get(kind, 64))}


def fake_embed(text, dim=64):
    """Hashed bag of words, unit length. Two texts that share words are close; it knows nothing about meaning."""
    v = [0.0] * dim
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 8) % 2 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _post(url, payload, key=""):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
                                 **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def embed(text, kind="query", cfg=None):
    c = cfg or config()
    if c["prefix"]:
        text = PREFIXES[kind] + text
    if c["kind"] == "fake":
        return fake_embed(text, c["dim"])
    if c["kind"] == "ollama":
        try:
            return _post(c["url"] + "/api/embed", {"model": c["model"], "input": text})["embeddings"][0]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            return _post(c["url"] + "/api/embeddings", {"model": c["model"], "prompt": text})["embedding"]
    if c["kind"] == "openai":
        return _post(c["url"] + "/embeddings", {"model": c["model"], "input": text}, c["key"])["data"][0]["embedding"]
    raise ValueError(f"EMBED_KIND={c['kind']!r}: expected openai, ollama or fake")


def cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    den = (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0
    return num / den
