# F-002: Format adapter, fail-open wrapper and internal deadline

Revision: 1
Status: READY
Depends on: F-001 (offline items)
Requirements: R-001–R-005, R-009, R-010, R-012, R-017, R-021

## Problem
The platform has no fallback: a miner exception or a call over 30 s fails the
agent's request. Later filters need a safe frame that identifies editable
locations and returns the original on any doubt.

## Hypothesis
A wrapper that validates shape, runs stages under a deadline, verifies the
result, and otherwise returns the input unchanged adds no risk and no latency
worth measuring.

## Scope
`src/soma_miner/`. New fixtures under `fixtures/synthetic/` for malformed shapes.

## Non-goals
No compression stage is enabled. No change to harness, scorer or acceptance policy.

## Required behavior
- Accept only list input; pass unknown message shapes through unchanged.
- Identify editable locations exactly as `harness/contracts.py` EDITABLE declares.
- Run stages under an internal deadline (acceptance.yaml `internal_deadline_s`); return the input on expiry.
- Verify before returning: structure fingerprint, protected fields, allowlisted insertions, size not larger.
- Any exception or failed verification returns the input unchanged.
- Decide, with evidence, what to return when `messages == []` (a list adds `messages: []` to non-chat bodies; `None` leaves them untouched).

## Acceptance
AC-1: Contract suite passes on all fixtures.
AC-2: Fault-injection tests: a stage that raises, times out, grows output, or edits a protected field yields the original input.
AC-3: p99 latency on the fixture corpus below the 200 ms target.
AC-4: Byte-identical output to identity (no stage enabled).

## Allowed paths
src/soma_miner/; tests/miner/; fixtures/synthetic/ (new malformed-shape fixtures only); this spec.

## Evidence
Candidate digest, check receipt, fault-injection test IDs.

## Rollback
Restore the F-001 identity digest.
