# Overview

Goal: a SOMA miner (`compress_messages`) that lowers weighted token use without
lowering solve rate. It must also clear stage-2 screening (≥ 10% pooled savings).
Design and rationale: `architecture.md`. This directory is the source of truth for
what the harness enforces.

| File | Holds |
|---|---|
| `upstream.lock.json` | Pinned upstream commits, file digests, runtime facts, scoring constants, open questions |
| `contracts.md` | What the miner receives, what it may change, how each requirement is checked |
| `scoring.md` | Code-verified scoring, contest and screening rules and their tests |
| `acceptance.yaml` | Gates, latency limits and promotion policy |
| `features/F-*.md` | One bounded behavior change each, with acceptance and evidence |

## Feature queue
| Spec | Status |
|---|---|
| F-001 identity miner and trustworthy harness | BLOCKED on U-001 (captured payloads); offline items pass |
| F-002 format adapter, fail-open, internal deadline | READY |
| F-003 conservative pytest progress compression | planned (architecture.md section 25 template) |

## Non-goals
No LLM inside the miner. No benchmark-ID routing or known answers. No paid runs
without a budget in `configs/budgets.yaml`.
