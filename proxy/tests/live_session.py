#!/usr/bin/env python3
"""Drive one real ACP session through the proxy, end to end.

NOT part of the unit suite — the filename is deliberately not `test_*` so
`unittest discover` skips it. This one costs a real model call and needs a
logged-in backend, so it is run on purpose:

    smrt -- python3 /workspace/proxy/tests/live_session.py

It exists because the interesting question about injection cannot be answered
offline. "The frame was rewritten" is a unit test; "the agent spawned the
server, listed its tools, and the model actually called one" needs a live
session, and until something calls a tool the injection is only plausibly
working.

Being an ACP *client* rather than a TUI has a second benefit: it exercises the
inbound half of the protocol — `session/request_permission` in particular,
which a real tool call triggers and which had never crossed the proxy.

It declares only the capabilities it actually implements. Claiming
`writeTextFile` or `terminal` and then answering `-32601` would be a worse
client than an honest, small one.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

PROMPT = (
    "Call the smrt_probe tool, then reply with exactly the token string it "
    "returns and nothing else."
)
PROBE_TOKEN = "SMRT_PROBE_OK"
TIMEOUT = 180.0


class Client:
    def __init__(self, command: list[str]) -> None:
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        self.inbox: queue.Queue = queue.Queue()
        self._next_id = 0
        self.chunks: list[str] = []
        self.saw: list[str] = []
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if line.strip():
                try:
                    self.inbox.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
        self.inbox.put(None)

    def _write(self, message: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message).encode() + b"\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict) -> int:
        self._next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        )
        return self._next_id

    def call(self, method: str, params: dict) -> dict:
        """Send a request and pump the connection until its response lands,
        answering anything the agent asks along the way."""
        want = self.request(method, params)
        while True:
            message = self.inbox.get(timeout=TIMEOUT)
            if message is None:
                raise RuntimeError(f"agent closed the connection awaiting {method}")

            if "method" not in message:  # a response
                if message.get("id") != want:
                    continue
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result") or {}

            self._handle(message)

    def _handle(self, message: dict) -> None:
        method = message["method"]
        params = message.get("params") or {}
        self.saw.append(method)

        if method == "session/update":
            update = params.get("update") or {}
            kind = update.get("sessionUpdate")
            self.saw.append(f"  update:{kind}")
            if kind == "agent_message_chunk":
                self.chunks.append((update.get("content") or {}).get("text", ""))
            return

        if "id" not in message:
            return  # any other notification: nothing owed

        if method == "session/request_permission":
            # Pick the first option that grants rather than refuses. Doing this
            # automatically is only acceptable because this is a scripted test
            # against a read-only subject; a real client asks a human.
            options = params.get("options") or []
            allow = next(
                (o for o in options if str(o.get("kind", "")).startswith("allow")),
                options[0] if options else None,
            )
            self.saw.append(f"  permission:{(allow or {}).get('kind')}")
            self._write({"jsonrpc": "2.0", "id": message["id"], "result": {
                "outcome": {"outcome": "selected", "optionId": allow["optionId"]}
                if allow else {"outcome": "cancelled"}
            }})
            return

        if method == "fs/read_text_file":
            try:
                text = Path(params["path"]).read_text(encoding="utf-8")
                self._write({"jsonrpc": "2.0", "id": message["id"],
                             "result": {"content": text}})
            except OSError as error:
                self._write({"jsonrpc": "2.0", "id": message["id"],
                             "error": {"code": -32603, "message": str(error)}})
            return

        self._write({"jsonrpc": "2.0", "id": message["id"],
                     "error": {"code": -32601, "message": f"not implemented: {method}"}})


def main() -> int:
    probe_log = Path(os.environ.get("SMRT_MCP_PROBE_LOG", "/tmp/live-probe.jsonl"))
    if probe_log.exists():
        probe_log.unlink()

    command = [
        "smrt-acp-proxy", "--backend", "claude", "--mcp", "probe=smrt-mcp-probe",
    ]
    print(f"$ {' '.join(command)}\n")
    client = Client(command)

    init = client.call("initialize", {
        "protocolVersion": 1,
        "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": False}},
        "clientInfo": {"name": "smrt-live-session", "title": "SMRT live session",
                       "version": "0.1.0"},
    })
    print(f"protocolVersion negotiated : {init.get('protocolVersion')}")

    session = client.call("session/new", {"cwd": "/vault", "mcpServers": []})
    print(f"sessionId                  : {session.get('sessionId')}")

    print(f"\nprompt: {PROMPT}\n")
    result = client.call("session/prompt", {
        "sessionId": session["sessionId"],
        "prompt": [{"type": "text", "text": PROMPT}],
    })

    reply = "".join(client.chunks)
    print(f"stopReason                 : {result.get('stopReason')}")
    print(f"reply                      : {reply.strip()!r}")

    print("\ninbound methods the proxy relayed:")
    for line in client.saw:
        print(f"  {line}")

    print(f"\nprobe log ({probe_log}):")
    events = []
    if probe_log.exists():
        for line in probe_log.read_text().splitlines():
            record = json.loads(line)
            events.append(record["event"])
            print(f"  {record['event']:<14} "
                  f"{json.dumps({k: v for k, v in record.items() if k not in ('ts', 'event')})}")
    else:
        print("  MISSING — the agent never spawned the injected server")

    ok = PROBE_TOKEN in reply and "tool_called" in events
    print(f"\nVERDICT: {'the model called the injected tool' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
