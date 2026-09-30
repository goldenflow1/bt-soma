"""Loses tool results -> R-004."""


def compress_messages(messages=None, path=None, metadata=None):
    return [m for m in messages if m.get("role") != "tool"]
