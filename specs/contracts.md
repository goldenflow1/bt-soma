# Runtime and message contracts

Pinned facts live in `specs/upstream.lock.json`; this file explains how the
harness uses them. Upstream: SOMA@e83a8df, SOMA-benchmark@204ff7f.

## Call path
Copilot CLI 1.0.82 → `http://proxy:8080/chat/completions` → proxy strips
protected prompts → compression service `/transform` → `compress_messages(messages,
path="/chat/completions", metadata={"path": ...})` → result written back →
proxy restores protected prompts → OpenRouter.

OpenClaw's LLM traffic goes through a plain nginx passthrough and never reaches
`compress_messages` (lock `runtime.agents.openclaw`).

## What the miner sees
- No `system`/`developer` messages, no top-level `system`, no first user message.
- Later user messages (for example loop-detection notices) are visible and protected.
- `metadata` holds only `path`.
- A JSON body without `messages` arrives as `[]`.

## Editable locations
Only the text of OpenAI chat-completions `role: "tool"` messages: string content,
or the `text` of `type: "text"` parts. Everything else, including image parts,
`tool_call_id`, assistant `tool_calls` and their `arguments`, must come back
byte-identical. New shapes become editable only through a spec with captured
fixtures.

## Inserted text
Only the markers in lock `allowed_insertions.markers`, each on its own line, with
`X`/`N`/`M` as integers. All other output lines must be an in-order subsequence
of the original lines. Loop-reason strings are not allowed inside tool text.

## Result
Return a list of the same length and order. Every message keeps its role, ids,
keys and content form (string vs parts).

## How each requirement is checked
| Requirement | Check (harness/contracts.py) |
|---|---|
| R-001 | entry point is `compress_messages`; result is a list |
| R-002 | child process compares the input to a deep copy after the call |
| R-003 | messages equal after masking editable text |
| R-004 | ordered fingerprints (role, ids, names, tool calls, content form, keys) equal |
| R-006 | outputs equal across hash seeds, and warm replay equals a cold process |
| R-007 | when input only grows, earlier outputs stay an exact prefix |
| R-009 | no call raises |
| R-010 | forwarded payload, serialized as the proxy does, never grows |
| R-011 | fixture `evidence` strings survive in the final payload |
| R-012 | inserted-text rule above |
| R-017 | each call within the 30 s limit; the child is killed if the budget is spent |
| R-021 | fixtures validated; every call uses the proxy's stripped view |
