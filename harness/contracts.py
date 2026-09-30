"""Contract suite (gate G1) for a candidate miner.

Each fixture is a full agent trajectory. The suite derives the successive LLM
requests, converts each into the compressor-visible view (R-021), runs them
through the candidate in an isolated child process, and checks every result.

Editable locations are declared in EDITABLE: only text inside OpenAI
chat-completions `role: "tool"` messages. Every other byte of every message
must come back unchanged (R-003, R-004, R-005).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from harness import proxy_view
from harness.invoke import InvokeResult, invoke
from harness.upstream import load_lock

EDITABLE = "OpenAI chat-completions: text of role=tool messages (string content or type=text parts)"
_MASK = "\x00EDITABLE\x00"
_SECRET_PATTERNS = re.compile(r"sk-or-[A-Za-z0-9-]{8,}|sk-[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,}")


@dataclass
class Finding:
    requirement: str
    fixture: str
    request: int | None
    detail: str


@dataclass
class Fixture:
    id: str
    path: str
    provenance: dict[str, Any]
    requests: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    source: str


@dataclass
class SuiteReport:
    candidate: str
    fixtures: list[str]
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "fixtures": self.fixtures,
            "passed": self.passed,
            "findings": [asdict(f) for f in self.findings],
            "stats": self.stats,
        }


# ── Fixtures ─────────────────────────────────────────────────────────────────


def load_fixture(path: Path) -> Fixture:
    data = json.loads(path.read_text(encoding="utf-8"))
    requests = data["requests"] if "requests" in data else derive_requests(data["payload"])
    return Fixture(
        id=data["id"],
        path=data.get("path", "/chat/completions"),
        provenance=data.get("provenance", {}),
        requests=requests,
        evidence=data.get("evidence", []),
        source=str(path),
    )


def derive_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Successive requests of an append-only chat: one per user/tool turn the model answered.

    The model is called when the history ends in a user or tool message and the
    next message is the assistant's reply (or the history ends).
    """
    messages = payload["messages"]
    requests = []
    for i, message in enumerate(messages):
        role = message.get("role")
        next_role = messages[i + 1].get("role") if i + 1 < len(messages) else None
        if role in ("user", "tool") and next_role in ("assistant", None):
            request = copy.deepcopy(payload)
            request["messages"] = copy.deepcopy(messages[: i + 1])
            requests.append(request)
    return requests


def validate_fixture(fixture: Fixture) -> list[Finding]:
    """R-021 and hygiene: provenance, shape, stripped view exercised, no credentials."""
    problems = []

    def bad(detail: str) -> None:
        problems.append(Finding("R-021", fixture.id, None, detail))

    if fixture.provenance.get("kind") not in ("synthetic", "captured"):
        bad("provenance.kind must be 'synthetic' or 'captured'")
    if not fixture.requests:
        bad("fixture yields no requests")
    for i, request in enumerate(fixture.requests):
        messages = request.get("messages")
        if not isinstance(messages, list):
            bad(f"request {i} has no messages list")
            continue
        view = proxy_view.compressor_view(request)
        if any(isinstance(m, dict) and m.get("role") in proxy_view.PROTECTED_ROLES for m in view):
            bad(f"request {i}: compressor view still contains system/developer messages")
    if fixture.requests and not any(m.get("role") == "user" for m in fixture.requests[0]["messages"]):
        bad("first request has no user task, so the stripped view is not exercised")
    if _SECRET_PATTERNS.search(json.dumps([r for r in fixture.requests], ensure_ascii=False)):
        bad("fixture appears to contain a credential")
    return problems


# ── Message structure ────────────────────────────────────────────────────────


def fingerprint(message: Any) -> tuple:
    """Ordered structural identity of a message (R-004)."""
    if not isinstance(message, dict):
        return ("non-dict", type(message).__name__)
    content = message.get("content")
    if isinstance(content, str):
        kind: Any = "str"
    elif isinstance(content, list):
        kind = tuple(part.get("type") if isinstance(part, dict) else type(part).__name__ for part in content)
    else:
        kind = type(content).__name__
    tool_calls = tuple(
        (tc.get("id"), (tc.get("function") or {}).get("name")) if isinstance(tc, dict) else ("?", "?")
        for tc in (message.get("tool_calls") or [])
    )
    return (message.get("role"), message.get("tool_call_id"), message.get("name"), tool_calls, kind, tuple(sorted(message)))


