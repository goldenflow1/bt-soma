"""Inserts non-allowlisted text into tool results -> R-012."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    for m in out:
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            m["content"] = "Note: output summarized.\n" + m["content"]
    return out
