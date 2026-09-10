"""A minimal MCP server whose only job is to prove the injection worked.

Deliberately not a real tool. The question "does `session/new` injection put a
server into the session" and the question "are the four question types the
right ones" are separate, and answering them in one step would mean a failure
could be either. This is the same reason the pass-through was built before the
injection: isolate the wiring, then judge the design.

So this server exposes one pointless tool and **writes a log of everything
that happens to it**. That log is the evidence: if the agent spawned it and
asked for its tools, the injected frame was accepted and acted on, which is the
whole claim under test. Nothing else here is meant to survive.

Replaced by `tools/vault_tools/server.py` once that stops raising
`NotImplementedError`.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROBE_TOKEN = "SMRT_PROBE_OK"
SERVER_NAME = "smrt-mcp-probe"
TOOL_NAME = "smrt_probe"

# The MCP version to fall back on if the client does not state one. The
# handshake echoes whatever the client asks for instead, which is what keeps a
# throwaway probe from becoming a version-compatibility problem of its own.
FALLBACK_PROTOCOL = "2025-06-18"


def log_path() -> Path:
    if explicit := os.environ.get("SMRT_MCP_PROBE_LOG"):
        return Path(explicit)
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return Path(state) / "smrt" / "acp" / f"mcp-probe-{os.getpid()}.jsonl"


class Probe:
    def __init__(self) -> None:
        self.path = log_path()
        self._fh = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
        except OSError:
            pass  # a probe that cannot log is still a probe that can answer
        self.log("spawned", argv=sys.argv, pid=os.getpid(), cwd=os.getcwd())

    def log(self, event: str, **fields: object) -> None:
        if self._fh is None:
            return
        try:
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **fields,
            }
            self._fh.write(json.dumps(record, default=repr) + "\n")
            self._fh.flush()
        except (OSError, ValueError):
            pass

    # -- protocol --------------------------------------------------------

    def handle(self, message: dict) -> dict | None:
        """Return a response, or `None` for a notification."""
        method = message.get("method")
        params = message.get("params") or {}
        self.log("received", method=method, id=message.get("id"))

        if method == "initialize":
            # Echo the client's version rather than asserting our own.
            version = params.get("protocolVersion") or FALLBACK_PROTOCOL
            return self._ok(message, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            })

        if method == "tools/list":
            # Reaching here is the proof: the agent accepted the injected
            # session/new, spawned this process, and asked what it offers.
            self.log("tools_listed")
            return self._ok(message, {"tools": [{
                "name": TOOL_NAME,
                "description": (
                    "Returns a fixed token proving the SMRT tool server was "
                    "reachable from this session. Takes no arguments."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }]})

        if method == "tools/call":
            name = params.get("name")
            self.log("tool_called", tool=name, arguments=params.get("arguments"))
            if name != TOOL_NAME:
                return self._err(message, -32602, f"no such tool: {name}")
            stamp = datetime.now(timezone.utc).isoformat()
            return self._ok(message, {
                "content": [{"type": "text", "text": f"{PROBE_TOKEN} {stamp}"}],
                "isError": False,
            })

        if method == "ping":
            return self._ok(message, {})

        if method and method.startswith("notifications/"):
            return None

        if "id" not in message:
            return None  # any other notification
        return self._err(message, -32601, f"method not found: {method}")

    def _ok(self, message: dict, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}

    def _err(self, message: dict, code: int, text: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": code, "message": text},
        }


def main() -> int:
    probe = Probe()
    out = sys.stdout.buffer
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            probe.log("unparsed", error=str(error), raw=line[:256].decode("utf-8", "replace"))
            continue
        try:
            response = probe.handle(message)
        except Exception as error:  # a probe must not die on a surprise
            probe.log("handler_failed", error=repr(error))
            continue
        if response is not None:
            out.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()
    probe.log("stdin_closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
