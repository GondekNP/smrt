"""JSONL record of every call the tool server handles.

The reason to have this at all: a tool server is spawned by the agent, four
processes deep, and its stdout is protocol. Without a file there is nowhere to
look when a lesson goes wrong — and the ACP trace one layer up shows only what
the *agent* chose to report about the call, not what the server was asked or
what it refused.

Under the XDG state dir, which `bin/smrt` bind-mounts out of the container, so
this is readable on the host beside the proxy's traces.

Refusals are the interesting records. A `ToolError` is the server telling the
model it got the contract wrong, and whether the model then corrects itself is
the question this file exists to answer.

Nothing here may raise into a tool call. Losing a log line is a degraded
server; failing a lesson over one is a broken one.

**A log contains full question, rubric and answer-key content.** It is a
debugging artifact, not something to paste around — and not something to read
mid-lesson if you intend to answer the questions honestly.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def default_log_path() -> Path:
    if explicit := os.environ.get("SMRT_TOOLS_LOG"):
        return Path(explicit)
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(state) / "smrt" / "tools" / f"tools-{stamp}-{os.getpid()}.jsonl"


class Log:
    """Append-only JSONL, flushed per line, silent on failure."""

    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._handle = None
        self.path = path

        if os.environ.get("SMRT_TOOLS_LOG") == "off":
            return
        try:
            target = path or default_log_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            self._handle = target.open("a", encoding="utf-8")
            self.path = target
        except OSError:
            # No log is survivable. Refusing to serve over it is not.
            self._handle = None

    def write(self, **fields: object) -> None:
        if self._handle is None:
            return
        record = {
            "t": round(time.monotonic(), 6),
            "ts": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        try:
            line = json.dumps(record, ensure_ascii=False, default=repr)
        except (TypeError, ValueError):
            return
        try:
            with self._lock:
                self._handle.write(line + "\n")
                self._handle.flush()
        except (OSError, ValueError):
            self._handle = None


def _refusal(result: object) -> str | None:
    """The refusal text, if this result is one.

    A `ToolError` does not propagate to the middleware as an exception: MCP
    reports a tool's own failure as a *successful* response carrying
    `isError`, and only protocol-level faults raise. So a refusal has to be
    read off the result, and without this every refusal logged as `ok` —
    which is exactly the outcome worth seeing.
    """
    # At this tier the result is a plain dict -- `{"content": [...],
    # "isError": true}` -- not a validated model, so `getattr` finds nothing.
    # Both shapes are handled anyway: which one arrives is an SDK internal.
    root = getattr(result, "root", result)
    if isinstance(root, dict):
        flag = root.get("isError", root.get("is_error"))
        content = root.get("content") or []
        text = "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    else:
        flag = getattr(root, "is_error", getattr(root, "isError", None))
        content = getattr(root, "content", None) or []
        text = "".join(getattr(block, "text", "") for block in content)
    if not flag:
        return None
    return text[:1000] or "(no message)"


def middleware(log: Log):
    """A `ServerMiddleware` that records every inbound request and its outcome.

    Middleware rather than a decorator on each tool, for two reasons: it is one
    hook instead of four, and a failure inside a handler arrives here as a
    raised exception — so refusals are recorded without threading logging
    through every `raise` site.

    Requests are logged on the way out, with their outcome, rather than on the
    way in. A call that never returns is still visible: it is the one with no
    record.
    """

    async def record(ctx, call_next):
        started = time.monotonic()
        detail: dict[str, object] = {"method": ctx.method}
        params = getattr(ctx, "params", None)
        if ctx.method == "tools/call" and isinstance(params, dict):
            detail["tool"] = params.get("name")
            detail["arguments"] = params.get("arguments")

        try:
            result = await call_next(ctx)
        except Exception as exc:
            # Protocol-level faults only; a tool's own refusal comes back as a
            # result, not as an exception. See `_refusal`.
            log.write(
                outcome="failed",
                error=str(exc),
                error_type=type(exc).__name__,
                ms=round((time.monotonic() - started) * 1000, 1),
                **detail,
            )
            raise

        refusal = _refusal(result) if ctx.method == "tools/call" else None
        log.write(
            outcome="refused" if refusal else "ok",
            ms=round((time.monotonic() - started) * 1000, 1),
            **({"error": refusal} if refusal else {}),
            **detail,
        )
        return result

    return record
