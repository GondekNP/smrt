#!/usr/bin/env python3
"""Did the injected MCP server actually start? Answered without a model call.

An MCP server is spawned by the agent during `session/new`, which happens
before any prompt — so the whole question "does `--mcp NAME=CMD` produce a
working server" is answerable for free. Only whether the *model* then uses the
tools needs a paid session, which is what `live_session.py` is for.

    smrt -- python3 /workspace/proxy/tests/spawn_session.py vault-tools=vault-tools

Worth having because the symptom of a failure here is uninformative: the model
reports "the server failed to connect (connection closed)" and the reason lives
in the agent's stderr, which the client never shows. The proxy drains that
stderr into its trace, so this prints it.

Exits non-zero if the handshake or `session/new` fails, but a server that
failed to start is NOT an error here — the agent proceeds without it, exactly
as in a real session. Read the output.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_session import Client  # noqa: E402


def main() -> int:
    spec = sys.argv[1] if len(sys.argv) > 1 else "vault-tools=vault-tools"
    trace_path = Path(tempfile.gettempdir()) / "spawn-session-trace.jsonl"

    command = [
        "smrt-acp-proxy", "--backend", "claude",
        "--mcp", spec, "--trace", str(trace_path),
    ]
    print(f"$ {' '.join(command)}\n")

    client = Client(command)
    client.call("initialize", {
        "protocolVersion": 1,
        "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": False}},
        "clientInfo": {"name": "spawn-session", "version": "0"},
    })
    result = client.call("session/new", {"cwd": "/vault", "mcpServers": []})
    print(f"session/new ok: sessionId={result.get('sessionId')}\n")

    # Wait WITHOUT closing stdin. The agent may spawn MCP servers lazily, and
    # closing stdin shuts the whole thing down before it gets there -- which
    # made the first version of this script report "never started" for a server
    # that had simply not been reached yet.
    delay = float(os.environ.get("SPAWN_WAIT", "20"))
    print(f"waiting {delay:.0f}s for MCP servers to be spawned...\n")
    deadline = time.monotonic() + delay
    while time.monotonic() < deadline:
        try:
            message = client.inbox.get(timeout=max(0.1, deadline - time.monotonic()))
        except Exception:
            continue
        if message is None:
            break

    print("--- Claude Code's own MCP logs (the authoritative reason) ---")
    cache = Path(os.path.expanduser("~/.cache/claude-cli-nodejs"))
    found = sorted(cache.glob("**/mcp-logs-*/*"))
    if not found:
        print(f"  none under {cache}")
    for log in found[-4:]:
        print(f"  == {log}")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]:
            print(f"     {line[:300]}")
    print()

    client.proc.stdin.close()
    try:
        client.proc.wait(timeout=15)
    except Exception:
        client.proc.terminate()

    records = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    print("--- proxy notes ---")
    for record in records:
        if record.get("kind") == "note":
            print(f"  {record.get('event')}: "
                  f"{ {k: v for k, v in record.items() if k not in ('kind', 'event', 't', 'ts', 'dir')} }")

    print("\n--- agent stderr (where the reason lives) ---")
    stderr = "".join(r.get("text", "") for r in records if r.get("kind") == "stderr")
    interesting = [
        line for line in stderr.splitlines()
        if any(word in line.lower() for word in
               ("mcp", "error", "fail", "connect", "spawn", "enoent", "module"))
    ]
    for line in interesting[-40:] or ["(nothing matching mcp/error/fail)"]:
        print(f"  {line[:300]}")

    print("\n--- tool server's own log ---")
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    logs = sorted(Path(state, "smrt", "tools").glob("tools-*.jsonl"))
    if not logs:
        print("  none — the server never got as far as running its own code")
    else:
        for line in logs[-1].read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            print(f"  {record.get('outcome'):8} {record.get('method')} "
                  f"{record.get('tool') or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
