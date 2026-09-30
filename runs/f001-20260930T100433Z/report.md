# f001-20260930T100433Z — BLOCKED

Spec: `specs/features/F-001-identity.md`  
Tests: 86 passed in 70.28s (0:01:10)

| Acceptance item | Status | Evidence |
|---|---|---|
| 1 upstream commits and runtime contract resolved | PASS | 4 repos pinned; 5 open questions recorded |
| 2 proxy strip/restore copy matches upstream | PASS | tests/contracts/test_proxy_view.py |
| 3 captured copilot payloads in the stripped view | BLOCKED | 0 captured fixtures; blocked by U-001 (needs a paid local copilot run) |
| 4 fingerprints, protected checks, mutants rejected | PASS | tests/contracts/test_suite.py (16 mutants, 1 positive control) |
| 5 scorer, contest and screening parity | PASS | tests/scoring/* |
| 6 manifest, run status, timeouts, budgets, resume | PASS | tests/harness/test_evidence.py; harness/invoke.py |
| 7 commands registered | PASS | python -m harness --help |
| identity candidate passes contracts | PASS | 15 calls, 0 findings |

Open upstream questions:

- **U-001** Exact extra fields and user-content form (string vs parts) in Copilot CLI 1.0.82 chat-completions payloads (blocks: F-001 acceptance item 3 (real fixtures); not the offline harness)
- **U-002** Does the OpenClaw somarizer path ever reach the miner? It POSTs /compress, which the compression service does not serve. (blocks: nothing while copilot is the only agent in use)
- **U-003** How a loop guard can end a run from inside compress_messages (blocks: runtime loop guards (M6))
- **U-004** Whether every stage-2 passer or only a top-ranked cohort advances to full evaluation (blocks: nothing offline)
- **U-005** Competition-specific screening thresholds (code defaults recorded here) (blocks: release policy margin (R-022))

Digests at manifest time:

- `candidate_src` 9649c190c5beac91
- `harness` 28fee082ee4c4392
- `specs` c39782d5fdc26021
- `upstream_lock` 0410a686fc8bbe99
- `acceptance` 343aed3618da3f1b
- `fixtures` e48d72ebafeb28d7
- `configs` b2842282f5da2633
