#!/usr/bin/env bash
# Stop: run the test suite before Claude finishes. Exit 2 keeps it working.
# Guarded by stop_hook_active so it never loops forever.
set -euo pipefail

INPUT=$(cat)
[[ "$(jq -r '.stop_hook_active // false' <<<"$INPUT")" == "true" ]] && exit 0

PY=.venv/bin/python
[[ -x "$PY" ]] || PY=python

if ! "$PY" -m pytest --tb=short -q; then
  echo "Tests are failing — do not stop yet; fix them first." >&2
  exit 2
fi
