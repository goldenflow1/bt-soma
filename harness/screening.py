"""Screening gates, reimplemented from the pinned screener (R-022).

Source of truth: soma `mcp_platform/app/services/swebench_screening.py` with the
defaults from `app/core/config.py`, as recorded in the lock. A competition may
configure different thresholds; pass them explicitly when known.

Each attempt is (resolved, weighted_tokens) for the miner and the baseline,
keyed by task. `resolved=None` means not scored yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from harness.upstream import load_lock

_G = load_lock()["screening"]


@dataclass(frozen=True)
class Attempt:
    resolved: bool | None
    weighted_tokens: float | None


@dataclass(frozen=True)
class Verdict:
    complete: bool
    passed: bool
    reason: str
    savings_ratio: float | None = None


def savings_ratio(baseline_total: float, miner_total: float) -> float | None:
    if baseline_total <= 0:
        return None
    return (baseline_total - miner_total) / baseline_total


def stage1(
    miner: dict[str, list[Attempt]],
    baseline: dict[str, list[Attempt]],
    *,
    epsilon: float = _G["stage1_quality_epsilon"],
    required_saving: float = _G["stage1_token_saving_ratio"],
) -> Verdict:
    """Pooled quality ≥ pooled baseline − epsilon, and pooled weighted savings ≥ required."""
    if not miner:
        return Verdict(True, True, "no stage-1 tasks")
    m_quality, b_quality = [], []
    m_total = b_total = 0.0
    for task, attempts in miner.items():
        base = baseline.get(task, [])
        for i, attempt in enumerate(attempts):
            if i >= len(base) or base[i].resolved is None:
                return Verdict(False, False, f"baseline attempt {task}#{i + 1} not scored")
            if attempt.resolved is None:
                return Verdict(False, False, f"miner attempt {task}#{i + 1} not scored")
            m_quality.append(1.0 if attempt.resolved else 0.0)
            b_quality.append(1.0 if base[i].resolved else 0.0)
            if base[i].weighted_tokens is not None:
                m_total += attempt.weighted_tokens or 0.0
                b_total += base[i].weighted_tokens
    m_mean, b_mean = sum(m_quality) / len(m_quality), sum(b_quality) / len(b_quality)
    if m_mean < b_mean - max(0.0, epsilon):
        return Verdict(True, False, f"quality {m_mean:.3f} < baseline {b_mean:.3f} - {epsilon}")
    ratio = savings_ratio(b_total, m_total)
    if ratio is not None and ratio < min(1.0, max(0.0, required_saving)):
        return Verdict(True, False, f"savings {ratio:.3f} < {required_saving}", ratio)
    return Verdict(True, True, "passed", ratio)


def required_passes(task_count: int, pass_ratio: float, min_passed: int) -> int:
    if task_count <= 0:
        return 0
    required = max(math.ceil(task_count * min(1.0, max(0.0, pass_ratio))), max(0, min_passed))
    return min(task_count, max(1, required))


def stage2(
    miner: dict[str, list[Attempt]],
    baseline: dict[str, list[Attempt]],
    *,
    pass_ratio: float = _G["stage2_pass_ratio"],
    min_passed: int = _G["stage2_min_passed_tasks"],
    required_saving: float = _G["stage2_min_weighted_token_saving_ratio"],
) -> Verdict:
    """A task passes on a strict majority of resolved attempts; enough tasks must pass
    and pooled weighted savings must reach the threshold.

    A resolved attempt without token metrics is incomplete; an unresolved one counts as
    zero tokens, as upstream does.
    """
    if not miner:
        return Verdict(True, True, "no stage-2 tasks")
    passed_tasks = 0
    m_total = b_total = 0.0
    for task, attempts in miner.items():
        base = baseline.get(task, [])
        resolved_flags = []
        for i, attempt in enumerate(attempts):
            if attempt.resolved is None:
                return Verdict(False, False, f"miner attempt {task}#{i + 1} not scored")
            if i >= len(base) or base[i].weighted_tokens is None:
                return Verdict(False, False, f"baseline tokens {task}#{i + 1} missing")
            tokens = attempt.weighted_tokens
            if tokens is None:
                if attempt.resolved:
                    return Verdict(False, False, f"resolved attempt {task}#{i + 1} has no tokens")
                tokens = 0.0
            m_total += tokens
            b_total += base[i].weighted_tokens
            resolved_flags.append(bool(attempt.resolved))
        if sum(resolved_flags) > len(resolved_flags) // 2:
            passed_tasks += 1
    needed = required_passes(len(miner), pass_ratio, min_passed)
    if passed_tasks < needed:
        return Verdict(True, False, f"{passed_tasks} tasks passed < {needed} required")
    ratio = savings_ratio(b_total, m_total)
    if ratio is None:
        return Verdict(True, False, "no baseline tokens")
    threshold = min(1.0, max(0.0, required_saving))
    if ratio < threshold:
        return Verdict(True, False, f"savings {ratio:.4f} < {threshold}", ratio)
    return Verdict(True, True, "passed", ratio)