def editable_texts(message: Any) -> list[str]:
    if not isinstance(message, dict) or message.get("role") != "tool":
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [p["text"] for p in content if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)]
    return []


def mask_editable(message: Any) -> Any:
    masked = copy.deepcopy(message)
    if not isinstance(masked, dict) or masked.get("role") != "tool":
        return masked
    content = masked.get("content")
    if isinstance(content, str):
        masked["content"] = _MASK
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                part["text"] = _MASK
    return masked


# ── Inserted text (R-012) ────────────────────────────────────────────────────


def marker_patterns(markers: list[str]) -> list[re.Pattern]:
    patterns = []
    for marker in markers:
        pieces = re.split(r"\b([XNM])\b", marker)
        regex = "".join(r"\d+" if i % 2 else re.escape(piece) for i, piece in enumerate(pieces))
        patterns.append(re.compile(regex))
    return patterns


def check_inserted_text(original: str, compressed: str, patterns: list[re.Pattern]) -> str | None:
    """Non-marker lines must be an in-order subsequence of the original lines."""
    if compressed == original:
        return None
    source = original.split("\n")
    cursor = 0
    for line in compressed.split("\n"):
        if any(p.fullmatch(line.strip()) for p in patterns) and line.strip():
            continue
        while cursor < len(source) and source[cursor] != line:
            cursor += 1
        if cursor == len(source):
            return f"line not in original order or not allowlisted: {line[:120]!r}"
        cursor += 1
    return None


# ── Suite ────────────────────────────────────────────────────────────────────


def payload_bytes(payload: dict[str, Any]) -> int:
    """Size as the proxy serializes the forwarded body."""
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def run_suite(candidate: Path, fixture_paths: list[Path], *, per_call_timeout_s: float | None = None) -> SuiteReport:
    lock = load_lock()
    runtime = lock["runtime"]
    timeout = per_call_timeout_s if per_call_timeout_s is not None else runtime["compression_timeout_seconds"]
    names = runtime["entry_point_names"]
    patterns = marker_patterns(lock["allowed_insertions"]["markers"])

    fixtures = [load_fixture(p) for p in fixture_paths]
    report = SuiteReport(str(candidate), [f.id for f in fixtures])
    latencies: list[float] = []
    bytes_in = bytes_out = 0

    for fx in fixtures:
        problems = validate_fixture(fx)
        report.findings.extend(problems)
        if problems:
            continue

        views = [proxy_view.compressor_view(req) for req in fx.requests]
        calls = [{"messages": v, "path": fx.path} for v in views]
        warm = invoke(candidate, calls, entry_point_names=names, per_call_timeout_s=timeout, hash_seed="0")
        if not _usable(warm, fx, report, timeout):
            continue

        results: list[Any] = []
        for k, (request, view, outcome) in enumerate(zip(fx.requests, views, warm.outcomes)):
            latencies.append(outcome.duration_ms)
            results.append(outcome.result)
            add = lambda req, detail, k=k: report.findings.append(Finding(req, fx.id, k, detail))  # noqa: E731

            if outcome.duration_ms > timeout * 1000.0:
                add("R-017", f"call took {outcome.duration_ms:.0f} ms, limit {timeout * 1000:.0f} ms")
            if not outcome.ok:
                add("R-009", "exception reaches the agent as HTTP 500: " + (outcome.error or "").strip().splitlines()[-1][:200])
                continue
            if outcome.input_mutated:
                add("R-002", "candidate mutated its input messages")
            if not isinstance(outcome.result, list):
                add("R-001", f"returned {type(outcome.result).__name__}, expected list")
                continue
            _check_structure(view, outcome.result, add, patterns)

            final = proxy_view.round_trip(request, outcome.result)
            size_in, size_out = payload_bytes(request), payload_bytes(final)
            bytes_in += size_in
            bytes_out += size_out
            if size_out > size_in:
                add("R-010", f"forwarded payload grew from {size_in} to {size_out} bytes")
            for miss in _missing_evidence(fx, final):
                add("R-011", miss)

        _check_prefix_stability(fx, views, results, report)
        _check_determinism(candidate, fx, calls, results, names, timeout, report)

    report.stats = {
        "calls": len(latencies),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p99": _percentile(latencies, 99),
        "bytes_in": bytes_in,
        "bytes_out": bytes_out,
        "byte_reduction": (1 - bytes_out / bytes_in) if bytes_in else None,
        "editable_locations": EDITABLE,
        "per_call_timeout_s": timeout,
    }
    return report


