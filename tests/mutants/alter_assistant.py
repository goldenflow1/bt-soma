"""Alters assistant text (an instruction-bearing message) -> R-003."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    for m in out:
        if m.get("role") == "assistant":
            m["content"] = (m.get("content") or "") + " Be brief."
            break
    return out
