# Parallel build prompts — Systematic Momentum Options Engine

These prompts let you build the engine described in
[`claude_code_trading_engine_outline.md`](../claude_code_trading_engine_outline.md)
using **multiple Claude Code instances running at the same time** in separate
terminals.

## Why waves (read this first)

Two Claude instances editing the **same file** at the same time will overwrite
each other. To run safely in parallel, this build is organized so that:

1. A single **foundation** prompt runs first and alone. It defines every shared
   type, interface, config, and test fixture. Nothing else can be built until
   these contracts exist.
2. After that, every prompt **owns its own directory** and depends only on
   already-finished work. Prompts in the same wave never touch the same files,
   so they can run simultaneously with zero conflicts.
3. A final **orchestration** prompt wires everything together.

```
Wave 0  ── 00_foundation                         (run ALONE, first)
              │
Wave 1  ──┬── 01_data_layer        (terminal 1)  ┐
          ├── 02_features          (terminal 2)  │  run these 4
          ├── 03_storage           (terminal 3)  │  AT THE SAME TIME
          └── 04_alerts            (terminal 4)  ┘
              │
Wave 2  ──┬── 05_scanners          (terminal 1)  ┐
          ├── 06_setups            (terminal 2)  │  run these 3
          └── 07_risk_contracts    (terminal 3)  ┘  AT THE SAME TIME
              │
Wave 3  ── 08_orchestration                      (run ALONE, last)
```

Within a wave the prompts are independent. **Wait for a whole wave to finish
(and be committed) before starting the next wave** — later waves import the code
earlier waves produce.

## How to run in separate terminals (recommended: git worktrees)

The foundation prompt runs `git init`. After Wave 0 is committed, give each
parallel prompt its own worktree so the instances never share a working copy:

```bash
# from the repo root, once per parallel prompt in the wave
git worktree add ../engine-data    -b data
git worktree add ../engine-features -b features
git worktree add ../engine-storage  -b storage
git worktree add ../engine-alerts   -b alerts
```

Open each worktree directory in its own terminal, start `claude` there, and
paste the matching prompt. When the wave is done, merge each branch back:

```bash
git checkout main
git merge data features storage alerts   # disjoint dirs → no conflicts
```

Then repeat the worktree + merge cycle for Wave 2.

> Simpler but slower alternative: skip worktrees and just run the prompts one
> after another in a single repo. You lose the parallelism but the wave order
> still applies.

## Ground rules baked into every prompt

- **Alert / paper only.** The engine never places orders, moves money, or
  connects to a live brokerage for execution. It scans, scores, and alerts.
- **Nothing is financial advice.** Signals are research output, not
  recommendations.
- **Stay in your lane.** Each prompt edits only the files it is told to own and
  imports shared code from `trading_engine.core`. It must not modify another
  module's directory or the shared `core/` package.
- **Mock first.** Everything is built and tested against the mock data adapter
  and the shared fixtures — no API keys or paid feeds required to develop.
- **Tests required.** Every prompt ships unit tests that pass via `pytest`.

## Package layout (created by Wave 0)

```
trading_engine/
  core/        types.py, interfaces.py, config.py   ← Wave 0 owns this
  data/        ← 01    features/  ← 02    storage/   ← 03    alerts/  ← 04
  scanners/    ← 05    setups/    ← 06    risk/      ← 07
  services/    app.py  ← 08
config/        settings.yaml, universe.yaml          ← Wave 0
tests/         fixtures/                              ← Wave 0 seeds fixtures
```
