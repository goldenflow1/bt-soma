"""Repeats the first line of each tool result -> R-010 (payload grows)."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    for m in out:
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            first = m["content"].split("\n", 1)[0]
            m["content"] = first + "\n" + m["content"]
    return out
