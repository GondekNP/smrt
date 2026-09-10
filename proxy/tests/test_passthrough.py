"""Does the proxy change anything? It must not.

Every assertion here is about transparency, because that is the entire claim of
step 1 in `docs/proxy.md`. Stdlib only, no Docker, no agent, no credentials —
`scripts/test-proxy.sh` runs it inside the image against the real interpreter,
but it runs anywhere with a python3.

The interesting cases are the ones a parse-and-re-serialize proxy would fail
while looking correct: odd whitespace, a trailing zero on a float, a one-line
batch array, an integer id. Those are here deliberately.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROXY_ROOT = HERE.parent
FAKE_BACKEND = HERE / "fake_backend.py"

TIMEOUT = 30


def _env() -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PROXY_ROOT) + (
        os.pathsep + existing if existing else ""
    )
    return env


def run_proxy(
    stdin: bytes,
    mode: str = "echo",
    mode_args: tuple[str, ...] = (),
    proxy_args: tuple[str, ...] = ("--no-trace",),
    backend: tuple[str, ...] | None = None,
) -> tuple[int, bytes, bytes]:
    """Drive the proxy end to end and return `(returncode, stdout, stderr)`."""
    if backend is None:
        backend = (sys.executable, str(FAKE_BACKEND), mode, *mode_args)

    cmd = [sys.executable, "-m", "acp_proxy", *proxy_args, "--", *backend]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_env(),
    )
    try:
        out, err = proc.communicate(stdin, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise AssertionError(
            f"proxy did not finish within {TIMEOUT}s "
            f"(stderr: {err[:2000]!r})"
        ) from None
    return proc.returncode, out, err


# Frames chosen so that any re-serialization shows up as a byte difference.
FRAMES = [
    # What Toad actually sends first (toad/acp/agent.py:717-734).
    b'{"jsonrpc": "2.0", "method": "initialize", "params": {"protocolVersion":'
    b' 1, "clientCapabilities": {"fs": {"readTextFile": true, "writeTextFile":'
    b' true}, "terminal": true}, "clientInfo": {"name": "toad", "title":'
    b' "Toad", "version": "0.6.20"}}, "id": 1}\n',
    # The frame this whole component exists because of.
    b'{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd": "/vault",'
    b' "mcpServers": []}, "id": 2}\n',
    # Unusual whitespace: survives forwarding, would not survive a dump().
    b'{ "jsonrpc" : "2.0" ,  "id" : 3 , "method" : "session/set_mode" }\n',
    # A float whose textual form json.dumps() would normalize away.
    b'{"jsonrpc": "2.0", "id": 4, "result": {"cost": 1.10, "big": 1e3}}\n',
    # A method from a version of ACP this proxy has never heard of, carrying
    # fields it does not know. The drift strategy depends on this passing.
    b'{"jsonrpc": "2.0", "method": "session/_unstable_future", "params":'
    b' {"whatever": {"nested": [1, 2, 3]}}, "id": 5}\n',
    # A batch: Toad emits these as one line when several calls share a request
    # block (toad/jsonrpc.py:403-417).
    b'[{"jsonrpc": "2.0", "method": "a", "id": 6}, {"jsonrpc": "2.0",'
    b' "method": "b", "id": 7}]\n',
    # Non-ASCII, unescaped. json.dumps() with default settings would \\u-escape.
    b'{"jsonrpc": "2.0", "id": 8, "method": "session/prompt", "params":'
    b' {"prompt": [{"type": "text", "text": "Fisher information \xe2\x80\x94'
    b' derive it \xf0\x9f\x90\xb8"}]}}\n',
    # A notification, which has no id and must not acquire one.
    b'{"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId":'
    b' "s1", "_meta": {}}}\n',
    # Not JSON at all. Forwarded regardless: an unreadable frame is not a
    # reason to drop a session.
    b"this is not json\n",
    # Blank line, which every ACP implementation skips and none should eat.
    b"\n",
]


class TestByteFidelity(unittest.TestCase):
    def test_every_frame_round_trips_byte_identical(self) -> None:
        payload = b"".join(FRAMES)
        code, out, err = run_proxy(payload)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, payload)

    def test_frame_larger_than_the_asyncio_line_limit(self) -> None:
        """64 KiB is where asyncio.StreamReader gives up, and base64 image
        blocks from `submit_artifact` will be bigger. Threads exist for this."""
        blob = "A" * (256 * 1024)
        frame = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "session/prompt",
                "params": {
                    "prompt": [
                        {
                            "type": "image",
                            "mimeType": "image/jpeg",
                            "data": blob,
                        }
                    ]
                },
            }
        ).encode() + b"\n"
        self.assertGreater(len(frame), 64 * 1024)

        code, out, err = run_proxy(frame)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, frame)

    def test_frame_without_trailing_newline_is_still_forwarded(self) -> None:
        code, out, err = run_proxy(b"", mode="half-line")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, b'{"jsonrpc":"2.0","id":1,"result":{}}')


class TestLifecycle(unittest.TestCase):
    def test_backend_stderr_does_not_deadlock(self) -> None:
        """Toad never drains the agent's stderr (toad/acp/agent.py:639-647), so
        the proxy has to. Without that this test hangs rather than fails."""
        payload = b'{"jsonrpc": "2.0", "id": 1, "method": "initialize"}\n'
        code, out, err = run_proxy(
            payload, mode="stderr-flood", mode_args=("1048576",)
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(out, payload)

    def test_backend_stderr_is_recorded_as_it_arrives(self) -> None:
        """Found in a real session, not by reading the code: with `read()` the
        backend's whole log landed in the trace in one lump at shutdown,
        because `read(n)` on a buffered stream waits for all n bytes. Never
        deadlocked, but the timestamps were fiction — and a backend that logged
        and then hung would have shown nothing.

        The discriminator is ordering: the backend writes to stderr, pauses,
        then echoes. With `read1` the stderr record precedes the frame.
        """
        payload = b'{"jsonrpc": "2.0", "id": 1, "method": "initialize"}\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            code, out, err = run_proxy(
                payload, mode="stderr-early",
                proxy_args=("--trace", str(path)),
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(out, payload)
            records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

        stderr_at = [r["t"] for r in records if r["kind"] == "stderr"]
        frame_at = [r["t"] for r in records if r["kind"] == "response"
                    or r.get("method") == "initialize"]
        self.assertTrue(stderr_at, "backend stderr was never recorded")
        self.assertIn("starting up", "".join(
            r["text"] for r in records if r["kind"] == "stderr"))
        # The echoed frame comes back after the backend's 0.5s pause, so a
        # correctly-drained stderr record must predate it.
        self.assertLess(min(stderr_at), max(frame_at))

    def test_backend_exit_code_propagates(self) -> None:
        code, _out, _err = run_proxy(b"", mode="exit", mode_args=("42",))
        self.assertEqual(code, 42)

    def test_missing_backend_fails_loudly(self) -> None:
        code, out, err = run_proxy(
            b"", backend=("smrt-no-such-backend-exists",)
        )
        self.assertEqual(code, 127)
        self.assertEqual(out, b"")
        self.assertIn(b"not found", err)


class TestCli(unittest.TestCase):
    def _cli(self, *args: str) -> tuple[int, bytes, bytes]:
        proc = subprocess.run(
            [sys.executable, "-m", "acp_proxy", *args],
            capture_output=True,
            env=_env(),
            timeout=TIMEOUT,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_help(self) -> None:
        code, out, _err = self._cli("--help")
        self.assertEqual(code, 0)
        self.assertIn(b"smrt-acp-proxy", out)

    def test_no_backend_is_a_usage_error(self) -> None:
        code, _out, err = self._cli("--no-trace")
        self.assertEqual(code, 2)
        self.assertIn(b"no backend command", err)

    def test_unknown_backend_name(self) -> None:
        code, _out, err = self._cli("--backend", "nope")
        self.assertEqual(code, 2)
        self.assertIn(b"unknown backend", err)

    def test_backend_shorthand_matches_toads_own_definitions(self) -> None:
        from acp_proxy.__main__ import BACKENDS

        self.assertEqual(BACKENDS["claude"], ["claude-agent-acp"])
        self.assertEqual(BACKENDS["opencode"], ["opencode", "acp"])


class TestTrace(unittest.TestCase):
    def test_trace_records_the_two_facts_step_one_measures(self) -> None:
        """`docs/OPEN.md` decision 5 rests on `mcpServers` being empty, and the
        protocol version was assumed rather than seen. The trace should answer
        both without a jq incantation."""
        frames = [
            b'{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd":'
            b' "/vault", "mcpServers": []}, "id": 1}\n',
            b'{"jsonrpc": "2.0", "id": 2, "result": {"protocolVersion": 1}}\n',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            code, _out, err = run_proxy(
                b"".join(frames), proxy_args=("--trace", str(path))
            )
            self.assertEqual(code, 0, err)

            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        events = {r.get("event"): r for r in records if r.get("kind") == "note"}
        self.assertIn("mcp_servers_observed", events)
        self.assertEqual(events["mcp_servers_observed"]["count"], 0)
        self.assertIn("protocol_version_negotiated", events)
        self.assertEqual(events["protocol_version_negotiated"]["version"], 1)

        # Both directions are recorded, and the byte counts are the wire's.
        directions = {r["dir"] for r in records}
        self.assertIn("client->agent", directions)
        self.assertIn("agent->client", directions)
        forwarded = [r for r in records if r["dir"] == "agent->client" and "bytes" in r]
        self.assertEqual(
            sorted(r["bytes"] for r in forwarded),
            sorted(len(f) for f in frames),
        )

    def test_unparseable_frame_is_flagged_but_still_forwarded(self) -> None:
        payload = b"definitely not json\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            code, out, err = run_proxy(
                payload, proxy_args=("--trace", str(path))
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(out, payload)
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        self.assertTrue(any(r.get("kind") == "unparsed" for r in records))


if __name__ == "__main__":
    unittest.main()