def _usable(result: InvokeResult, fx: Fixture, report: SuiteReport, timeout: float) -> bool:
    if result.timed_out:
        report.findings.append(Finding("R-017", fx.id, None, f"candidate exceeded {timeout} s per call and was killed"))
        return False
    if result.load_error:
        report.findings.append(Finding("R-001", fx.id, None, "load failed: " + result.load_error.strip().splitlines()[-1][:200]))
        return False
    if result.entry_point != "compress_messages":
        report.findings.append(Finding("R-001", fx.id, None, f"entry point is {result.entry_point!r}, expected compress_messages"))
    if len(result.outcomes) != len(fx.requests):
        report.findings.append(Finding("R-009", fx.id, None, "child exited before completing all calls"))
        return False
    return True


def _check_structure(view: list[Any], result: list[Any], add, patterns: list[re.Pattern]) -> None:
    if [fingerprint(m) for m in view] != [fingerprint(m) for m in result]:
        index = next(
            (i for i, (a, b) in enumerate(zip(view, result)) if fingerprint(a) != fingerprint(b)),
            min(len(view), len(result)),
        )
        add("R-004", f"message structure differs at index {index} ({len(view)} in, {len(result)} out)")
        return
    for i, (before, after) in enumerate(zip(view, result)):
        if mask_editable(before) != mask_editable(after):
            add("R-003", f"protected content changed in message {i} (role={before.get('role')})")
            continue
        for original, compressed in zip(editable_texts(before), editable_texts(after)):
            problem = check_inserted_text(original, compressed, patterns)
            if problem:
                add("R-012", f"message {i}: {problem}")


def _missing_evidence(fx: Fixture, final: dict[str, Any]) -> list[str]:
    missing = []
    by_id = {m.get("tool_call_id"): m for m in final.get("messages", []) if isinstance(m, dict) and m.get("role") == "tool"}
    for item in fx.evidence:
        message = by_id.get(item["tool_call_id"])
        if message is None:
            continue
        text = "\n".join(editable_texts(message))
        missing += [f"{item['tool_call_id']}: lost {needle!r}" for needle in item["must_contain"] if needle not in text]
    return missing


def _check_prefix_stability(fx: Fixture, views: list[list[Any]], results: list[Any], report: SuiteReport) -> None:
    """R-007: when the input only grows, earlier outputs must remain an exact prefix."""
    for k in range(len(views) - 1):
        before, after = results[k], results[k + 1]
        if not isinstance(before, list) or not isinstance(after, list):
            continue
        if views[k + 1][: len(views[k])] != views[k]:
            continue  # input itself was not append-only; nothing to assert
        if after[: len(before)] != before:
            index = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b), len(before))
            report.findings.append(
                Finding("R-007", fx.id, k + 1, f"earlier output message {index} changed when the history grew")
            )


def _check_determinism(candidate, fx, calls, warm_results, names, timeout, report) -> None:
    """R-006: same outputs under another hash seed, and for a cold process on the last request."""
    other = invoke(candidate, calls, entry_point_names=names, per_call_timeout_s=timeout, hash_seed="1")
    if other.usable and [o.result for o in other.outcomes] != warm_results:
        report.findings.append(Finding("R-006", fx.id, None, "outputs differ between hash seeds"))
    cold = invoke(candidate, calls[-1:], entry_point_names=names, per_call_timeout_s=timeout, hash_seed="2")
    if cold.usable and cold.outcomes and cold.outcomes[0].result != warm_results[-1]:
        report.findings.append(Finding("R-006", fx.id, len(calls) - 1, "cold-process output differs from warm replay"))


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 3)
