"""Parity between harness scoring and the pinned upstream functions (R-015, R-016, R-022)."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import itertools
import math
import random
from datetime import datetime, timezone
from itertools import combinations
from math import ceil, isclose, log2
from typing import Mapping, Sequence

import pytest

from harness import contest, screening, scoring, upstream
from harness.scoring import Run
from tests.conftest import Settings

pytestmark = pytest.mark.upstream

SCORING_PY = "mcp_platform/app/api/routes/scoring.py"
INCENTIVE_PY = "mcp_platform/app/services/incentive_calculator.py"
SCREENING_PY = "mcp_platform/app/services/swebench_screening.py"
CONFIG_PY = "mcp_platform/app/core/config.py"


@pytest.fixture(scope="module")
def up_scoring(upstream_ready):
    return upstream.load_symbols(
        "soma",
        SCORING_PY,
        [
            "SCORING_R_MIN", "SCORING_R_MAX", "SCORING_BONUS_MAX", "SCORING_BONUS_MIN_EXTRA",
            "SCORING_QUALITY_PENALTY_ONLY_RATIO", "SCORING_QUALITY_TOKEN_SCORE_RATIO",
            "SWE_SCORE_MIN", "SWE_SCORE_MAX", "_scoring_token_weights", "compute_weighted_tokens",
            "_normalize_to_unit_interval", "_compression_ratio", "_quality_token_score_threshold",
            "_quality_adjusted_score", "_bonus_component", "compute_swe_task_score", "_task_inputs",
            "build_swe_task_scores", "build_swe_miner_scores", "build_swe_miner_total_score",
        ],
        {"ceil": ceil, "log2": log2, "settings": Settings(), "Any": object},
    )


def test_lock_constants_match_upstream(up_scoring):
    lock = upstream.load_lock()["scoring"]
    assert (lock["r_min"], lock["r_max"]) == (up_scoring["SCORING_R_MIN"], up_scoring["SCORING_R_MAX"])
    assert lock["bonus_max"] == up_scoring["SCORING_BONUS_MAX"]
    assert lock["bonus_min_extra"] == up_scoring["SCORING_BONUS_MIN_EXTRA"]
    assert lock["quality_penalty_only_ratio"] == up_scoring["SCORING_QUALITY_PENALTY_ONLY_RATIO"]
    assert lock["quality_token_score_ratio"] == up_scoring["SCORING_QUALITY_TOKEN_SCORE_RATIO"]
    assert (lock["task_score_min"], lock["task_score_max"]) == (up_scoring["SWE_SCORE_MIN"], up_scoring["SWE_SCORE_MAX"])


def test_lock_screening_defaults_match_upstream_config(upstream_ready):
    defaults = _config_defaults()
    lock = upstream.load_lock()
    assert defaults["swebench_screening_pass_ratio"] == lock["screening"]["stage2_pass_ratio"]
    assert defaults["swebench_screening_min_passed_tasks"] == lock["screening"]["stage2_min_passed_tasks"]
    assert defaults["swebench_screening_min_weighted_token_saving_ratio"] == lock["screening"]["stage2_min_weighted_token_saving_ratio"]
    assert defaults["swebench_screening_stage1_quality_epsilon_verified"] == lock["screening"]["stage1_quality_epsilon"]
    assert defaults["swebench_screening_stage1_token_saving_ratio_verified"] == lock["screening"]["stage1_token_saving_ratio"]
    weights = lock["scoring"]["token_weights"]
    assert defaults["swebench_screening_input_tokens_weight"] == weights["input"]
    assert defaults["swebench_screening_cached_input_tokens_weight"] == weights["cached_input"]
    assert defaults["swebench_screening_output_tokens_weight"] == weights["output"]


TOKENS = [None, 0.0, 50.0, 100.0, 141.4, 400.0, 1000.0]


def test_task_score_matches_on_a_grid(up_scoring):
    for x, y, n in itertools.product(range(7), range(8), range(1, 9)):
        for tb, ta in itertools.product(TOKENS, TOKENS):
            theirs = up_scoring["compute_swe_task_score"](x, y, tb, ta, task_run_count=n)
            ours = scoring.task_score(x, y, tb, ta, n)
            assert (ours.pool, ours.zone) == (theirs["pool"], theirs["zone"]), (x, y, n, tb, ta)
            assert _same(ours.score, theirs["score"]) and _same(ours.r, theirs["r"])
            assert _same(ours.hard_boost_contribution, theirs["hard_boost_contribution"])


def test_miner_totals_match_on_random_task_sets(up_scoring):
    rng = random.Random(20260930)
    for _ in range(300):
        groups, ours = {}, []
        for task_id in range(rng.randint(0, 12)):
            baseline = [_random_run(rng) for _ in range(rng.randint(1, 5))]
            miner = [_random_run(rng) for _ in range(rng.randint(1, 5))]
            groups[task_id] = _upstream_group(baseline, miner)
            ours.append(scoring.score_task_runs(baseline, miner))
        theirs, _ = up_scoring["build_swe_miner_total_score"](groups)
        assert _same(scoring.total_score(ours), theirs)


@pytest.fixture(scope="module")
def up_incentive(upstream_ready):
    return upstream.load_symbols(
        "soma",
        INCENTIVE_PY,
        [
            "Category", "BenchmarkType", "FALLBACK_CATEGORY", "LAYER_WEIGHTS_BY_SUBSET_SIZE",
            "IncentiveElementResult", "IncentiveLayerResult", "IncentiveCalculationResult",
            "_normalize_categories", "build_incentive_layers", "_layer_weights_for", "_category_weight",
            "_subset_weighted_score", "calculate_incentive_weights",
        ],
        {
            "dataclass": dataclasses.dataclass, "combinations": combinations, "isclose": isclose,
            "Mapping": Mapping, "Sequence": Sequence,
            "COMPLEXITY_WEIGHTS": {"short": 1.0, "medium": 1.0, "long": 1.0},
        },
    )


def test_incentive_allocation_matches(up_incentive):
    assert {int(k): v for k, v in upstream.load_lock()["incentives"]["layer_weights_by_subset_size"].items()} == up_incentive["LAYER_WEIGHTS_BY_SUBSET_SIZE"]
    assert contest.FALLBACK == up_incentive["FALLBACK_CATEGORY"]
    rng = random.Random(7)
    category_sets = [("short", "medium", "long"), ("short", "long"), ("medium",), ("overall",)]
    for _ in range(400):
        cats = rng.choice(category_sets)
        scores = {}
        for miner in range(rng.randint(0, 6)):
            scores[f"m{miner}"] = {c: rng.choice([0.1, 0.25, 0.5, rng.uniform(-1, 1)]) for c in cats if rng.random() > 0.2}
        burn = rng.choice([0.0, 0.5, 1.0, rng.random()])
        theirs = up_incentive["calculate_incentive_weights"](scores, cats, burn_ratio=burn)
        ours = contest.allocate(scores, cats, burn_ratio=burn)
        assert ours.raw_weights == pytest.approx(theirs.raw_weights, abs=1e-12)
        assert ours.final_weights == pytest.approx(theirs.final_weights, abs=1e-12)
        assert ours.burn_weight == pytest.approx(theirs.burn_weight, abs=1e-12)


@pytest.fixture(scope="module")
def up_screening(upstream_ready):
    return upstream.load_symbols(
        "soma",
        SCREENING_PY,
        [
            "SCREENING_BENCHMARK_TYPES", "STAGE1_GATED_BENCHMARK_TYPES", "evaluate_screening_for_script",
            "required_screening_task_passes", "required_screening_weighted_token_saving_ratio",
            "stage1_quality_epsilon_for_benchmark_type", "stage1_required_token_saving_ratio_for_benchmark_type",
            "evaluate_stage1_for_script", "compute_weighted_token_savings_ratio",
        ],
        {"math": math, "datetime": datetime, "settings": Settings()},
    )


def test_screening_matches(up_screening):
    rng = random.Random(11)
    bt = "swebench_verified"
    stamp = datetime(2026, 9, 30, tzinfo=timezone.utc)
    for _ in range(500):
        n_tasks, repeats = rng.randint(1, 6), rng.randint(1, 5)
        miner, base = {}, {}
        up_miner2, up_miner1, up_base_w, up_base_q, up_miner_w = {}, {}, {}, {}, {}
        for t in range(n_tasks):
            miner[f"t{t}"], base[f"t{t}"] = [], []
            for a in range(1, repeats + 1):
                b_res = rng.random() < 0.7
                b_tok = rng.choice([80.0, 100.0, 120.0])
                m_res = rng.random() < 0.65
                m_tok = rng.choice([None, 60.0, 90.0, 100.0, 130.0]) if not m_res else rng.choice([60.0, 90.0, 100.0])
                miner[f"t{t}"].append(screening.Attempt(m_res, m_tok))
                base[f"t{t}"].append(screening.Attempt(b_res, b_tok))
                key = (t, a, bt)
                up_miner2[key] = (m_res, stamp, m_tok)
                up_miner1[key] = (1.0 if m_res else 0.0, stamp)
                up_base_w[key], up_base_q[key], up_miner_w[key] = b_tok, 1.0 if b_res else 0.0, m_tok
        ids, repeats_map = list(range(n_tasks)), {t: repeats for t in range(n_tasks)}

        complete2, passed2 = asyncio.run(up_screening["evaluate_screening_for_script"](
            screener_task_ids=ids, task_repeats=repeats_map, baseline_weighted_by_task_attempt=up_base_w,
            screening_by_task_attempt=up_miner2, benchmark_types=(bt,)))
        ours2 = screening.stage2(miner, base)
        assert (ours2.complete, ours2.passed) == (complete2, passed2)

        complete1, passed1 = asyncio.run(up_screening["evaluate_stage1_for_script"](
            stage1_task_ids=ids, task_repeats=repeats_map, benchmark_types=(bt,),
            baseline_quality_by_task_attempt=up_base_q, stage1_quality_by_task_attempt=up_miner1,
            baseline_weighted_by_task_attempt=up_base_w, stage1_weighted_by_task_attempt=up_miner_w))
        ours1 = screening.stage1(miner, base)
        assert (ours1.complete, ours1.passed) == (complete1, passed1)


# ── helpers ──────────────────────────────────────────────────────────────────


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-12)


def _random_run(rng: random.Random) -> Run:
    if rng.random() < 0.1:
        return Run(rng.random() < 0.5, None, None, None)
    return Run(
        rng.random() < 0.6,
        rng.randint(0, 50_000),
        rng.choice([None, 0, rng.randint(0, 200_000)]),
        rng.randint(0, 5_000),
    )


def _upstream_group(baseline: list[Run], miner: list[Run]) -> dict:
    return {
        "baseline_runs": {
            i: {"resolved": r.resolved, "input_tokens": r.input_tokens, "cached_input_tokens": r.cached_input_tokens, "output_tokens": r.output_tokens}
            for i, r in enumerate(baseline)
        },
        "runs": [
            {"pass_with_compression": r.resolved, "weighted_tokens_with_compression": scoring.weighted_tokens(r.input_tokens, r.cached_input_tokens, r.output_tokens)}
            for r in miner
        ],
    }


def _config_defaults() -> dict[str, float]:
    tree = ast.parse((upstream.checkout_dir("soma") / CONFIG_PY).read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and isinstance(node.value, ast.Call):
            default = next((kw.value for kw in node.value.keywords if kw.arg == "default"), None)
            if default is not None and node.target.id.startswith("swebench_screening"):
                found[node.target.id] = eval(compile(ast.Expression(default), CONFIG_PY, "eval"), {"__builtins__": {}})  # noqa: S307 - numeric literals from pinned source
    return found
