"""Raises; production has no fallback, so the agent's request fails -> R-009."""


def compress_messages(messages=None, path=None, metadata=None):
    if len(messages) > 2:
        raise ValueError("unexpected shape")
    return messages
