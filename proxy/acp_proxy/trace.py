"""JSONL record of every frame that crosses the proxy.

**This is the proxy's only diagnostic channel, and that is not a style
preference.** Toad pipes the agent's stderr and never drains it during normal
operation — it reads the pipe exactly once, after stdout hits EOF, and only
when the exit code is non-zero (`toad/acp/agent.py:639-647`). Anything that
logged steadily to stderr would fill the pipe buffer and block forever, taking
the session down. So diagnostics land here instead, including the backend's own
stderr, which the proxy drains on the backend's behalf.

Every write is flushed. A trace is most useful when the thing being diagnosed
killed the process, which is exactly when a buffered tail would be lost.

Nothing here may raise into the pump. A trace is an observation; losing it is a
degraded proxy, while crashing on it is a broken one.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Direction labels. ASCII rather than arrows so `grep` and `jq -r` stay easy.
CLIENT_TO_AGENT = "client->agent"
AGENT_TO_CLIENT = "agent->client"


def default_trace_path() -> Path:
    """Where traces go when no path is given.

    Under the XDG state dir, which `bin/smrt` bind-mounts out of the container,
    so a trace is readable on the host without digging into a stopped
    container. Toad's own transcripts land beside it under `toad/logs/`.
    """
    if explicit := os.environ.get("SMRT_ACP_TRACE"):
        return Path(explicit)
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(state) / "smrt" / "acp" / f"acp-{stamp}-{os.getpid()}.jsonl"


def classify(frame: object) -> str:
    """Name the JSON-RPC shape of a frame.

    Matches how Toad itself dispatches (`toad/acp/agent.py:606-620`): a
    top-level `result` or `error` is a response, a list is a batch, and
    anything else with a `method` is an incoming call. Recorded so a trace can
    be read without re-deriving this each time.
    """
    if isinstance(frame, list):
        return "batch"
    if not isinstance(frame, dict):
        return "unknown"
    if "result" in frame:
        return "response"
    if "error" in frame:
        return "error"
    if "method" in frame:
        return "request" if "id" in frame else "notification"
    return "unknown"


class Trace:
    """Append-only JSONL writer. Thread-safe; three pumps write to it."""

    def __init__(self, path: Path | None) -> None:
        self._lock = threading.Lock()
        self._fh = None
        self._t0 = time.monotonic()
        self.path = path

        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = path.open("a", encoding="utf-8")
        except OSError as error:
            # One line, to stderr, then carry on untraced. Bounded output is
            # safe; a proxy that refused to start because it could not open a
            # log file would be worse than a proxy with no log.
            self.path = None
            _warn(f"could not open trace {path}: {error}")

    # -- writing ---------------------------------------------------------

    def _write(self, record: dict) -> None:
        if self._fh is None:
            return
        record["t"] = round(time.monotonic() - self._t0, 6)
        record["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            line = json.dumps(record, ensure_ascii=False, default=repr)
            with self._lock:
                self._fh.write(line + "\n")
                self._fh.flush()
        except (OSError, ValueError):
            pass  # see the module docstring: never raise into the pump

    def frame(
        self,
        direction: str,
        raw: bytes,
        parsed: object = None,
        parse_error: str | None = None,
    ) -> None:
        """Record one protocol frame.

        `raw` is what actually went on the wire; `parsed` is the proxy's
        reading of it. Both are kept because the point of step 1 is proving
        they agree — the `bytes` count is what makes a byte-faithful forward
        checkable from the trace alone.
        """
        record: dict = {"dir": direction, "bytes": len(raw)}
        if parse_error is not None:
            record["kind"] = "unparsed"
            record["parse_error"] = parse_error
            # Keep enough to identify it without dumping an arbitrary blob.
            record["raw_prefix"] = raw[:512].decode("utf-8", "replace")
        else:
            record["kind"] = classify(parsed)
            if isinstance(parsed, dict):
                if (method := parsed.get("method")) is not None:
                    record["method"] = method
                if "id" in parsed:
                    record["id"] = parsed["id"]
            record["frame"] = parsed
        self._write(record)

    def note(self, event: str, **fields: object) -> None:
        """Record something that is not a frame: lifecycle, warnings."""
        self._write({"dir": "proxy", "kind": "note", "event": event, **fields})

    def backend_stderr(self, text: str) -> None:
        """Record the backend's stderr, which the proxy drains rather than
        relays — see the module docstring."""
        self._write({"dir": "agent-stderr", "kind": "stderr", "text": text})

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None


def _warn(message: str) -> None:
    """A single bounded line on stderr.

    Reserved for failures that happen before or instead of a session, where a
    non-zero exit follows and Toad will therefore actually read it. Never for
    anything per-frame.
    """
    import sys

    try:
        sys.stderr.write(f"smrt-acp-proxy: {message}\n")
        sys.stderr.flush()
    except OSError:
        pass
