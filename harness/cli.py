"""Command registry for the development harness.

    python -m harness lock fetch|verify    materialize / verify pinned upstream sources
    python -m harness check [--candidate]  contract suite (G1 + replay checks) -> receipt
    python -m harness test                 full pytest suite -> receipt (skips count as not run)
    python -m harness f001                 run every F-001 check into runs/<id>/ and report
    python -m harness report <run-dir>     rebuild the offline report from receipts
    python -m harness status               budgets, unresolved upstream questions
    python -m harness online | package     registered; refuse until their gates exist
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness import ROOT, contracts, evidence, upstream
from harness.budget import load_budget
from harness.evidence import Receipt

MINER = ROOT / "src" / "soma_miner" / "miner.py"
FIXTURE_DIRS = [ROOT / "fixtures" / "synthetic", ROOT / "fixtures" / "captured"]


def fixture_paths() -> list[Path]:
    return sorted(p for d in FIXTURE_DIRS if d.is_dir() for p in d.glob("*.json"))


def cmd_lock(args) -> int:
    if args.action == "fetch":
        print("\n".join(upstream.fetch()))
    problems = upstream.verify()
    print("lock verified" if not problems else "\n".join(problems))
    return 0 if not problems else 1


def run_check(candidate: Path, run_dir: Path | None) -> Receipt:
    started = evidence.now()
    paths = fixture_paths()
    report = contracts.run_suite(candidate, paths)
    receipt = Receipt(
        kind="contracts",
        command=f"python -m harness check --candidate {candidate.relative_to(ROOT)}",
        inputs={str(candidate.relative_to(ROOT)): evidence.digest_path(candidate), "fixtures": evidence.digest_path(ROOT / "fixtures")},
        result=report.to_dict(),
        passed=report.passed,
        reason="all contracts hold" if report.passed else f"{len(report.findings)} contract finding(s)",
        started_at=started,
        finished_at=evidence.now(),
    )
    if run_dir:
        evidence.write_receipt(run_dir, receipt)
    return receipt


def cmd_check(args) -> int:
    receipt = run_check(Path(args.candidate).resolve(), None)
    print(json.dumps(receipt.result, indent=1)[:4000])
    return 0 if receipt.passed else 1


def run_tests(run_dir: Path | None) -> Receipt:
    started = evidence.now()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    summary = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error|errors)", summary)}
    passed = proc.returncode == 0 and counts.get("skipped", 0) == 0
    receipt = Receipt(
        kind="tests",
        command="python -m pytest -q",
        inputs={"harness": evidence.digest_path(ROOT / "harness"), "tests": evidence.digest_path(ROOT / "tests")},
        result={"exit_code": proc.returncode, "summary": summary, "counts": counts, "tail": proc.stdout[-3000:]},
        passed=passed,
        reason=summary if passed else f"exit {proc.returncode}; skipped tests count as not run: {summary}",
        started_at=started,
        finished_at=evidence.now(),
    )
    if run_dir:
        evidence.write_receipt(run_dir, receipt)
    return receipt


def cmd_test(args) -> int:
    receipt = run_tests(None)
    print(receipt.reason)
    return 0 if receipt.passed else 1


def cmd_f001(args) -> int:
    run_id = "f001-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = evidence.RUNS_DIR / run_id
    evidence.write_manifest(run_dir, {
        "experiment_id": run_id,
        "spec": "specs/features/F-001-identity.md",
        "requirements": ["R-001", "R-002", "R-003", "R-004", "R-005", "R-006", "R-007", "R-009", "R-010", "R-011",
                         "R-012", "R-015", "R-016", "R-017", "R-021", "R-022"],
        "candidate": str(MINER.relative_to(ROOT)),
        "kind": "offline",
        "paid_runs": False,
    })
    started = evidence.now()
    problems = upstream.verify()
    evidence.write_receipt(run_dir, Receipt(
        "lock", "python -m harness lock verify", {"specs/upstream.lock.json": upstream.lock_digest()},
        {"problems": problems}, not problems, "pinned sources match" if not problems else "; ".join(problems),
        started, evidence.now()))
    run_check(MINER, run_dir)
    run_tests(run_dir)
    report = build_report(run_dir)
    print(f"{run_dir.relative_to(ROOT)}: {report['outcome']}")
    for item in report["acceptance"]:
        print(f"  [{item['status']}] {item['item']}: {item['evidence']}")
    return 0 if report["outcome"] == "READY_FOR_COMPRESSION" else 1


def build_report(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    receipts = {r["kind"]: r for r in evidence.load_receipts(run_dir)}
    lock = upstream.load_lock()
    captured = [p for p in fixture_paths() if json.loads(p.read_text(encoding="utf-8")).get("provenance", {}).get("kind") == "captured"]

    def status(kind: str) -> str:
        return "PASS" if receipts.get(kind, {}).get("passed") else ("MISSING" if kind not in receipts else "FAIL")

    tests = receipts.get("tests", {}).get("result", {}).get("summary", "not run")
    contract = receipts.get("contracts", {}).get("result", {})
    acceptance = [
        {"item": "1 upstream commits and runtime contract resolved", "status": status("lock"),
         "evidence": f"{len(lock['repos'])} repos pinned; {len(lock['unresolved'])} open questions recorded"},
        {"item": "2 proxy strip/restore copy matches upstream", "status": status("tests"), "evidence": "tests/contracts/test_proxy_view.py"},
        {"item": "3 captured copilot payloads in the stripped view", "status": "PASS" if captured else "BLOCKED",
         "evidence": f"{len(captured)} captured fixtures; blocked by U-001 (needs a paid local copilot run)" if not captured else f"{len(captured)} captured fixtures"},
        {"item": "4 fingerprints, protected checks, mutants rejected", "status": status("tests"), "evidence": "tests/contracts/test_suite.py (16 mutants, 1 positive control)"},
        {"item": "5 scorer, contest and screening parity", "status": status("tests"), "evidence": "tests/scoring/*"},
        {"item": "6 manifest, run status, timeouts, budgets, resume", "status": status("tests"), "evidence": "tests/harness/test_evidence.py; harness/invoke.py"},
        {"item": "7 commands registered", "status": "PASS", "evidence": "python -m harness --help"},
        {"item": "identity candidate passes contracts", "status": status("contracts"),
         "evidence": f"{contract.get('stats', {}).get('calls', 0)} calls, {len(contract.get('findings', []))} findings"},
    ]
    statuses = {a["status"] for a in acceptance}
    outcome = "FAILED" if statuses & {"FAIL", "MISSING"} else ("BLOCKED" if "BLOCKED" in statuses else "READY_FOR_COMPRESSION")
    report = {
        "experiment_id": manifest["experiment_id"],
        "spec": manifest["spec"],
        "outcome": outcome,
        "manifest_digests": manifest["digests"],
        "current_digests": evidence.project_digests(),
        "tests": tests,
        "acceptance": acceptance,
        "unresolved": lock["unresolved"],
        "generated_at": evidence.now(),
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    lines = [f"# {manifest['experiment_id']} — {outcome}", "", f"Spec: `{manifest['spec']}`  ", f"Tests: {tests}", "",
             "| Acceptance item | Status | Evidence |", "|---|---|---|"]
    lines += [f"| {a['item']} | {a['status']} | {a['evidence']} |" for a in acceptance]
    lines += ["", "Open upstream questions:", ""] + [f"- **{u['id']}** {u['question']} (blocks: {u['blocks']})" for u in lock["unresolved"]]
    lines += ["", "Digests at manifest time:", ""] + [f"- `{k}` {v[:16]}" for k, v in manifest["digests"].items()]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def cmd_report(args) -> int:
    report = build_report(Path(args.run_dir).resolve())
    print(report["outcome"])
    return 0


def cmd_status(args) -> int:
    budget = load_budget()
    lock = upstream.load_lock()
    print(f"paid runs allowed: {budget.paid_runs_allowed}" + ("" if budget.paid_runs_allowed else f" (unset: {', '.join(budget.missing_paid_fields())})"))
    print(f"max repair cycles: {budget.max_repair_cycles}; active attempts: {budget.max_active_attempts}")
    print(f"fixtures: {len(fixture_paths())}")
    for item in lock["unresolved"]:
        print(f"{item['id']}: {item['question']}  [blocks: {item['blocks']}]")
    return 0


def cmd_online(args) -> int:
    budget = load_budget()
    if not budget.paid_runs_allowed:
        print("refused: paid runs are disabled until configs/budgets.yaml sets " + ", ".join(budget.missing_paid_fields()))
        return 2
    print("refused: the online evaluation runner is not implemented yet (needs U-001 captured payloads first)")
    return 2


def cmd_package(args) -> int:
    print("refused: packaging is milestone M8; no packaged artifact exists yet")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    lock = sub.add_parser("lock")
    lock.add_argument("action", choices=["fetch", "verify"])
    lock.set_defaults(func=cmd_lock)
    check = sub.add_parser("check")
    check.add_argument("--candidate", default=str(MINER))
    check.set_defaults(func=cmd_check)
    sub.add_parser("test").set_defaults(func=cmd_test)
    sub.add_parser("f001").set_defaults(func=cmd_f001)
    report = sub.add_parser("report")
    report.add_argument("run_dir")
    report.set_defaults(func=cmd_report)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("online").set_defaults(func=cmd_online)
    sub.add_parser("package").set_defaults(func=cmd_package)
    args = parser.parse_args(argv)
    return args.func(args)
