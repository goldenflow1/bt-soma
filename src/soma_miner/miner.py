"""SOMA context-compression miner.

Entry point called by the SOMA compression service with the proxy-stripped
message list (no system/developer messages, no first user message).

F-001: identity. Behaves exactly like the official baseline so the harness can
be proven against a known-correct candidate before any compression exists.
Fail-open handling and the internal deadline arrive with F-002.
"""

from __future__ import annotations

from typing import Any


def compress_messages(
    messages: list[Any] | None = None,
    path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[Any]:
    del path, metadata
    if isinstance(messages, list):
        return messages
    return []
