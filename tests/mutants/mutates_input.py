"""Mutates its input in place -> R-002."""


def compress_messages(messages=None, path=None, metadata=None):
    for m in messages:
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            m["content"] = "[[Omitted]]"
    return messages
