"""llm — the one model door the judge, the Gardener and the reviewer share. `complete(system, user)` returns text.

  MODEL_KIND=anthropic   the Messages API (MODEL_BASE_URL default https://api.anthropic.com)
  MODEL_KIND=openai      any /chat/completions-compatible door (MODEL_BASE_URL, e.g. a local router)
  MODEL_NAME             the model; VERIFIER_MODEL / GARDENER_MODEL / REVIEW_MODEL override it per job
  MODEL_API_KEY          read, never printed

No key, no model: `available()` is False and every caller skips its model step and says so in its report — the
deterministic half of each job still runs. Tests pass a fake `complete` callable; nothing here is called offline.
"""
import json, os, urllib.request


def available():
    return bool(os.environ.get("MODEL_API_KEY")) and bool(os.environ.get("MODEL_NAME"))


def model_for(job):
    return os.environ.get(f"{job.upper()}_MODEL") or os.environ.get("MODEL_NAME", "")


def complete(system, user, model=None, max_tokens=1200, timeout=180):
    kind = os.environ.get("MODEL_KIND", "anthropic").lower()
    key = os.environ.get("MODEL_API_KEY", "")
    model = model or os.environ.get("MODEL_NAME", "")
    if not key or not model:
        raise RuntimeError("no MODEL_API_KEY / MODEL_NAME in the environment")
    if kind == "anthropic":
        url = os.environ.get("MODEL_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        payload = {"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
    elif kind == "openai":
        url = os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}"}
        payload = {"model": model, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    else:
        raise ValueError(f"MODEL_KIND={kind!r}: expected anthropic or openai")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    if kind == "anthropic":
        return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    return out["choices"][0]["message"]["content"] or ""


def parse_json(text):
    """The first {...} object in a model reply, tolerant of code fences and stray escapes. None when there is none."""
    t = text.strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        return None
    t = t[start:end + 1]
    try:
        return json.loads(t)
    except ValueError:
        try:
            import re
            return json.loads(re.sub(r'\\(?![\\/"bfnrt]|u[0-9a-fA-F]{4})', r"\\\\", t))
        except ValueError:
            return None
