"""Rewrites a line in place while shrinking -> R-012 (not an in-order subset of the original)."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    for m in out:
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            m["content"] = m["content"].replace("AssertionError", "AssertErr")
    return out
