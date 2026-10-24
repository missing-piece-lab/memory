#!/usr/bin/env python3
"""Run every test file, then the scrub gate. No pytest needed: `python tests/run.py`. (pytest works too: `python -m pytest`.)
Every test is offline: a fake embedder, a fake judge, the in-process graph, temp directories. Postgres is never required."""
import glob, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
red = []
for t in sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py"))):
    r = subprocess.run([sys.executable, t], capture_output=True, text=True, cwd=ROOT)
    name = os.path.relpath(t, ROOT)
    print(f"{'ok ' if r.returncode == 0 else 'RED'} {name}")
    if r.returncode:
        red.append(name); print((r.stdout + r.stderr)[-2000:])
r = subprocess.run(["bash", os.path.join(ROOT, "tools", "check.sh")], capture_output=True, text=True, cwd=ROOT)
print(("ok  " if r.returncode == 0 else "RED ") + "tools/check.sh — " + (r.stdout + r.stderr).strip())
if r.returncode:
    red.append("tools/check.sh")
print("all green" if not red else f"RED: {', '.join(red)}")
sys.exit(1 if red else 0)
