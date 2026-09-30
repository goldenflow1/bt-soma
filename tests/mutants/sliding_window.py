"""Masks every tool result except the newest one -> R-007 (moving boundary breaks the prefix)."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    tool_indices = [i for i, m in enumerate(out) if m.get("role") == "tool" and isinstance(m.get("content"), str)]
    for i in tool_indices[:-1]:
        out[i]["content"] = "[[Omitted]]"
    return out
