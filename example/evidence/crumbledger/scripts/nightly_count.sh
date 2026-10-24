#!/usr/bin/env bash
# The nightly count: yesterday's closing counts into the store, then the reorder list for the morning.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m crumb.count --date "$(date -d yesterday +%F)"
python -m crumb.reorder --print
