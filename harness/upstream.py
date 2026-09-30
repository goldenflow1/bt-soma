"""Pinned upstream sources: fetch, digest verification and symbol extraction.

`specs/upstream.lock.json` pins each upstream repository to a commit and lists
the files this project depends on with their SHA-256 digests. Checkouts live in
`.upstream/<key>/` and are never edited.

`load_symbols` extracts named top-level functions, classes and constants from an
upstream file without importing the file itself, so parity tests can call the
official pure functions without the platform's database and settings stack.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

from harness import ROOT

LOCK_PATH = ROOT / "specs" / "upstream.lock.json"
UPSTREAM_DIR = ROOT / ".upstream"


def load_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def lock_digest() -> str:
    return sha256_file(LOCK_PATH)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkout_dir(repo_key: str) -> Path:
    return UPSTREAM_DIR / repo_key


def fetch(lock: dict[str, Any] | None = None) -> list[str]:
    """Materialize every pinned repository at its locked commit. Returns log lines."""
    lock = lock or load_lock()
    log: list[str] = []
    for key, repo in lock["repos"].items():
        if not repo.get("sha"):
            log.append(f"{key}: no pinned sha, skipped")
            continue
        target = checkout_dir(key)
        head = _git_head(target)
        if head == repo["sha"]:
            log.append(f"{key}: already at {repo['sha'][:12]}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        _git(target, "init", "-q")
        _git(target, "fetch", "-q", "--depth", "1", repo["url"], repo["sha"])
        _git(target, "checkout", "-q", "--detach", "FETCH_HEAD")
        log.append(f"{key}: fetched {repo['sha'][:12]}")
    return log


def verify(lock: dict[str, Any] | None = None) -> list[str]:
    """Return a list of problems; empty means every pinned file matches its digest."""
    lock = lock or load_lock()
    problems: list[str] = []
    for key, repo in lock["repos"].items():
        if not repo.get("sha"):
            continue
        target = checkout_dir(key)
        head = _git_head(target)
        if head != repo["sha"]:
            problems.append(f"{key}: checkout at {head or 'missing'}, lock pins {repo['sha']}")
            continue
        for rel, expected in repo.get("files", {}).items():
            path = target / rel
            if not path.is_file():
                problems.append(f"{key}: missing {rel}")
            elif sha256_file(path) != expected:
                problems.append(f"{key}: digest mismatch for {rel}")
    return problems


def is_available(repo_key: str) -> bool:
    repo = load_lock()["repos"][repo_key]
    return _git_head(checkout_dir(repo_key)) == repo["sha"]


def load_symbols(
    repo_key: str,
    relpath: str,
    names: list[str],
    namespace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute only the named top-level definitions of an upstream file.

    `namespace` supplies whatever the definitions reference (stdlib imports,
    stand-ins for settings). The file's digest is checked against the lock first.
    """
    lock = load_lock()
    expected = lock["repos"][repo_key]["files"].get(relpath)
    path = checkout_dir(repo_key) / relpath
    if expected is None:
        raise KeyError(f"{repo_key}:{relpath} is not pinned in the lock")
    if sha256_file(path) != expected:
        raise RuntimeError(f"{repo_key}:{relpath} does not match its pinned digest")

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = set(names)
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            body.append(node)
        elif _defined_name(node) in wanted:
            body.append(node)
            wanted.discard(_defined_name(node))
    if wanted:
        raise KeyError(f"{repo_key}:{relpath} does not define {sorted(wanted)}")

    # A registered module object, because dataclasses resolve their module by name.
    module_name = "_upstream." + repo_key + "." + relpath.replace("/", ".").removesuffix(".py")
    module = types.ModuleType(module_name)
    module.__dict__.update(namespace or {})
    sys.modules[module_name] = module
    code = compile(ast.Module(body=body, type_ignores=[]), str(path), "exec")
    exec(code, module.__dict__)  # noqa: S102 - pinned, digest-checked source
    return module.__dict__


def _defined_name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_head(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        return _git(path, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        return None
