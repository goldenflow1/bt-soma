"""Evidence: content digests, immutable manifests, check receipts and attempt state.

A candidate is identified by the digest of its source tree, never by a mutable
filename. Receipts are written by the harness, never by the agent, and a
receipt cannot be recorded for an input that does not exist.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness import ROOT

RUNS_DIR = ROOT / "runs"

STATES = ("READY", "IMPLEMENTING", "CHECKING", "REPAIRING", "EVALUATING", "PROMOTED", "REJECTED", "INCONCLUSIVE", "BLOCKED")
TRANSITIONS = {
    "READY": {"IMPLEMENTING", "BLOCKED"},
    "IMPLEMENTING": {"CHECKING", "BLOCKED"},
    "CHECKING": {"REPAIRING", "EVALUATING", "REJECTED", "BLOCKED", "PROMOTED"},
    "REPAIRING": {"CHECKING", "REJECTED", "BLOCKED"},
    "EVALUATING": {"PROMOTED", "REJECTED", "INCONCLUSIVE", "BLOCKED"},
    "BLOCKED": {"READY"},
    "PROMOTED": set(),
    "REJECTED": set(),
    "INCONCLUSIVE": set(),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_path(path: Path) -> str:
    """Digest of a file, or of a directory tree (sorted relative paths + file digests)."""
    path = Path(path)
    if path.is_file():
        return sha256_bytes(path.read_bytes())
    if not path.is_dir():
        raise FileNotFoundError(path)
    h = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(str(file.relative_to(path)).encode())
        h.update(b"\0")
        h.update(sha256_bytes(file.read_bytes()).encode())
        h.update(b"\n")
    return h.hexdigest()


def project_digests() -> dict[str, str]:
    """Digests that identify what a result was produced from."""
    return {
        "candidate_src": digest_path(ROOT / "src"),
        "harness": digest_path(ROOT / "harness"),
        "specs": digest_path(ROOT / "specs"),
        "upstream_lock": digest_path(ROOT / "specs" / "upstream.lock.json"),
        "acceptance": digest_path(ROOT / "specs" / "acceptance.yaml"),
        "fixtures": digest_path(ROOT / "fixtures"),
        "configs": digest_path(ROOT / "configs"),
    }


@dataclass
class Receipt:
    kind: str
    command: str
    inputs: dict[str, str]
    result: dict[str, Any]
    passed: bool
    reason: str
    started_at: str
    finished_at: str
    digests: dict[str, str] = field(default_factory=project_digests)


def write_receipt(experiment_dir: Path, receipt: Receipt) -> Path:
    """Persist a receipt. Inputs must exist and match the digests given."""
    for name, digest in receipt.inputs.items():
        target = ROOT / name
        if not target.exists():
            raise FileNotFoundError(f"receipt input {name} does not exist")
        if digest_path(target) != digest:
            raise ValueError(f"receipt input {name} changed during the check")
    receipts = experiment_dir / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    index = len(list(receipts.glob("*.json"))) + 1
    path = receipts / f"{index:03d}-{receipt.kind}.json"
    path.write_text(json.dumps(asdict(receipt), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_receipts(experiment_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((experiment_dir / "receipts").glob("*.json"))]


def write_manifest(experiment_dir: Path, manifest: dict[str, Any]) -> Path:
    """Write an experiment manifest once; an existing manifest is never overwritten."""
    path = experiment_dir / "manifest.json"
    if path.exists():
        raise FileExistsError(f"{path} is immutable")
    experiment_dir.mkdir(parents=True, exist_ok=True)
    body = dict(manifest)
    body.setdefault("created_at", now())
    body["digests"] = project_digests()
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def resume_check(experiment_dir: Path) -> list[str]:
    """Reasons an experiment cannot be resumed as-is; empty means digests still match."""
    manifest = json.loads((experiment_dir / "manifest.json").read_text(encoding="utf-8"))
    current = project_digests()
    return [
        f"{name} changed since the manifest was written"
        for name in ("candidate_src", "harness", "upstream_lock", "acceptance", "fixtures")
        if manifest["digests"].get(name) != current.get(name)
    ]


class AttemptState:
    """Persistent state of one feature attempt with a bounded repair budget."""

    def __init__(self, path: Path, *, max_repairs: int):
        self.path = path
        self.max_repairs = max_repairs
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"state": "READY", "repairs": 0, "history": []}

    @property
    def state(self) -> str:
        return self.data["state"]

    def transition(self, new_state: str, reason: str) -> None:
        if new_state not in TRANSITIONS[self.state]:
            raise ValueError(f"illegal transition {self.state} -> {new_state}")
        if new_state == "REPAIRING":
            if self.data["repairs"] >= self.max_repairs:
                raise RuntimeError("repair budget exhausted; the attempt must end")
            self.data["repairs"] += 1
        self.data["history"].append({"from": self.state, "to": new_state, "reason": reason, "at": now()})
        self.data["state"] = new_state
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1) + "\n", encoding="utf-8")
