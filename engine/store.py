"""store — the files. A memory is one markdown file with YAML frontmatter in a store directory; MEMORY.md beside them is
the index, one line per memory, loaded whole at the start of every session. This module reads that shape and nothing
else: parse a file, load a store, read the index, extract the references a body asserts (the Verifier's food).

Frontmatter (docs/FRONTMATTER.md):  name · description · metadata.type (user|feedback|project|reference) ·
metadata.project (the evidence scope) · optional supersedes, metadata.origin, metadata.session.
Index line:  - [Title](slug.md) — one-line hook
"""
import os, re
from dataclasses import dataclass, field

import yaml

TYPES = ("user", "feedback", "project", "reference")
INDEX_FILE = "MEMORY.md"
INDEX_LINE = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<slug>[a-z0-9][a-z0-9-]*)\.md\)\s*(?:—|-)\s*(?P<hook>.*)$")
LINK_RE = re.compile(r"\[\[([a-z0-9][a-z0-9-]*)\]\]")
FM_RE = re.compile(r"\A(---\n.*?\n---\n)(.*)\Z", re.S)

# references: tokens a body asserts about code — a path with a code extension, a backticked flag / path / dotted symbol
EXT = r"py|sql|js|ts|tsx|json|ya?ml|sh|cfg|ini|md|toml|env"
PATH_RE = re.compile(rf"(?<![\w./:-])[\w./-]+\.(?:{EXT})\b(?!\.[A-Za-z])")
BACKTICK_RE = re.compile(r"`([^`]+)`")
SYMBOL_RE = re.compile(r"[A-Za-z_]\w*\.[A-Za-z_][\w.]*")
HAS_EXT = re.compile(rf"[\w-]+\.(?:{EXT})\b(?!\.[A-Za-z])")
URLISH = re.compile(r"[?{}<>*]|://|^www\.")


class FrontmatterError(ValueError):
    """Frontmatter present but unusable: bad YAML, or not a mapping."""


@dataclass
class Memory:
    slug: str
    title: str
    description: str
    type: str
    project: str
    body: str
    links: list = field(default_factory=list)
    supersedes: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    frontmatter: dict = field(default_factory=dict)
    path: str = ""


def split(text):
    """(frontmatter block with its dashes, body) — the block is kept byte-for-byte so a Gardener edit can be checked
    against it. (None, text) when there is no frontmatter."""
    m = FM_RE.match(text)
    return (m.group(1), m.group(2)) if m else (None, text)


def parse(text):
    """(frontmatter dict, body). Raises FrontmatterError on a block that does not parse to a mapping."""
    block, body = split(text)
    if block is None:
        return {}, text
    try:
        fm = yaml.safe_load(block.strip("-\n")) or {}
    except yaml.YAMLError as e:
        raise FrontmatterError(str(e).strip().splitlines()[0]) from e
    if not isinstance(fm, dict):
        raise FrontmatterError(f"frontmatter is {type(fm).__name__}, not a mapping")
    meta = fm.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        raise FrontmatterError(f"metadata is {type(meta).__name__}, not a mapping")
    return fm, body.lstrip("\n")


def _list(v):
    if not v:
        return []
    if not isinstance(v, (str, list, tuple)):
        raise FrontmatterError(f"supersedes is {type(v).__name__}, not a slug or a list of slugs")
    v = [v] if isinstance(v, str) else list(v)
    return [str(x).strip().removesuffix(".md") for x in v if str(x).strip()]


def looks_like_ref(s):
    s = s.strip()
    if not s or len(s) > 80 or " " in s or URLISH.search(s):
        return False
    if s.startswith("--") or (s.startswith("-") and len(s) <= 4):
        return True
    if "/" in s and "." in s:
        return True
    if re.fullmatch(rf"[\w./-]+\.(?:{EXT})", s):
        return True
    return bool(SYMBOL_RE.fullmatch(s))


def extract_refs(body):
    """The paths / flags / dotted symbols a body asserts. A heuristic seed, deliberately conservative: a URL, a template
    (`{id}`, `<name>`, globs) or anything with a space is not a reference."""
    prose = re.sub(r"```.*?```", "", body, flags=re.S)
    scrubbed = BACKTICK_RE.sub(lambda m: "``" if URLISH.search(m.group(1)) else m.group(0), prose)
    refs = {r for r in PATH_RE.findall(scrubbed) if not URLISH.search(r)}
    for span in BACKTICK_RE.findall(prose):
        s = span.strip()
        if URLISH.search(s):
            continue
        if "/" in s and not HAS_EXT.search(s) and not s.startswith(("/", "~/")):
            refs.update(p for p in s.split("/") if SYMBOL_RE.fullmatch(p))   # a.b/c.d → the dotted parts
            continue
        if looks_like_ref(s):
            refs.add(s)
    return sorted(refs)


def links_of(body):
    prose = re.sub(r"```.*?```", "", body, flags=re.S)
    prose = re.sub(r"`[^`]*`", "", prose)
    return sorted(set(LINK_RE.findall(prose)))


def read_index(store):
    """slug -> (title, hook, line number). Lines that are not index lines are ignored here; the lint counts them."""
    out = {}
    path = os.path.join(store, INDEX_FILE)
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            m = INDEX_LINE.match(line.rstrip("\n"))
            if m:
                out[m.group("slug")] = (m.group("title"), m.group("hook").strip(), n)
    return out


def load_file(path, index=None):
    slug = os.path.basename(path)[:-3]
    with open(path, encoding="utf-8") as fh:
        fm, body = parse(fh.read())
    meta = fm.get("metadata") or {}
    title = (index or {}).get(slug, (fm.get("name") or slug,))[0]
    return Memory(slug=slug, title=str(title), description=str(fm.get("description") or ""),
                  type=str(meta.get("type") or fm.get("type") or ""),
                  project=str(meta.get("project") or fm.get("project") or ""),
                  body=body.rstrip() + "\n", links=[l for l in links_of(body) if l != slug],
                  supersedes=[s for s in _list(fm.get("supersedes") or meta.get("supersedes")) if s != slug],
                  refs=extract_refs(body), frontmatter=fm, path=path)


def load(store):
    """(memories, skipped) — one bad file never stops the load: it is skipped with its reason and the rest go on
    (a store froze for a day once over one unquoted colon in a description)."""
    index = read_index(store)
    memories, skipped = [], []
    for fname in sorted(os.listdir(store)):
        if not fname.endswith(".md") or fname == INDEX_FILE:
            continue
        try:
            memories.append(load_file(os.path.join(store, fname), index))
        except (FrontmatterError, UnicodeDecodeError, OSError) as e:
            skipped.append((fname, str(e)))
    return memories, skipped
