"""Official SWE task scoring, reimplemented from the pinned scorer (R-015).

Source of truth: soma `mcp_platform/app/api/routes/scoring.py` at the locked
commit. `docs/miner/scoring.md` describes an older curve and is NOT followed
here; the discrepancy is recorded in the lock. Constants are read from the lock
so an upstream change surfaces as a lock change, not a silent drift.

Parity with the upstream functions is tested in tests/scoring/test_parity.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2
from typing import Iterable

from harness.upstream import load_lock

_S = load_lock()["scoring"]
W_INPUT = _S["token_weights"]["input"]
W_CACHED = _S["token_weights"]["cached_input"]
W_OUTPUT = _S["token_weights"]["output"]
R_MIN = _S["r_min"]
R_MAX = _S["r_max"]
BONUS_MAX = _S["bonus_max"]
BONUS_MIN_EXTRA = _S["bonus_min_extra"]
PENALTY_ONLY_RATIO = _S["quality_penalty_only_ratio"]
TOKEN_SCORE_RATIO = _S["quality_token_score_ratio"]
SCORE_MIN = _S["task_score_min"]
SCORE_MAX = _S["task_score_max"]


@dataclass(frozen=True)
class Run:
    """One scored run. Token fields are the provider's split usage; None = missing."""

    resolved: bool | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class TaskResult:
    score: float | None
    zone: str  # penalty | maintain | bonus | none
    pool: str  # main | hard_boost | excluded
    r: float
    x: int
    y: int
    n: int
    baseline_tokens: float | None
    miner_tokens: float | None
    hard_boost_contribution: float | None


def weighted_tokens(input_tokens: int | None, cached_input_tokens: int | None, output_tokens: int | None) -> float | None:
    """1.0 × uncached input + 0.1 × cached input + 3.0 × output; None if invalid."""
    if input_tokens is None or output_tokens is None:
        return None
    cached = 0 if cached_input_tokens is None else cached_input_tokens
    if input_tokens < 0 or cached < 0 or output_tokens < 0:
        return None
    return W_INPUT * input_tokens + W_CACHED * cached + W_OUTPUT * output_tokens


def compression_ratio(baseline_tokens: float | None, miner_tokens: float | None) -> float:
    """r = clamp(log2(T_B / T_A), -2, 2); 0 when either side is missing or non-positive."""
    if not baseline_tokens or not miner_tokens or baseline_tokens <= 0 or miner_tokens <= 0:
        return 0.0
    return max(R_MIN, min(R_MAX, log2(baseline_tokens / miner_tokens)))


def quality_adjusted(x: int, y: int, r: float) -> tuple[float, str]:
    """y ≤ x: -2 → -1 over quality 0..50%, blend -1 → r over 50..80%, r from 80%."""
    quality = max(0.0, min(1.0, y / x))
    if quality <= PENALTY_ONLY_RATIO:
        return R_MIN + 2.0 * quality, "penalty"
    if quality < TOKEN_SCORE_RATIO:
        blend = (quality - PENALTY_ONLY_RATIO) / (TOKEN_SCORE_RATIO - PENALTY_ONLY_RATIO)
        return (1.0 - blend) * -1.0 + blend * r, "penalty"
    return r, "maintain"


def bonus(x: int, y: int, n: int) -> float:
    """Small quadratic bonus once the miner beats baseline by ≥ 2 solves and > half the headroom."""
    extra = max(0, y - x)
    if extra < BONUS_MIN_EXTRA:
        return 0.0
    headroom = max(BONUS_MIN_EXTRA, max(0, n - x))
    progress = extra / headroom
    if progress <= 0.5:
        return 0.0
    return BONUS_MAX * ((progress - 0.5) / 0.5) ** 2


def task_score(x: int, y: int, baseline_tokens: float | None, miner_tokens: float | None, n: int) -> TaskResult:
    r = compression_ratio(baseline_tokens, miner_tokens)
    n = max(int(n), x, y, 1)

    def result(score, zone, pool, hard):
        return TaskResult(score, zone, pool, r, x, y, n, baseline_tokens, miner_tokens, hard)

    if x <= 1:
        if y == 0:
            return result(None, "none", "excluded", None)
        if x == 1 and y == 1:
            score, zone = r, "maintain"
        else:
            b = bonus(x, y, n)
            score, zone = max(R_MIN, min(SCORE_MAX, r + b)), ("bonus" if b > 0 else "maintain")
        return result(score, zone, "hard_boost", max(0.0, score))

    if y <= x:
        score, zone = quality_adjusted(x, y, r)
    else:
        b = bonus(x, y, n)
        score, zone = max(R_MIN, min(SCORE_MAX, r + b)), ("bonus" if b > 0 else "maintain")
    return result(score, zone, "main", None)


def score_task_runs(baseline_runs: list[Run], miner_runs: list[Run]) -> TaskResult:
    """Derive (x, y, T_B, T_A, n) from run records as the platform does, then score.

    T_B averages ALL baseline runs with valid weighted tokens (resolved or not).
    T_A averages all miner runs with weighted tokens > 0 (resolved or not).
    """
    x = sum(1 for run in baseline_runs if run.resolved is True)
    y = sum(1 for run in miner_runs if run.resolved is True)
    b_tokens = [w for run in baseline_runs if (w := _weighted(run)) is not None]
    m_tokens = [w for run in miner_runs if (w := _weighted(run)) is not None and w > 0]
    t_b = sum(b_tokens) / len(b_tokens) if b_tokens else None
    t_a = sum(m_tokens) / len(m_tokens) if m_tokens else None
    n = max(len(baseline_runs), len(miner_runs), x, y, 1)
    return task_score(x, y, t_b, t_a, n)


def aggregate(results: Iterable[TaskResult]) -> tuple[float | None, float | None]:
    """(main_score, hard_boost); both None when there are no tasks at all."""
    results = list(results)
    if not results:
        return None, None
    main = [(res.score, res.x ** (1 / 3)) for res in results if res.pool == "main" and res.score is not None]
    hard = [res.hard_boost_contribution for res in results if res.pool == "hard_boost" and res.hard_boost_contribution is not None]
    main_score = sum(s * w for s, w in main) / sum(w for _, w in main) if main else 0.0
    counted = len(main) + len(hard)
    hard_boost = sum(hard) / counted if hard and counted > 0 else 0.0
    return main_score, hard_boost


def normalize(raw: float) -> float:
    """Clamp to [SCORE_MIN, SCORE_MAX] and map linearly onto [-1, 1]."""
    clamped = max(SCORE_MIN, min(SCORE_MAX, raw))
    return (clamped - SCORE_MIN) / (SCORE_MAX - SCORE_MIN) * 2.0 - 1.0


def total_score(results: Iterable[TaskResult]) -> float | None:
    main_score, hard_boost = aggregate(results)
    if main_score is None or hard_boost is None:
        return None
    return normalize(main_score + hard_boost)


def complexity_scores(results_by_category: dict[str, list[TaskResult]]) -> dict[str, float]:
    """Per-category totals; categories without scored tasks are absent, not zero."""
    scores: dict[str, float] = {}
    for category, results in results_by_category.items():
        value = total_score(results)
        if value is not None:
            scores[category] = value
    return scores


def _weighted(run: Run) -> float | None:
    return weighted_tokens(run.input_tokens, run.cached_input_tokens, run.output_tokens)


def penalty_threshold(x: int) -> int:
    """Smallest resolved count reaching the 80% quality boundary (reporting only)."""
    return ceil(x * TOKEN_SCORE_RATIO)
