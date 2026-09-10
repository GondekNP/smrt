#!/usr/bin/env python3
"""A minimal ACP *agent*, for proving what a client accepts.

Test infrastructure, not part of the unit suite. `fake_backend.py` echoes
frames and is enough to test the proxy's transport; this one speaks enough of
ACP to get a real client through a handshake and then hands it a frame chosen
to provoke a specific reaction.

It exists for one question the unit tests cannot answer: `compat.py` strips a
field *because Toad refuses frames containing it* — but that claim is about
Toad's behaviour, not ours. Pointing a real Toad at this agent, with and
without the repair, turns the claim into a measurement. No model, no
credentials, no terminal.

Everything the client sends is logged to $FAKE_AGENT_LOG, including the
client's error replies, which is where Toad's rejection shows up.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

LOG = os.environ.get("FAKE_AGENT_LOG", "/tmp/fake-acp-agent.jsonl")
SESSION_ID = "fake-session-1"


def log(event: str, **fields: object) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": event, **fields}, default=repr) + "\n")
    except OSError:
        pass


def send(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message).encode() + b"\n")
    sys.stdout.buffer.flush()


def provoke() -> None:
    """Send the frames under test, once the session exists.

    A `tool_call` the client should accept, then a `tool_call_update` whose
    `rawOutput` is a list — valid ACP (`Option<serde_json::Value>`), refused by
    Toad 0.6.20, and repaired by `compat.py`.
    """
    send({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": SESSION_ID,
        "update": {"sessionUpdate": "tool_call", "toolCallId": "tc1",
                   "title": "probe", "kind": "other", "status": "pending"},
    }})
    time.sleep(0.2)
    send({"jsonrpc": "2.0", "method": "session/update", "params": {
        "sessionId": SESSION_ID,
        "update": {"sessionUpdate": "tool_call_update", "toolCallId": "tc1",
                   "status": "completed",
                   "rawOutput": [{"type": "tool_reference", "tool_name": "x"}],
                   "content": [{"type": "content",
                                "content": {"type": "text", "text": "done"}}]},
    }})


def main() -> int:
    log("started", argv=sys.argv, pid=os.getpid())
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        log("received", method=method, id=message.get("id"), frame=message)

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {
                "protocolVersion": 1,
                "agentCapabilities": {"loadSession": False,
                                      "promptCapabilities": {"image": False}},
                "agentInfo": {"name": "fake-acp-agent", "version": "0.1.0"},
                "authMethods": [],
            }})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": message["id"],
                  "result": {"sessionId": SESSION_ID}})
            threading.Thread(target=provoke, daemon=True).start()
        elif method == "session/prompt":
            send({"jsonrpc": "2.0", "id": message["id"],
                  "result": {"stopReason": "end_turn"}})
        elif "id" in message and method:
            send({"jsonrpc": "2.0", "id": message["id"],
                  "error": {"code": -32601, "message": f"no: {method}"}})
    log("stdin_closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
