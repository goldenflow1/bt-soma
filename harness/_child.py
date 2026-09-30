"""Child process that loads a candidate miner and runs a sequence of calls.

Mirrors the compression service: the module is loaded once from a file path,
the entry point is the first callable among the upstream candidate names, and
arguments are passed by signature. Calls run sequentially in one process, so
module-level state persists across calls as it does within a production run.

Protocol: one JSON object on stdin, one JSON object on stdout. The candidate's
own stdout/stderr are captured per call and never mix with the protocol.
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import inspect
import io
import json
import sys
import time
import traceback


def _load(candidate_path: str, names: list[str]):
    spec = importlib.util.spec_from_file_location("soma_compressor_miner", candidate_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {candidate_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def _call(fn, messages, path):
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        parameters = {}
    kwargs = {}
    if "messages" in parameters:
        kwargs["messages"] = messages
    if "path" in parameters:
        kwargs["path"] = path
    if "metadata" in parameters:
        kwargs["metadata"] = {"path": path}
    return fn(**kwargs) if kwargs else fn(messages)


def main() -> None:
    request = json.loads(sys.stdin.read())
    real_stdout = sys.stdout
    response: dict = {"load_error": None, "entry_point": None, "calls": []}

    capture_out, capture_err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(capture_out), contextlib.redirect_stderr(capture_err):
            fn = _load(request["candidate"], request["entry_point_names"])
    except Exception:  # noqa: BLE001 - reported to the harness, not swallowed
        response["load_error"] = traceback.format_exc()
        fn = None
    if fn is None and response["load_error"] is None:
        response["load_error"] = "no entry point found"
    response["entry_point"] = getattr(fn, "__name__", None)

    if fn is not None:
        for call in request["calls"]:
            messages = call["messages"]
            snapshot = copy.deepcopy(messages)
            out, err = io.StringIO(), io.StringIO()
            started = time.perf_counter()
            outcome: dict = {"ok": True, "error": None, "result": None}
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    result = _call(fn, messages, call["path"])
                json.dumps(result, ensure_ascii=False)  # production serializes the payload
                outcome["result"] = result
            except Exception:  # noqa: BLE001
                outcome["ok"] = False
                outcome["error"] = traceback.format_exc()
            outcome["duration_ms"] = (time.perf_counter() - started) * 1000.0
            outcome["input_mutated"] = messages != snapshot
            outcome["stdout"] = out.getvalue()[-4000:]
            outcome["stderr"] = err.getvalue()[-4000:]
            response["calls"].append(outcome)

    real_stdout.write(json.dumps(response, ensure_ascii=False))
    real_stdout.flush()


if __name__ == "__main__":
    main()
