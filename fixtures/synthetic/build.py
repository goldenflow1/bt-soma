"""Generate the synthetic contract fixtures in this directory.

These are hand-built OpenAI chat-completions trajectories shaped like the copilot
backend's requests. They are labeled `synthetic`: they exercise contract edge cases but
are no substitute for captured payloads (F-001 acceptance item 3).

Run: .venv/bin/python fixtures/synthetic/build.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVENANCE = {
    "kind": "synthetic",
    "generator": "fixtures/synthetic/build.py",
    "note": "Hand-built; OpenAI chat-completions as the copilot backend sends through the SOMA proxy (path /chat/completions). Tool names are illustrative, not Copilot CLI's.",
}
SYSTEM = (
    "You are a coding agent working in a repository checkout. Use the provided tools to inspect "
    "files, run commands and edit code. Make the failing tests pass without breaking others."
)
TOOLS = [
    {"type": "function", "function": {"name": "exec", "description": "Run a shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read", "description": "Read a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "edit", "description": "Replace text in a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "oldText": {"type": "string"}, "newText": {"type": "string"}}, "required": ["path", "oldText", "newText"]}}},
]


def call(call_id: str, name: str, **arguments) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def assistant(*tool_calls: dict, content: str = "") -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = list(tool_calls)
    return message


def tool(call_id: str, content) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def payload(messages: list[dict]) -> dict:
    return {"model": "deepseek/deepseek-v4-pro", "messages": messages, "tools": TOOLS, "stream": False}


def grep_output() -> str:
    lines = [
        f"django/db/models/query.py:{700 + i * 7}:        # bulk_create helper step {i}" for i in range(12)
    ]
    lines += [f"django/db/models/sql/compiler.py:{1600 + i}:    def bulk_create_{i}(self):" for i in range(6)]
    lines += [f"tests/bulk_create/tests.py:{40 + i * 9}:    def test_bulk_create_case_{i}(self):" for i in range(20)]
    lines += [f".venv/lib/python3.12/site-packages/pkg/mod_{i}.py:{i}:bulk_create = None" for i in range(10)]
    return "\n".join(lines)


def source_view(start: int, count: int) -> str:
    body = []
    for n in range(start, start + count):
        if n == start + 10:
            text = "    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False):"
        elif n == start + 11:
            text = '        """Insert each of the instances into the database."""'
        elif n == start + 30:
            text = "        fields = [f for f in opts.concrete_fields if not f.generated]"
        else:
            text = f"        step_{n} = self._prepare(objs, {n % 7})"
        body.append(f"{n:>6}\t{text}")
    return "\n".join(body)


def pytest_failure() -> str:
    progress = "\n".join("tests/bulk_create/tests.py " + "." * 60 + f" [{p:>3}%]" for p in range(5, 100, 5))
    return "\n".join([
        "============================= test session starts ==============================",
        "platform linux -- Python 3.12.3, pytest-8.3.3, pluggy-1.5.0",
        "rootdir: /testbed",
        "collected 129 items",
        "",
        progress,
        "",
        "=================================== FAILURES ===================================",
        "__________________________ test_generated_field ________________________________",
        "",
        "    def test_generated_field(self):",
        "        objs = GeneratedModel.objects.bulk_create([GeneratedModel(a=1)])",
        ">       assert objs[0].a_plus_one == 2",
        "E       AssertionError: assert None == 2",
        "E        +  where None = <GeneratedModel: GeneratedModel object (1)>.a_plus_one",
        "",
        "tests/bulk_create/tests.py:812: AssertionError",
        "=========================== short test summary info ============================",
        "FAILED tests/bulk_create/tests.py::test_generated_field - AssertionError: assert None == 2",
        "======================== 1 failed, 128 passed in 14.20s ========================",
    ])


def pip_log() -> str:
    lines = [f"Collecting package-{i}==1.{i}.0" for i in range(15)]
    lines += [f"  Downloading package_{i}-1.{i}.0-py3-none-any.whl ({i * 13 + 20} kB)" for i in range(15)]
    lines += ["Installing collected packages: " + ", ".join(f"package-{i}" for i in range(15))]
    lines += ["Successfully installed " + " ".join(f"package-{i}-1.{i}.0" for i in range(15))]
    return "\n".join(lines)


def bugfix() -> dict:
    task = (
        "QuerySet.bulk_create() does not populate GeneratedField values on returned objects.\n"
        "Reproduce with tests/bulk_create/tests.py::test_generated_field and fix it."
    )
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task},
        assistant(call("call_1", "exec", command='grep -rn "bulk_create" django/db/models/ tests/bulk_create/ .venv/lib')),
        tool("call_1", grep_output()),
        assistant(call("call_2", "read", path="django/db/models/query.py", offset=700, limit=80)),
        tool("call_2", source_view(700, 80)),
        assistant(call("call_3", "exec", command="python -m pytest tests/bulk_create/tests.py -q")),
        tool("call_3", pytest_failure()),
        assistant(call("call_4", "edit", path="django/db/models/query.py",
                       oldText="fields = [f for f in opts.concrete_fields if not f.generated]",
                       newText="fields = [f for f in opts.concrete_fields if not f.generated]\n        returning = opts.db_returning_fields")),
        tool("call_4", "Successfully replaced text in django/db/models/query.py."),
        {"role": "user", "content": "Continue with the task."},
        assistant(call("call_5", "exec", command="python -m pytest tests/bulk_create/tests.py::test_generated_field -q")),
        tool("call_5", "1 passed in 0.41s"),
        assistant(content="The fix makes bulk_create() read back generated fields; the failing test now passes."),
    ]
    return {
        "id": "syn-chat-bugfix",
        "path": "/chat/completions",
        "provenance": PROVENANCE,
        "payload": payload(messages),
        "evidence": [
            {"tool_call_id": "call_2", "must_contain": ["def bulk_create(self, objs", "   730\t"]},
            {"tool_call_id": "call_3", "must_contain": [
                "FAILED tests/bulk_create/tests.py::test_generated_field",
                "E       AssertionError: assert None == 2",
                "tests/bulk_create/tests.py:812: AssertionError",
                "1 failed, 128 passed",
            ]},
        ],
    }


def parallel_multipart() -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "The CLI crashes when --config points to a directory. Fix it."},
        assistant(
            call("call_a", "read", path="cli/config.py"),
            call("call_b", "exec", command="python -m cli --config /tmp"),
            content="I'll look at the loader and reproduce the crash.",
        ),
        tool("call_a", [{"type": "text", "text": "   1\timport os\n   2\t\n   3\tdef load(path):\n   4\t    with open(path) as fh:\n   5\t        return fh.read()"}]),
        tool("call_b", [
            {"type": "text", "text": 'Traceback (most recent call last):\n  File "cli/config.py", line 4, in load\nIsADirectoryError: [Errno 21] Is a directory: \'/tmp\''},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        ]),
        assistant(content="load() must reject directories before opening them."),
    ]
    return {
        "id": "syn-chat-parallel-multipart",
        "path": "/chat/completions",
        "provenance": PROVENANCE,
        "payload": payload(messages),
        "evidence": [{"tool_call_id": "call_b", "must_contain": ["IsADirectoryError", 'File "cli/config.py", line 4']}],
    }


def repeated_reads() -> dict:
    view = source_view(1, 40)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Install the dev requirements and make utils.slugify handle unicode."},
        assistant(call("call_1", "exec", command="pip install -r requirements-dev.txt")),
        tool("call_1", pip_log()),
        assistant(call("call_2", "read", path="utils/text.py")),
        tool("call_2", view),
        assistant(call("call_3", "read", path="utils/text.py")),
        tool("call_3", view),
        assistant(call("call_4", "read", path="utils/text.py")),
        tool("call_4", view),
        assistant(content="The file is unchanged between reads; the bug is in the normalization step."),
    ]
    return {
        "id": "syn-chat-repeated-reads",
        "path": "/chat/completions",
        "provenance": PROVENANCE,
        "payload": payload(messages),
        "evidence": [{"tool_call_id": "call_1", "must_contain": ["Successfully installed"]}],
    }


def minimal() -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Print the Python version used by the repository."},
        assistant(call("call_1", "exec", command="python --version")),
        tool("call_1", "Python 3.12.3"),
        assistant(content="The repository uses Python 3.12.3."),
    ]
    return {
        "id": "syn-chat-minimal",
        "path": "/chat/completions",
        "provenance": PROVENANCE,
        "payload": payload(messages),
        "evidence": [],
    }


def main() -> None:
    for fixture in (bugfix(), parallel_multipart(), repeated_reads(), minimal()):
        target = HERE / f"{fixture['id']}.json"
        target.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", target.relative_to(HERE.parent.parent))


if __name__ == "__main__":
    main()
