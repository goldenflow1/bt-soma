# Scoring, contest and screening parity

The harness follows the pinned **code**, not `docs/miner/scoring.md`, which
describes an older curve. Implementations: `harness/scoring.py`,
`harness/contest.py`, `harness/screening.py`. Constants come from the lock.

## Per task (x = baseline solves, y = miner solves, n = runs)
- `T_B`: mean weighted tokens of **all** baseline runs with valid tokens.
- `T_A`: mean weighted tokens of all miner runs with tokens > 0.
- `r = clamp(log2(T_B / T_A), -2, 2)`, or 0 when either is missing.
- Standard (`x ≥ 2`), `y ≤ x`, quality `q = y/x`:
  - `q ≤ 0.5`: `-2 + 2q`
  - `0.5 < q < 0.8`: linear from −1 to `r`
  - `q ≥ 0.8`: `r`
- `y > x`: `clamp(r + bonus, -2, 2)`. The bonus is at most 0.1, only with ≥ 2 extra solves, quadratic in progress past half the headroom.
- Hard (`x ≤ 1`):
  - `y = 0`: excluded.
  - `x = y = 1`: `r`.
  - Otherwise: as `y > x`.
  - Boost contribution is `max(0, s)`.

## Aggregation
- `main` is the `x^(1/3)`-weighted mean of the main-task scores.
- `hard_boost = Σh / (N_main + N_hard)`.
- `final = clamp(main + hard_boost, -2, 2) / 2`, which lies in `[-1, 1]`.

## Golden cases
`tests/scoring/test_scoring_golden.py`, including the architecture.md section 18.8
example: 0.3291, or 0.5625 without the Task C regression.
`tests/scoring/test_contest_and_screening_golden.py`: Alice/Bob/Carol 75/15/10, ties
(1e-12), two-category renormalization, empty-element redistribution, fallback,
stage-1 and stage-2 screening edges.

## Parity
`tests/scoring/test_parity.py` loads the upstream functions from the pinned files
(digest-checked) and compares:
- about 22k task-score grid points;
- 300 random miner task sets;
- 400 random contests;
- 500 random screening scenarios;
- lock constants and config defaults.
