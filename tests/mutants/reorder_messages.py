"""Swaps the last two messages -> R-004."""


def compress_messages(messages=None, path=None, metadata=None):
    out = list(messages)
    if len(out) >= 2:
        out[-1], out[-2] = out[-2], out[-1]
    return out
