"""The pump: newline-delimited JSON-RPC forwarded in both directions.

Three design choices here are load-bearing, and each one is a response to
something specific rather than a preference.

**Frames are forwarded as the original bytes.** Only frames the proxy
deliberately changes get re-serialized, and there are exactly two of those:
`session/new` / `session/load` when MCP servers are being injected
(`inject.py`), and tool-call frames Toad would otherwise refuse
(`compat.py`).
A parse-and-re-serialize pass-through tests identically and then becomes a
second source of failure: unknown fields from a newer ACP version, number formatting,
unicode escaping, integer request ids, and one-line JSON batch arrays. Since the
version-drift strategy is "handle a few methods, let the rest through
untouched", the transport has to be *incapable* of mangling a method it does not
understand.

**Threads, not asyncio.** `asyncio.StreamReader` caps lines at 64 KiB by
default and raises above it. ACP prompts carry base64 image blocks — precisely
what `submit_artifact` will return — so real frames exceed that. Toad had to
raise its own limit to 10 MB for the same reason, which is also the effective
ceiling on a frame regardless of what the proxy does.
`io.BufferedReader.readline()` has no such cap.

**The backend's stderr is drained here and written to the trace, never
relayed.** Toad pipes the agent's stderr and reads it only after stdout EOF on a
non-zero exit (`toad/acp/agent.py:639-647`), so a backend that logs steadily
would otherwise fill the pipe buffer and hang the session.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading

from . import compat, inject, mdlog
from .trace import AGENT_TO_CLIENT, CLIENT_TO_AGENT, Trace, _warn

# How long to let the backend exit on its own after its stdin is closed, before
# escalating. Toad itself sends SIGTERM with no escalation and no grace
# (`toad/acp/agent.py:651-661`), so being tidier than our own client is enough.
_STDIN_EOF_GRACE = 2.0
_TERM_GRACE = 3.0

# Reading the backend's stderr in modest chunks rather than lines, because
# nothing guarantees an agent's log output is newline-terminated, and a
# half-written line must not be able to stall the drain. Read with `read1`,
# never `read`: on a buffered stream `read(n)` waits for the FULL n bytes, so
# a chatty-but-not-4KB-chatty agent had its whole log appear in the trace in
# one lump at shutdown. It never deadlocked — we were still draining — but the
# timestamps were fiction, and a backend that logged something and then hung
# would have shown nothing at all, which is exactly when you want it.
_STDERR_CHUNK = 4096


def run(
    backend_cmd: list[str],
    trace: Trace,
    mcp_servers: list[dict] | None = None,
    compat_repairs: bool = True,
    md: mdlog.MdLog | None = None,
) -> int:
    """Proxy stdio between our own client and `backend_cmd`. Returns an exit
    code suitable for `sys.exit`.

    With `mcp_servers`, `session/new` and `session/load` are rewritten to carry
    them — see `inject.py`. With `compat_repairs`, tool-call frames Toad would
    refuse are repaired on the way back — see `compat.py`, and note that module
    is a workaround with a follow-up attached, not a feature.
    """
    return _Proxy(backend_cmd, trace, mcp_servers or [], compat_repairs,
                  md).run()


class _Proxy:
    def __init__(
        self,
        backend_cmd: list[str],
        trace: Trace,
        mcp_servers: list[dict] | None = None,
        compat_repairs: bool = True,
        md: mdlog.MdLog | None = None,
    ) -> None:
        self.backend_cmd = backend_cmd
        self.trace = trace
        self.mcp_servers = mcp_servers or []
        self.compat_repairs = compat_repairs
        # Observation only, and fed before any rewriting: the mirror records
        # the session as the agent sent it, not as the client would accept it.
        self.md = md if md is not None else mdlog.MdLog(None)
        self.proc: subprocess.Popen[bytes] | None = None
        self._shutdown_lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    def run(self) -> int:
        # Toad owns the terminal and the foreground process group, so it also
        # owns Ctrl-C. A proxy that died on SIGINT would drop the session out
        # from under a client that was only trying to cancel a turn.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, self._on_sigterm)

        # A list, not a shell string: Toad has already run this through
        # `sh -c` (it spawns with `create_subprocess_shell`), and a second
        # round of shell interpretation here would mangle any argument
        # containing a space or a quote.
        try:
            self.proc = subprocess.Popen(
                self.backend_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            return self._fail_to_start(f"backend not found: {self.backend_cmd[0]}", 127)
        except PermissionError:
            return self._fail_to_start(
                f"backend not executable: {self.backend_cmd[0]}", 126
            )
        except OSError as error:
            return self._fail_to_start(f"could not start backend: {error}", 1)

        self.trace.note(
            "start",
            backend=self.backend_cmd,
            pid=self.proc.pid,
            trace_path=str(self.trace.path) if self.trace.path else None,
        )

        assert self.proc.stdin and self.proc.stdout and self.proc.stderr
        threads = [
            self._spawn("client->agent", self._pump_inbound),
            self._spawn("agent->client", self._pump_outbound),
            self._spawn("agent-stderr", self._drain_stderr),
        ]

        code = self.proc.wait()

        # Let the outbound pump finish flushing whatever the backend wrote just
        # before exiting; without this the last frames of a turn can be lost.
        threads[1].join(timeout=5.0)

        self.md.close()
        self.trace.note("exit", code=code)
        try:
            sys.stdout.buffer.flush()
            sys.stdout.buffer.close()
        except OSError:
            pass
        return code

    def _spawn(self, name: str, target) -> threading.Thread:
        # Daemon threads throughout: `sys.stdin.buffer.readline()` blocks in a
        # way nothing can interrupt, so a non-daemon reader would keep the
        # process alive after the backend was gone.
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        return thread

    def _fail_to_start(self, message: str, code: int) -> int:
        # The one case where stderr is the right channel: we are about to exit
        # non-zero, which is exactly when Toad reads it and surfaces it to the
        # user as agent-launch failure. Bounded, one line, then gone.
        _warn(message)
        self.trace.note("start_failed", error=message, code=code)
        return code

    def _on_sigterm(self, _signum: int, _frame: object) -> None:
        self.trace.note("sigterm")
        self._stop_backend()

    def _stop_backend(self) -> None:
        proc = self.proc
        if proc is None:
            return
        with self._shutdown_lock:
            if proc.poll() is not None:
                return
            try:
                proc.terminate()
            except (ProcessLookupError, OSError):
                return
            try:
                proc.wait(timeout=_TERM_GRACE)
            except subprocess.TimeoutExpired:
                self.trace.note("escalate_to_kill")
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass

    # -- pumps -----------------------------------------------------------

    def _pump_inbound(self) -> None:
        """Client -> backend. Ends when our own stdin closes."""
        assert self.proc is not None and self.proc.stdin is not None
        self._pump(sys.stdin.buffer, self.proc.stdin, CLIENT_TO_AGENT)

        # Our client is gone. Close the backend's stdin so it can shut down the
        # way it prefers, and only escalate if it does not take the hint.
        self.trace.note("client_eof")
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=_STDIN_EOF_GRACE)
        except subprocess.TimeoutExpired:
            self._stop_backend()

    def _pump_outbound(self) -> None:
        """Backend -> client. Ends when the backend's stdout closes."""
        assert self.proc is not None and self.proc.stdout is not None
        self._pump(self.proc.stdout, sys.stdout.buffer, AGENT_TO_CLIENT)
        self.trace.note("agent_eof")

    def _pump(self, src, dst, direction: str) -> None:
        while True:
            try:
                line = src.readline()
            except (OSError, ValueError):
                # ValueError covers a read from a stream closed under us during
                # teardown, which is routine rather than exceptional.
                return
            if not line:
                return

            # Toad skips blank lines on the way in and so does every other ACP
            # implementation; forward them, but don't clutter the trace.
            out = line
            if line.strip():
                out = self._handle(direction, line)

            if not line.endswith(b"\n"):
                # EOF mid-frame: the peer died partway through writing. Forward
                # what there is, faithfully, and say so.
                self.trace.note("partial_frame", direction=direction, bytes=len(line))

            try:
                dst.write(out)
                dst.flush()
            except (BrokenPipeError, OSError):
                self.trace.note("write_failed", direction=direction)
                return

    def _handle(self, direction: str, line: bytes) -> bytes:
        """Trace the frame and return the bytes to forward.

        Almost always the bytes that arrived. The one exception is the
        `session/new` injection, which is the only rewriting this proxy does —
        everything else is observation.
        """
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            # Forwarded anyway. If a future ACP version, or a backend bug,
            # produces something this proxy cannot read, being unable to read
            # it is not a reason to break the session.
            self.trace.frame(direction, line, parse_error=str(error))
            return line

        # Trace and observe the frame as it ARRIVED, before any rewriting, so
        # `mcp_servers_observed` keeps reporting what the client really sent.
        self.trace.frame(direction, line, parsed)
        self._observe(direction, parsed)
        self.md.observe(direction, parsed)

        if direction == CLIENT_TO_AGENT and self.mcp_servers:
            return self._rewrite(
                line, parsed,
                lambda f: inject.rewrite(f, self.mcp_servers),
                note="mcp_injected", detail="added", failed="inject_failed",
                # Injection happens once per session and is the thing most
                # worth being able to read back verbatim.
                include_frame=True,
            )

        if direction == AGENT_TO_CLIENT and self.compat_repairs:
            return self._rewrite(
                line, parsed, compat.repair,
                note="compat_repaired", detail="removed", failed="compat_failed",
                # Repairs fire several times a turn, and the frame as it
                # arrived is already traced beside this note, so recording the
                # rewrite too would only bloat the trace.
                include_frame=False,
            )

        return line

    def _rewrite(self, line: bytes, parsed: object, transform,
                 *, note: str, detail: str, failed: str,
                 include_frame: bool) -> bytes:
        """Apply one rewriting pass, fail-safe.

        The `except Exception` is deliberately broad. Rewriting is a
        convenience layered on a transport that already works; if it raises for
        any reason at all, the original frame goes through and the session
        survives. Losing the tool server, or a tool result, is recoverable —
        losing the session is not.

        The cost of that choice is that a bug in a transform presents as
        *something quietly missing* rather than as an error, so the `failed`
        note is the only tell. A real bug was caught this way during
        development; it is worth grepping traces for.
        """
        try:
            result = transform(parsed)
        except Exception as error:  # noqa: BLE001 — see above
            self.trace.note(failed, error=repr(error))
            return line

        if result is None:
            return line

        rewritten, changed = result
        fields: dict = {
            "method": parsed.get("method") if isinstance(parsed, dict) else None,
            detail: changed,
            "bytes_before": len(line),
            "bytes_after": len(rewritten),
        }
        if include_frame:
            fields["frame"] = json.loads(rewritten)
        self.trace.note(note, **fields)
        return rewritten

    def _observe(self, direction: str, parsed: object) -> None:
        """Pull out the two facts step 1 exists to measure.

        `docs/OPEN.md` decision 5 rests on Toad hardcoding `mcpServers` to
        `[]`, which until now was read out of Toad's source rather than seen on
        the wire; and the negotiated protocol version was assumed to be 1
        because that is the constant Toad sends, though the agent is free to
        answer with a different one and Toad never checks. Both become plain
        lines in the trace instead of a `jq` exercise.
        """
        if not isinstance(parsed, dict):
            return
        try:
            if direction == CLIENT_TO_AGENT and parsed.get("method") in (
                "session/new",
                "session/load",
            ):
                servers = (parsed.get("params") or {}).get("mcpServers")
                self.trace.note(
                    "mcp_servers_observed",
                    method=parsed["method"],
                    count=len(servers) if isinstance(servers, list) else None,
                    names=[
                        s.get("name") for s in servers if isinstance(s, dict)
                    ]
                    if isinstance(servers, list)
                    else None,
                )
            elif direction == AGENT_TO_CLIENT and isinstance(
                result := parsed.get("result"), dict
            ):
                if (version := result.get("protocolVersion")) is not None:
                    self.trace.note("protocol_version_negotiated", version=version)
        except (AttributeError, TypeError):
            pass  # an observation is never worth a failure

    def _drain_stderr(self) -> None:
        """Read the backend's stderr so it cannot block, and file it away.

        See the module docstring: Toad does not drain this pipe, so somebody
        has to.
        """
        assert self.proc is not None and self.proc.stderr is not None
        stream = self.proc.stderr
        while True:
            try:
                chunk = stream.read1(_STDERR_CHUNK)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            self.trace.backend_stderr(chunk.decode("utf-8", "replace"))
