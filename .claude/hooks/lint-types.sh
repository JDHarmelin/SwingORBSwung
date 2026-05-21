#!/usr/bin/env bash
# PostToolUse: ruff-fix + format the edited Python file, then mypy it.
# mypy failure exits 2 (blocks) so types stay green while iterating.
set -euo pipefail

FILE=$(jq -r '.tool_input.file_path // ""')
[[ "$FILE" == *.py ]] || exit 0
[[ -f "$FILE" ]] || exit 0

PY=.venv/bin/python
[[ -x "$PY" ]] || PY=python

"$PY" -m ruff check --fix "$FILE" || true
"$PY" -m ruff format "$FILE" || true

if ! "$PY" -m mypy "$FILE"; then
  echo "mypy failed on $FILE — fix type errors before continuing." >&2
  exit 2
fi
