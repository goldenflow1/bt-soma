"""Exceeds the per-call deadline -> R-017."""
import time


def compress_messages(messages=None, path=None, metadata=None):
    time.sleep(3)
    return messages
