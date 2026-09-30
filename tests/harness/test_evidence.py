"""Evidence, run-record, budget and attempt-state rules (sections 24 and 26)."""

from __future__ import annotations

import json

import pytest

from harness import evidence
from harness.budget import load_budget
from harness.evidence import AttemptState, Receipt
from harness.runs import Completion, RunRecord, Usage, normalize_openai_usage
from harness.scoring import Run


def test_tree_digest_is_stable_and_content_sensitive(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2\n")
    first = evidence.digest_path(tmp_path)
    assert evidence.digest_path(tmp_path) == first
    (tmp_path / "sub" / "b.py").write_text("y = 3\n")
    assert evidence.digest_path(tmp_path) != first


def test_manifest_is_immutable(tmp_path):
    evidence.write_manifest(tmp_path, {"experiment_id": "x"})
    with pytest.raises(FileExistsError):
        evidence.write_manifest(tmp_path, {"experiment_id": "x"})


def test_receipt_refuses_missing_inputs(tmp_path):
    receipt = Receipt("contracts", "check", {"does/not/exist.py": "0" * 64}, {}, True, "", "t0", "t1")
    with pytest.raises(FileNotFoundError):
        evidence.write_receipt(tmp_path, receipt)


def test_receipt_refuses_changed_inputs(tmp_path):
    receipt = Receipt("contracts", "check", {"src/soma_miner/miner.py": "0" * 64}, {}, True, "", "t0", "t1")
    with pytest.raises(ValueError):
        evidence.write_receipt(tmp_path, receipt)


def test_resume_detects_changed_digests(tmp_path):
    evidence.write_manifest(tmp_path, {"experiment_id": "x"})
    assert evidence.resume_check(tmp_path) == []
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["digests"]["candidate_src"] = "stale"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert evidence.resume_check(tmp_path) == ["candidate_src changed since the manifest was written"]


def test_attempt_state_machine_and_repair_budget(tmp_path):
    state = AttemptState(tmp_path / "attempt.json", max_repairs=3)
    state.transition("IMPLEMENTING", "start")
    state.transition("CHECKING", "run gates")
    for _ in range(3):
        state.transition("REPAIRING", "gate failed")
        state.transition("CHECKING", "rerun")
    with pytest.raises(RuntimeError):
        state.transition("REPAIRING", "fourth repair")
    with pytest.raises(ValueError):
        state.transition("READY", "illegal jump")
    assert AttemptState(tmp_path / "attempt.json", max_repairs=3).data["repairs"] == 3


def test_openai_usage_normalization_avoids_double_counting():
    usage = normalize_openai_usage({"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 800}})
    assert (usage.uncached_input, usage.cached_input, usage.output) == (200, 800, 50)
    assert normalize_openai_usage({"prompt_tokens": 10, "completion_tokens": 1}).cached_input == 0
    assert normalize_openai_usage({"completion_tokens": 1}) is None
    assert normalize_openai_usage({"prompt_tokens": 10, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 11}}) is None


def test_incomplete_runs_are_never_solves_and_missing_usage_is_never_zero():
    with pytest.raises(ValueError):
        RunRecord("candidate", "d", "t", "short", 0, Completion.INTERRUPTED, resolved=True)
    interrupted = RunRecord("candidate", "d", "t", "short", 0, Completion.INTERRUPTED)
    assert interrupted.scoring_run() is None
    no_usage = RunRecord("candidate", "d", "t", "short", 0, Completion.COMPLETED, resolved=True)
    assert no_usage.usage_missing
    assert no_usage.scoring_run() == Run(True, None, None, None)
    done = RunRecord("candidate", "d", "t", "short", 0, Completion.COMPLETED, resolved=False, usage=Usage(200, 800, 50, "openai"))
    assert done.scoring_run() == Run(False, 200, 800, 50)


def test_paid_runs_disabled_until_every_budget_is_set():
    budget = load_budget()
    assert budget.max_repair_cycles == 3
    assert not budget.paid_runs_allowed
    assert set(budget.missing_paid_fields()) == {"spend_ceiling_usd", "max_fresh_runs", "per_run_deadline_s", "experiment_deadline_s"}
