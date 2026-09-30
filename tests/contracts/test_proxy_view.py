"""The harness copy of the proxy matches upstream behavior (R-021)."""

from __future__ import annotations

import copy
import inspect
import json
import os

import pytest

from harness import proxy_view, upstream
from tests.conftest import FIXTURES

PAYLOADS = [json.loads(p.read_text())["payload"] for p in FIXTURES] + [
    # Anthropic-style top-level system field and content blocks.
    {"system": "sys", "messages": [{"role": "user", "content": [{"type": "text", "text": "task"}]}, {"role": "assistant", "content": "ok"}]},
    # Developer role, several user messages, a non-dict entry.
    {"messages": [{"role": "developer", "content": "d"}, {"role": "user", "content": "u1"}, {"role": "user", "content": "u2"}, "junk", {"role": "system", "content": "s2"}]},
    {"messages": []},
    {"prompt": "no messages key"},
]
RESULTS = [
    lambda msgs: msgs,
    lambda msgs: msgs[1:],
    lambda msgs: [{"role": "system", "content": "injected"}] + list(msgs),
    lambda msgs: {"messages": list(msgs)},
    lambda msgs: {"model": "replaced"},
    lambda msgs: None,
]


def test_first_user_message_and_system_roles_are_hidden_from_the_miner():
    payload = json.loads(FIXTURES[0].read_text())["payload"]
    view = proxy_view.compressor_view(payload)
    assert all(m["role"] not in ("system", "developer") for m in view)
    assert payload["messages"][1]["content"] not in [m.get("content") for m in view]
    assert view[0]["role"] == "assistant"


def test_round_trip_of_identity_restores_chat_payloads():
    for payload in PAYLOADS:
        if not isinstance(payload.get("messages"), list):
            continue
        view = proxy_view.compressor_view(payload)
        assert proxy_view.round_trip(payload, view) == payload


def test_list_result_adds_messages_to_a_payload_without_them():
    """Upstream hazard (F-002 input): a non-chat JSON body reaches the miner as [], and
    returning a list writes `messages: []` into it. Returning None leaves it untouched."""
    payload = {"prompt": "no messages key"}
    assert proxy_view.round_trip(payload, []) == {"prompt": "no messages key", "messages": []}
    assert proxy_view.round_trip(payload, None) == payload


@pytest.mark.upstream
def test_strip_and_restore_match_upstream(upstream_ready):
    ns = upstream.load_symbols(
        "soma_benchmark",
        "src/compression_service/app/proxy.py",
        ["_PROTECTED_MESSAGE_ROLES", "_strip_protected_prompts", "_restore_protected_prompts"],
        {"Any": object},
    )
    for payload in PAYLOADS:
        ours_stripped, ours_protected = proxy_view.strip_protected(copy.deepcopy(payload))
        theirs_stripped, theirs_protected = ns["_strip_protected_prompts"](copy.deepcopy(payload))
        assert ours_stripped == theirs_stripped
        assert ours_protected == theirs_protected
        for make_result in RESULTS:
            if not isinstance(ours_stripped.get("messages"), list):
                continue
            result = make_result(ours_stripped["messages"])
            ours = proxy_view.restore_protected(proxy_view.apply_result(ours_stripped, result), ours_protected)
            theirs = ns["_restore_protected_prompts"](proxy_view.apply_result(theirs_stripped, result), theirs_protected)
            assert ours == theirs


@pytest.mark.upstream
def test_result_application_matches_the_compression_service(upstream_ready):
    for make_result in RESULTS:
        payload = {"model": "m", "messages": [{"role": "tool", "tool_call_id": "a", "content": "x"}]}

        def miner(messages=None, path=None, metadata=None, _make=make_result):
            return _make(messages)

        ns = upstream.load_symbols(
            "soma_benchmark",
            "src/compression_service/app/main.py",
            ["_coerce_bool", "_extract_messages", "_invoke_compressor"],
            {"Any": object, "os": os, "inspect": inspect, "_COMPRESSOR_FN": miner},
        )
        theirs = ns["_invoke_compressor"](copy.deepcopy(payload), path="/chat/completions")
        ours = proxy_view.apply_result(copy.deepcopy(payload), miner(copy.deepcopy(payload["messages"])))
        assert ours == theirs
