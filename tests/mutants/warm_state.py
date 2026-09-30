"""Output depends on how many calls this process has served -> R-006 (warm vs cold)."""
import copy

_CALLS = 0


def compress_messages(messages=None, path=None, metadata=None):
    global _CALLS
    _CALLS += 1
    out = copy.deepcopy(messages)
    if _CALLS > 2:
        for m in out:
            if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > 200:
                m["content"] = "[[Omitted]]"
    return out
