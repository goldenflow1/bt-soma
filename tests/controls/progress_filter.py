"""Positive control: a minimal legitimate compressor the harness must accept.

Collapses runs of pytest progress lines into one allowlisted marker. The
transformation depends only on each tool result's own text, so it is
deterministic and prefix-stable. Harness test data, not miner code.
"""

import copy
import re

_PROGRESS = re.compile(r"^\S+\.py [.sFEx]+\s+\[\s*\d+%\]$")


def compress_messages(messages=None, path=None, metadata=None):
    if not isinstance(messages, list):
        return []
    out = copy.deepcopy(messages)
    for message in out:
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            message["content"] = _collapse(message["content"])
    return out


def _collapse(text):
    lines, kept, in_run = text.split("\n"), [], False
    for line in lines:
        if _PROGRESS.match(line):
            if not in_run:
                kept.append("[[Omitted]]")
            in_run = True
        else:
            kept.append(line)
            in_run = False
    return "\n".join(kept)
