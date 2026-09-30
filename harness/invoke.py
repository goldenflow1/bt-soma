"""Run a candidate miner in an isolated child process with time and memory limits.

A `try/except` inside the miner cannot stop a stuck or malicious process, so
the harness owns the deadline: the child is killed when the overall budget for
its calls is spent, and each call's own duration is checked against the
per-call production timeout.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness import ROOT

CHILD = ROOT / "harness" / "_child.py"
MEMORY_LIMIT_BYTES = 4 * 1024**3
STARTUP_ALLOWANCE_S = 10.0


@dataclass
class CallOutcome:
    ok: bool
    result: Any
    error: str | None
    duration_ms: float
    input_mutated: bool
    stdout: str = ""
    stderr: str = ""


@dataclass
class InvokeResult:
    entry_point: str | None
    load_error: str | None
    timed_out: bool
    returncode: int | None
    outcomes: list[CallOutcome] = field(default_factory=list)
    child_stderr: str = ""

    @property
    def usable(self) -> bool:
        return not self.timed_out and self.load_error is None and self.returncode == 0


def invoke(
    candidate: Path,
    calls: list[dict[str, Any]],
    *,
    entry_point_names: list[str],
    per_call_timeout_s: float,
    hash_seed: str = "0",
) -> InvokeResult:
    """Run `calls` ([{"messages": [...], "path": "/..."}]) sequentially in one child."""
    request = {
        "candidate": str(Path(candidate).resolve()),
        "entry_point_names": entry_point_names,
        "calls": calls,
    }
    budget = STARTUP_ALLOWANCE_S + per_call_timeout_s * max(1, len(calls))
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONHASHSEED": hash_seed, "PYTHONIOENCODING": "utf-8"}
    with tempfile.TemporaryDirectory(prefix="soma-candidate-") as workdir:
        try:
            proc = subprocess.run(
                [sys.executable, str(CHILD)],
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=budget,
                cwd=workdir,
                env=env,
                preexec_fn=_limit_resources,
            )
        except subprocess.TimeoutExpired as exc:
            return InvokeResult(None, None, True, None, [], _tail(exc.stderr))

    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return InvokeResult(None, "child produced no protocol output", False, proc.returncode, [], _tail(proc.stderr))

    outcomes = [CallOutcome(**{k: c.get(k) for k in CallOutcome.__dataclass_fields__}) for c in response["calls"]]
    return InvokeResult(
        response["entry_point"], response["load_error"], False, proc.returncode, outcomes, _tail(proc.stderr)
    )


def _limit_resources() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))


def _tail(text: str | bytes | None, limit: int = 4000) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return text[-limit:]
