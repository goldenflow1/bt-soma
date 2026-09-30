from __future__ import annotations

from pathlib import Path

import pytest

from harness import ROOT, upstream

FIXTURES = sorted((ROOT / "fixtures" / "synthetic").glob("*.json"))
MINER = ROOT / "src" / "soma_miner" / "miner.py"


class Settings:
    """Stand-in for the platform settings object, holding the lock's defaults."""

    def __init__(self) -> None:
        lock = upstream.load_lock()
        weights, screening = lock["scoring"]["token_weights"], lock["screening"]
        self.swebench_screening_input_tokens_weight = weights["input"]
        self.swebench_screening_cached_input_tokens_weight = weights["cached_input"]
        self.swebench_screening_output_tokens_weight = weights["output"]
        self.swebench_screening_pass_ratio = screening["stage2_pass_ratio"]
        self.swebench_screening_min_passed_tasks = screening["stage2_min_passed_tasks"]
        self.swebench_screening_min_weighted_token_saving_ratio = screening["stage2_min_weighted_token_saving_ratio"]
        self.swebench_screening_stage1_quality_epsilon_verified = screening["stage1_quality_epsilon"]
        self.swebench_screening_stage1_token_saving_ratio_verified = screening["stage1_token_saving_ratio"]


@pytest.fixture(scope="session")
def upstream_ready() -> None:
    """Parity tests need the pinned checkouts; run `python -m harness lock fetch` first."""
    problems = upstream.verify()
    if problems or not all(upstream.is_available(k) for k in ("soma", "soma_benchmark")):
        pytest.skip("pinned upstream checkouts missing or modified: " + "; ".join(problems or ["not fetched"]))


@pytest.fixture(scope="session")
def fixtures() -> list[Path]:
    return FIXTURES
