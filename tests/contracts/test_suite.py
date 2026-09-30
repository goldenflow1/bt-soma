"""The contract suite accepts the identity miner and a legitimate control, and rejects mutants."""

from __future__ import annotations

import json

import pytest

from harness import ROOT
from harness.contracts import (
    check_inserted_text,
    derive_requests,
    load_fixture,
    marker_patterns,
    run_suite,
    validate_fixture,
)
from harness.upstream import load_lock
from tests.conftest import FIXTURES, MINER

MUTANTS = ROOT / "tests" / "mutants"

# Each mutant must be rejected, and at least for the requirement it was built to break.
EXPECTED = {
    "alter_assistant": "R-003",
    "alter_later_user": "R-003",
    "change_arguments": "R-003",
    "drop_tool_result": "R-004",
    "reorder_messages": "R-004",
    "foreign_text": "R-012",
    "paraphrase_line": "R-012",
    "grows_output": "R-010",
    "drops_evidence": "R-011",
    "mutates_input": "R-002",
    "warm_state": "R-006",
    "sliding_window": "R-007",
    "crash": "R-009",
    "slow": "R-017",
    "returns_dict": "R-001",
    "wrong_entry_point": "R-001",
}


def test_every_mutant_file_has_an_expectation():
    assert {p.stem for p in MUTANTS.glob("*.py")} == set(EXPECTED)


def test_identity_miner_passes_all_contracts():
    report = run_suite(MINER, FIXTURES)
    assert report.findings == []
    assert report.stats["calls"] >= 10
    assert report.stats["bytes_out"] == report.stats["bytes_in"]


def test_positive_control_passes_and_compresses():
    report = run_suite(ROOT / "tests" / "controls" / "progress_filter.py", FIXTURES)
    assert report.findings == []
    assert report.stats["bytes_out"] < report.stats["bytes_in"]


@pytest.mark.parametrize("mutant", sorted(EXPECTED))
def test_mutant_is_rejected_for_its_requirement(mutant):
    report = run_suite(MUTANTS / f"{mutant}.py", FIXTURES, per_call_timeout_s=1.0)
    requirements = {finding.requirement for finding in report.findings}
    assert not report.passed
    assert EXPECTED[mutant] in requirements, report.to_dict()["findings"]


def test_fixtures_are_valid_and_exercise_the_stripped_view():
    for path in FIXTURES:
        fixture = load_fixture(path)
        assert validate_fixture(fixture) == []
        assert fixture.provenance["kind"] == "synthetic"


def test_fixture_with_credential_is_rejected(tmp_path):
    data = json.loads(FIXTURES[0].read_text())
    data["payload"]["messages"][1]["content"] += " key sk-or-v1-abcdef0123456789"
    path = tmp_path / "leaky.json"
    path.write_text(json.dumps(data))
    assert any("credential" in f.detail for f in validate_fixture(load_fixture(path)))


def test_derive_requests_waits_for_all_parallel_tool_results():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "1"},
        {"role": "tool", "tool_call_id": "b", "content": "2"},
        {"role": "assistant", "content": "done"},
    ]
    requests = derive_requests({"messages": messages})
    assert [len(r["messages"]) for r in requests] == [2, 5]


@pytest.mark.parametrize(
    ("original", "compressed", "ok"),
    [
        ("a\nb\nc", "a\n[[Omitted]]\nc", True),
        ("a\nb\nc", "a\n[[Omitted]] source line 2 ~ source line 2 Omitted [[/Omitted]]\nc", True),
        ("a\nb\nc", "[[BLOCK 3]]\na\nb\nc\n[[/BLOCK 3]]", True),
        ("a\nb\nc", "Same response as in [[BLOCK 12]].", True),
        ("a\nb\nc", "c\na", False),  # reordered
        ("a\nb\nc", "a\na\nb\nc", False),  # duplicated
        ("a\nb\nc", "a\n[[Removed]]\nc", False),  # not allowlisted
        ("a\nb\nc", "a\n[[BLOCK X]]\nc", False),  # placeholder must be a number
        ("a\nb\nc", "a\nloop_detected: repeated tool call signature", False),  # guard text is not a marker
    ],
)
def test_inserted_text_rules(original, compressed, ok):
    patterns = marker_patterns(load_lock()["allowed_insertions"]["markers"])
    assert (check_inserted_text(original, compressed, patterns) is None) is ok
