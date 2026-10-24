#!/usr/bin/env bash
# The scrub gate: nothing private leaves in this repo. Zero hits allowed; part of every test run (tests/run.py).
#
# Two layers. Generic, shipped here: secret-shaped strings and the size cap. Yours, never in the repo: a file of
# words that must not appear — hostnames, people, employers, internal tools — one per line, at
# $PRIVATE_WORDS (default ~/.config/missing-piece/private-words). Put your own words there; the gate reads it
# if it exists and says so when it does not. Keep that file out of every repo.
set -u
cd "$(dirname "$0")/.."
EXCL=(--exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=.pytest_cache --exclude-dir=.venv --exclude-dir=venv)
rc=0
words="${PRIVATE_WORDS:-$HOME/.config/missing-piece/private-words}"
if [ -r "$words" ]; then
  n=0
  while IFS= read -r w || [ -n "$w" ]; do
    case "$w" in ''|'#'*) continue;; esac
    n=$((n + 1))
    hits=$(grep -rIin "${EXCL[@]}" -F -- "$w" . || true)
    if [ -n "$hits" ]; then echo "check: a private word found:"; printf '%s\n' "$hits" | sed 's/^/  /'; rc=1; fi
  done < "$words"
  wordnote="$n private words checked"
else
  wordnote="no private-words file at $words (none checked)"
fi
shape=$(grep -rIEn "${EXCL[@]}" -e 'sk-[A-Za-z0-9_-]{20,}' -e 'BEGIN (RSA |OPENSSH )?PRIVATE KEY' -e 'ghp_[A-Za-z0-9]{20,}' -e 'AKIA[0-9A-Z]{16}' -e 'xox[abp]-[A-Za-z0-9-]{10,}' . || true)
if [ -n "$shape" ]; then echo "check: a secret-shaped string:"; printf '%s\n' "$shape" | sed 's/^/  /'; rc=1; fi
total=$(find . \( -path ./.git -o -path ./.venv -o -path ./venv \) -prune -o -type f \( -name '*.py' -o -name '*.md' -o -name '*.yml' -o -name '*.sh' -o -name '*.toml' -o -name '*.example' -o -name '*.yaml' -o -name '*.sql' -o -name 'LICENSE' \) -print0 | xargs -0 cat | wc -l)
if [ "$total" -gt 4000 ]; then echo "check: $total lines — the budget is 4000"; rc=1; fi
[ $rc -eq 0 ] && echo "check: clean ($total lines, nothing secret-shaped, $wordnote)"
exit $rc
