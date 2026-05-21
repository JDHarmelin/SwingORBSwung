#!/usr/bin/env bash
# PreToolUse (Edit|Write|MultiEdit): enforce the alert/paper-only rule.
# Blocks (exit 2) if an edit introduces order-execution / brokerage-trading code.
# This is a guardrail for the project's #1 constraint, not a substitute for review.
set -euo pipefail

INPUT=$(cat)
FILE=$(jq -r '.tool_input.file_path // ""' <<<"$INPUT")

# Only police engine source code.
case "$FILE" in
  *.py) ;;
  *) exit 0 ;;
esac

# Gather all incoming text: Write.content, Edit.new_string, MultiEdit.edits[].new_string
NEW=$(jq -r '
  [ .tool_input.content // empty,
    .tool_input.new_string // empty,
    (.tool_input.edits // [] | .[].new_string // empty)
  ] | join("\n")' <<<"$INPUT")

# Forbidden execution/brokerage signals (case-insensitive).
PATTERN='submit_order|place_order|create_order|cancel_order|\bib_insync\b|alpaca[._]trade|TradingClient|MarketOrder|LimitOrder|broker(age)?[._](connect|client|trade)|execute_trade|send_order'

if grep -nEi "$PATTERN" <<<"$NEW" >/dev/null 2>&1; then
  {
    echo "BLOCKED: this edit to $FILE looks like order-execution / brokerage-trading code."
    echo "SwingORSwung is ALERT / PAPER-ONLY — no order placement or money movement."
    echo "Matched terms:"
    grep -nEi "$PATTERN" <<<"$NEW" | sed 's/^/  /'
  } >&2
  exit 2
fi
exit 0
