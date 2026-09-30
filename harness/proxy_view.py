"""Harness copy of the SOMA proxy's view of a request (R-021).

Production path (SOMA-benchmark, pinned in the lock):

    agent request payload
      -> proxy strips system/developer messages, the first user message and the
         top-level `system` field
      -> compression service calls the miner with the stripped `messages`
      -> compression service writes the miner's result back into the payload
      -> proxy restores the stripped messages at their original indices and
         drops any system/developer message the miner added

Every fixture, replay and contract check goes through these functions so the
miner is tested on exactly what it receives in production. Parity with the
upstream functions is tested in tests/contracts/test_proxy_view_parity.py.
"""

from __future__ import annotations

import copy
from typing import Any

PROTECTED_ROLES = frozenset({"system", "developer"})


def strip_protected(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (stripped_payload, protected) exactly as the proxy computes them."""
    protected_messages: list[tuple[int, Any]] = []
    remaining: list[Any] = []
    first_user_seen = False
    messages = payload.get("messages")
    if isinstance(messages, list):
        for index, message in enumerate(messages):
            role = message.get("role") if isinstance(message, dict) else None
            if role in PROTECTED_ROLES:
                protected_messages.append((index, message))
            elif role == "user" and not first_user_seen:
                first_user_seen = True
                protected_messages.append((index, message))
            else:
                remaining.append(message)

    stripped = dict(payload)
    if isinstance(messages, list):
        stripped["messages"] = remaining
    system_field = stripped.pop("system", None)
    return stripped, {"messages": protected_messages, "system": system_field}


def restore_protected(payload: dict[str, Any], protected: dict[str, Any]) -> dict[str, Any]:
    """Reinsert protected messages as the proxy does after compression."""
    restored = dict(payload)
    messages = restored.get("messages")
    kept = [
        message
        for message in (messages if isinstance(messages, list) else [])
        if not (isinstance(message, dict) and message.get("role") in PROTECTED_ROLES)
    ]
    for index, message in protected["messages"]:
        kept.insert(min(index, len(kept)), message)
    if kept or protected["messages"]:
        restored["messages"] = kept
    if protected["system"] is not None:
        restored["system"] = protected["system"]
    return restored


def apply_result(payload: dict[str, Any], result: Any) -> dict[str, Any]:
    """Write a miner's return value back into the payload (COMPRESSION_MUTATE_REQUEST=true).

    Mirrors compression_service `_invoke_compressor`: a list replaces `messages`;
    a dict with a `messages` list replaces `messages`; any other dict replaces
    the whole payload; anything else leaves the payload unchanged.
    """
    if isinstance(result, list):
        updated = dict(payload)
        updated["messages"] = result
        return updated
    if isinstance(result, dict):
        if isinstance(result.get("messages"), list):
            updated = dict(payload)
            updated["messages"] = result["messages"]
            return updated
        return result
    return payload


def compressor_view(payload: dict[str, Any]) -> list[Any]:
    """The `messages` list the miner receives for this request."""
    stripped, _ = strip_protected(copy.deepcopy(payload))
    messages = stripped.get("messages")
    return messages if isinstance(messages, list) else []


def round_trip(payload: dict[str, Any], miner_result: Any) -> dict[str, Any]:
    """Final upstream request after the miner returned `miner_result` for `payload`."""
    stripped, protected = strip_protected(copy.deepcopy(payload))
    return restore_protected(apply_result(stripped, miner_result), protected)
