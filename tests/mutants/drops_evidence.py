"""Uses allowlisted markers but removes failure diagnostics -> R-011."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    for m in out:
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            lines = m["content"].split("\n")
            if len(lines) > 6:
                m["content"] = "\n".join(lines[:3] + ["[[Omitted]]"])
    return out
