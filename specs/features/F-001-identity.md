# F-001: Identity miner and trustworthy harness

Revision: 1
Status: BLOCKED (item 3 only; see Decision)
Depends on: M0
Requirements: R-001–R-007, R-009–R-012, R-015–R-017, R-021, R-022

## Problem
No compression claim can be trusted until the harness itself is proven: it must
see exactly what production sends, reject broken candidates, and reproduce the
official scorer.

## Hypothesis
An identity candidate that matches the official baseline passes every contract,
while deliberately broken candidates are each rejected for the requirement they
break.

## Scope
`src/soma_miner/miner.py` (identity), `harness/`, `tests/`, `fixtures/synthetic/`,
`specs/`, `configs/budgets.yaml`.

## Non-goals
No compression, no masking, deduplication or loop guards. No paid runs.

## Acceptance (architecture.md section 29)
AC-1: Upstream commits and runtime contract pinned; unverified cases recorded (`specs/upstream.lock.json`).
AC-2: Harness copy of proxy strip/restore matches upstream (`tests/contracts/test_proxy_view.py`).
AC-3: Captured copilot payloads stored in the stripped view.
AC-4: Fingerprint and protected-field checks reject every mutant; a legitimate control passes (`tests/contracts/test_suite.py`).
AC-5: Scorer, contest and screening match hand-computed cases and upstream functions (`tests/scoring/`).
AC-6: Manifest, run-status model, external timeouts, budgets and resume (`harness/evidence.py`, `runs.py`, `budget.py`, `invoke.py`).
AC-7: Commands registered (`python -m harness --help`).
AC-8: Offline report with digests and receipts (`python -m harness f001`).

## Evidence
`runs/f001-*/manifest.json`, `receipts/`, `report.md`.

## Decision
AC-1, AC-2 and AC-4 to AC-8 pass offline. AC-3 is BLOCKED on U-001: real payloads
need a local copilot benchmark run, which needs a paid budget and an OpenRouter key.
F-002 may start on synthetic fixtures. No compression feature may be promoted on
synthetic fixtures alone.

## Findings recorded during this attempt
- `docs/miner/scoring.md` is stale; the harness follows the pinned scorer code (lock `scoring.doc_discrepancy`).
- Only the copilot agent reaches `compress_messages`; OpenClaw traffic bypasses the compression proxy (lock `runtime.agents`).
- A JSON body without `messages` reaches the miner as `[]`; returning a list adds `messages: []` to it (F-002 input).

## Rollback
Not applicable: identity is the baseline.
