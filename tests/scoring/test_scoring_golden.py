"""Hand-computed scoring cases (R-015). Expected values are written out, not derived from harness code."""

from __future__ import annotations

from math import log2

import pytest

from harness import scoring
from harness.scoring import Run, task_score

C4, C5 = 4 ** (1 / 3), 5 ** (1 / 3)


def approx(value):
    return pytest.approx(value, abs=1e-12)


def test_weighted_tokens():
    assert scoring.weighted_tokens(1000, 5000, 100) == approx(1000 + 500 + 300)
    assert scoring.weighted_tokens(1000, None, 100) == approx(1300)  # missing cached counts as 0
    assert scoring.weighted_tokens(None, 10, 100) is None
    assert scoring.weighted_tokens(1000, 10, None) is None
    assert scoring.weighted_tokens(-1, 0, 0) is None


@pytest.mark.parametrize(
    ("tb", "ta", "r"),
    [(100, 50, 1.0), (100, 25, 2.0), (100, 10, 2.0), (100, 400, -2.0), (100, 100, 0.0), (None, 50, 0.0), (100, 0, 0.0)],
)
def test_compression_ratio(tb, ta, r):
    assert scoring.compression_ratio(tb, ta) == approx(r)


@pytest.mark.parametrize(
    ("x", "y", "r", "score", "zone"),
    [
        (5, 0, 1.0, -2.0, "penalty"),
        (4, 2, 1.0, -1.0, "penalty"),  # 50% quality
        (5, 3, 1.0, -1 / 3, "penalty"),  # 60%: one third of the way from -1 to r
        (10, 7, 1.0, (1 / 3) * -1 + (2 / 3) * 1.0, "penalty"),  # 70%
        (5, 4, 1.0, 1.0, "maintain"),  # 80%
        (4, 4, -0.5, -0.5, "maintain"),
    ],
)
def test_standard_task_quality_curve(x, y, r, score, zone):
    tokens_b, tokens_a = 1000.0, 1000.0 / 2**r
    result = task_score(x, y, tokens_b, tokens_a, n=10)
    assert result.pool == "main"
    assert (result.score, result.zone) == (approx(score), zone)


def test_bonus_needs_two_extra_solves_and_is_small():
    assert task_score(2, 3, 200, 100, n=5).score == approx(1.0)  # one extra solve: no bonus
    beat = task_score(2, 5, 200, 100, n=5)  # extra 3 of headroom 3: full bonus
    assert (beat.score, beat.zone) == (approx(1.1), "bonus")
    assert task_score(2, 5, 400, 100, n=5).score == approx(2.0)  # capped at the task maximum


def test_hard_tasks():
    assert task_score(0, 0, 100, 50, n=5).pool == "excluded"
    assert task_score(1, 0, 100, 50, n=5).score is None
    same = task_score(1, 1, 100, 200, n=5)  # x = y = 1: score is r, boost floors at 0
    assert (same.score, same.hard_boost_contribution) == (approx(-1.0), approx(0.0))
    solved = task_score(0, 1, 100, 50, n=5)  # baseline never solved; r still applies
    assert (solved.pool, solved.score, solved.hard_boost_contribution) == ("hard_boost", approx(1.0), approx(1.0))
    lifted = task_score(1, 4, 100, 100, n=5)  # extra 3, headroom 4, progress 0.75
    assert lifted.score == approx(0.1 * 0.5**2)


def test_task_inputs_follow_the_platform():
    baseline = [Run(True, 1000, 0, 100), Run(False, 2000, 0, 0), Run(True, None, None, None)]
    miner = [Run(True, 500, 0, 50), Run(False, None, None, None), Run(True, 0, 0, 0)]
    result = scoring.score_task_runs(baseline, miner)
    # T_B averages every baseline run with valid tokens, resolved or not; T_A skips missing and zero.
    assert (result.x, result.y, result.n) == (2, 2, 3)
    assert result.baseline_tokens == approx((1300 + 2000) / 2)
    assert result.miner_tokens == approx(650)
    assert result.r == approx(log2(1650 / 650))


def test_normalization():
    assert scoring.normalize(3.0) == approx(1.0)
    assert scoring.normalize(-2.0) == approx(-1.0)
    assert scoring.normalize(0.5) == approx(0.25)


def test_worked_example_from_architecture_section_18_8():
    """A, B, C are main tasks, D is hard; n = 5 runs per task; r in the task tuples."""
    a = task_score(4, 4, 200, 100, n=5)  # r = 1, maintain
    b = task_score(4, 5, 200, 100, n=5)  # one extra solve: no bonus
    c = task_score(5, 3, 200, 100, n=5)  # 60% quality
    d = task_score(0, 1, 200 * 2**0.5, 200, n=5)  # r = 0.5
    assert [a.score, b.score, c.score, d.score] == [approx(1.0), approx(1.0), approx(-1 / 3), approx(0.5)]

    main = (1.0 * C4 + 1.0 * C4 + (-1 / 3) * C5) / (C4 + C4 + C5)
    hard = 0.5 / 4
    assert scoring.aggregate([a, b, c, d]) == (approx(main), approx(hard))
    assert scoring.total_score([a, b, c, d]) == approx((main + hard) / 2)
    assert round(scoring.total_score([a, b, c, d]), 4) == 0.3291

    c_ok = task_score(5, 5, 200, 100, n=5)
    assert scoring.total_score([a, b, c_ok, d]) == approx((1.0 + 0.125) / 2)


def test_empty_and_hard_only():
    assert scoring.total_score([]) is None
    only_hard = [task_score(0, 1, 100, 50, n=5)]
    assert scoring.aggregate(only_hard) == (approx(0.0), approx(1.0))
