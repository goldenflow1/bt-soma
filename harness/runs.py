"""Per-run records and provider-usage normalization (section 26.2).

`resolved=False` is kept separate from infrastructure errors, interruptions and
missing usage. Missing usage never becomes zero cost, and an incomplete run
never becomes a solve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from harness.scoring import Run


class Completion(str, Enum):
    COMPLETED = "completed"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    INTERRUPTED = "interrupted"
    RUNNING = "running"


@dataclass(frozen=True)
class Usage:
    uncached_input: int
    cached_input: int
    output: int
    normalization: str


def normalize_openai_usage(raw: dict[str, Any] | None) -> Usage | None:
    """OpenAI/OpenRouter usage: `prompt_tokens` already includes cached tokens.

    uncached = prompt_tokens - prompt_tokens_details.cached_tokens, so cached
    input is never counted twice. Returns None when required fields are missing.
    """
    if not raw or raw.get("prompt_tokens") is None or raw.get("completion_tokens") is None:
        return None
    prompt = int(raw["prompt_tokens"])
    cached = int(((raw.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    if prompt < 0 or cached < 0 or cached > prompt or int(raw["completion_tokens"]) < 0:
        return None
    return Usage(prompt - cached, cached, int(raw["completion_tokens"]), "openai: uncached = prompt_tokens - cached_tokens")


@dataclass
class RunRecord:
    arm: str  # identity | reference | candidate | champion
    candidate_digest: str
    task_id: str
    group: str | None
    repeat_index: int
    completion: Completion
    resolved: bool | None = None
    usage: Usage | None = None
    raw_usage: list[dict[str, Any]] = field(default_factory=list)
    model_calls: int | None = None
    compressor_latency_ms: float | None = None
    wall_time_s: float | None = None
    spend_usd: float | None = None
    artifacts: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.completion is not Completion.COMPLETED and self.resolved:
            raise ValueError("an incomplete run cannot be recorded as resolved")

    @property
    def usage_missing(self) -> bool:
        return self.completion is Completion.COMPLETED and self.usage is None

    def scoring_run(self) -> Run | None:
        """The run as the scorer sees it, or None when it must not be scored yet."""
        if self.completion is not Completion.COMPLETED:
            return None
        if self.usage is None:
            return Run(self.resolved, None, None, None)
        return Run(self.resolved, self.usage.uncached_input, self.usage.cached_input, self.usage.output)
