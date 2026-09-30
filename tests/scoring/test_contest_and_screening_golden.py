"""Hand-computed contest (R-016) and screening (R-022) cases."""

from __future__ import annotations

import pytest

from harness import contest, screening
from harness.screening import Attempt

CATS = ("short", "medium", "long")
ABC = {
    "alice": {"short": 0.60, "medium": 0.50, "long": 0.20},
    "bob": {"short": 0.40, "medium": 0.55, "long": 0.45},
    "carol": {"short": 0.70, "long": 0.10},
}


def approx(value):
    return pytest.approx(value, abs=1e-12)


@pytest.mark.parametrize(
    ("burn", "final", "burned"),
    [
        (0.0, {"alice": 0.15, "bob": 0.75, "carol": 0.10}, 0.0),
        (0.5, {"alice": 0.075, "bob": 0.375, "carol": 0.05}, 0.5),
        (1.0, {}, 1.0),
    ],
)
def test_alice_bob_carol(burn, final, burned):
    result = contest.allocate(ABC, CATS, burn_ratio=burn)
    assert result.raw_weights == {k: approx(v) for k, v in {"alice": 0.15, "bob": 0.75, "carol": 0.10}.items()}
    assert result.final_weights == {k: approx(v) for k, v in final.items()}
    assert result.burn_weight == approx(burned)
    assert sum(result.final_weights.values()) + result.burn_weight == approx(1.0)


def test_exact_tie_splits_the_element():
    result = contest.allocate({"a": {"short": 0.5}, "b": {"short": 0.5}}, ("short",), burn_ratio=0.0)
    assert result.final_weights == {"a": approx(0.5), "b": approx(0.5)}


def test_tie_tolerance_is_1e_12():
    near = contest.allocate({"a": {"short": 0.5}, "b": {"short": 0.5 + 1e-13}}, ("short",), burn_ratio=0.0)
    far = contest.allocate({"a": {"short": 0.5}, "b": {"short": 0.5 + 1e-9}}, ("short",), burn_ratio=0.0)
    assert set(near.final_weights) == {"a", "b"}
    assert set(far.final_weights) == {"b"}


def test_two_categories_renormalize_layers():
    result = contest.allocate({"a": {"short": 0.9, "long": 0.1}, "b": {"short": 0.1, "long": 0.8}}, ("short", "long"), burn_ratio=0.0)
    weights = {e.subset: e.weight for e in result.elements}
    assert weights == {("short", "long"): approx(0.6), ("short",): approx(0.2), ("long",): approx(0.2)}
    assert result.final_weights == {"a": approx(0.8), "b": approx(0.2)}


def test_empty_elements_are_redistributed_not_burned():
    result = contest.allocate({"solo": {"short": 0.3}}, CATS, burn_ratio=0.5)
    assert result.raw_weights == {"solo": approx(0.10)}
    assert result.final_weights == {"solo": approx(0.5)}
    assert result.burn_weight == approx(0.5)


def test_nothing_classified_uses_the_fallback_element():
    result = contest.allocate({"a": {"overall": 0.2}, "b": {"overall": 0.4}}, (contest.FALLBACK,), burn_ratio=0.0)
    assert result.final_weights == {"b": approx(1.0)}


def test_present_categories_is_canonical_and_ignores_unknown_labels():
    assert contest.present_categories(["long", None, "Short", "huge", "long"]) == ("short", "long")


def runs(*pairs):
    return [Attempt(resolved, tokens) for resolved, tokens in pairs]


def baseline(n_tasks, n_attempts, tokens=100.0):
    return {f"t{i}": runs(*[(True, tokens)] * n_attempts) for i in range(n_tasks)}


def test_stage2_passes_at_exactly_ten_percent_savings():
    miner = {f"t{i}": runs((True, 90.0), (True, 90.0), (False, 90.0)) for i in range(4)}
    verdict = screening.stage2(miner, baseline(4, 3))
    assert verdict.passed and verdict.savings_ratio == approx(0.10)


def test_stage2_fails_just_below_ten_percent():
    miner = {f"t{i}": runs((True, 90.01), (True, 90.01), (True, 90.01)) for i in range(4)}
    assert not screening.stage2(miner, baseline(4, 3)).passed


def test_stage2_identity_miner_cannot_pass():
    miner = {f"t{i}": runs((True, 100.0), (True, 100.0), (True, 100.0)) for i in range(4)}
    verdict = screening.stage2(miner, baseline(4, 3))
    assert verdict.complete and not verdict.passed


def test_stage2_needs_majority_resolved_on_half_the_tasks():
    good = runs((True, 50.0), (True, 50.0), (False, 50.0))
    bad = runs((True, 50.0), (False, 50.0), (False, 50.0))
    assert screening.stage2({"t0": good, "t1": good, "t2": bad, "t3": bad}, baseline(4, 3)).passed
    assert not screening.stage2({"t0": good, "t1": bad, "t2": bad, "t3": bad}, baseline(4, 3)).passed


def test_stage2_missing_token_rules():
    unresolved_no_tokens = {"t0": runs((True, 50.0), (True, 50.0), (False, None))}
    assert screening.stage2(unresolved_no_tokens, baseline(1, 3)).savings_ratio == approx(1 - 100 / 300)
    resolved_no_tokens = {"t0": runs((True, None), (True, 50.0), (True, 50.0))}
    assert not screening.stage2(resolved_no_tokens, baseline(1, 3)).complete


def test_stage1_quality_tolerance_and_zero_savings_floor():
    base = {f"t{i}": runs(*[(True, 100.0)] * 4 + [(False, 100.0)]) for i in range(4)}  # pooled 0.80
    within = {f"t{i}": runs(*[(True, 90.0)] * 4 + [(False, 90.0)]) for i in range(3)}
    within["t3"] = runs(*[(True, 90.0)] * 3 + [(False, 90.0)] * 2)  # pooled 0.75 = 0.80 - 0.05
    assert screening.stage1(within, base).passed
    worse = dict(within, t2=runs(*[(True, 90.0)] * 3 + [(False, 90.0)] * 2))  # pooled 0.70
    assert not screening.stage1(worse, base).passed
    costlier = {f"t{i}": runs(*[(True, 110.0)] * 4 + [(False, 110.0)]) for i in range(4)}
    assert not screening.stage1(costlier, base).passed  # savings must not be negative
