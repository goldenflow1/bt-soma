"""Rewrites tool-call arguments -> R-003."""
import copy


def compress_messages(messages=None, path=None, metadata=None):
    out = copy.deepcopy(messages)
    for m in out:
        for tc in m.get("tool_calls") or []:
            tc["function"]["arguments"] = "{}"
    return out
