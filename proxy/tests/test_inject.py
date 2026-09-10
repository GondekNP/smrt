"""Does injection put the server in, and leave everything else alone?

The second question matters as much as the first. Step 1 established that the
proxy is byte-faithful; adding the first frame the proxy deliberately rewrites
is exactly the change that could quietly cost that property, so most of these
tests are about what did *not* change.

The echo backend makes this directly observable: whatever the proxy writes to
the backend comes straight back, so the proxy's stdout *is* the frame the
backend received.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from acp_proxy import inject

from .test_passthrough import run_proxy

# A spec whose command really exists, since parse_spec resolves it and refuses
# to start otherwise. Arguments included so shlex splitting is covered too.
SPEC = f"probe={sys.executable} -c pass"

NEW = (b'{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd":'
       b' "/vault", "mcpServers": []}, "id": 2}\n')
LOAD = (b'{"jsonrpc": "2.0", "method": "session/load", "params": {"cwd":'
        b' "/vault", "mcpServers": [], "sessionId": "s1"}, "id": 3}\n')
INIT = (b'{"jsonrpc": "2.0", "method": "initialize", "params":'
        b' {"protocolVersion": 1}, "id": 1}\n')
PROMPT = (b'{"jsonrpc": "2.0", "method": "session/prompt", "params":'
          b' {"sessionId": "s1", "prompt": [{"type": "text", "text": "hi"}]}, "id": 4}\n')


def with_injection(payload: bytes, *, spec: str = SPEC, trace: str | None = None):
    args = ["--mcp", spec]
    args += ["--trace", trace] if trace else ["--no-trace"]
    return run_proxy(payload, proxy_args=tuple(args))


class TestRewriting(unittest.TestCase):
    def test_session_new_gains_the_server(self) -> None:
        code, out, err = with_injection(NEW)
        self.assertEqual(code, 0, err)
        frame = json.loads(out)
        servers = frame["params"]["mcpServers"]
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["name"], "probe")
        self.assertEqual(servers[0]["command"], sys.executable)
        self.assertEqual(servers[0]["args"], ["-c", "pass"])

    def test_everything_else_about_the_frame_survives(self) -> None:
        code, out, err = with_injection(NEW)
        self.assertEqual(code, 0, err)
        frame = json.loads(out)
        original = json.loads(NEW)
        self.assertEqual(frame["id"], original["id"])
        self.assertIsInstance(frame["id"], int)  # Toad correlates on int ids
        self.assertEqual(frame["jsonrpc"], "2.0")
        self.assertEqual(frame["method"], "session/new")
        self.assertEqual(frame["params"]["cwd"], "/vault")
        self.assertEqual(set(frame["params"]), set(original["params"]))

    def test_session_load_is_injected_too(self) -> None:
        """Resume passes `[]` as well, so injecting only into session/new would
        give you tools in fresh sessions and lose them on resume."""
        code, out, err = with_injection(LOAD)
        self.assertEqual(code, 0, err)
        frame = json.loads(out)
        self.assertEqual(len(frame["params"]["mcpServers"]), 1)
        self.assertEqual(frame["params"]["sessionId"], "s1")

    def test_no_other_frame_is_touched(self) -> None:
        """The pass-through property has to survive the arrival of rewriting."""
        payload = INIT + NEW + PROMPT
        code, out, err = with_injection(payload)
        self.assertEqual(code, 0, err)
        lines = out.splitlines(keepends=True)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], INIT)
        self.assertNotEqual(lines[1], NEW)      # the one we meant to change
        self.assertEqual(lines[2], PROMPT)


class TestFailSafe(unittest.TestCase):
    """Every one of these forwards the original rather than breaking a session.
    Losing the tool server is recoverable; losing the session is not."""

    def test_params_of_the_wrong_type(self) -> None:
        frame = b'{"jsonrpc": "2.0", "method": "session/new", "params": [], "id": 2}\n'
        code, out, err = with_injection(frame)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, frame)

    def test_params_missing_entirely(self) -> None:
        frame = b'{"jsonrpc": "2.0", "method": "session/new", "id": 2}\n'
        code, out, err = with_injection(frame)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, frame)

    def test_unparseable_frame(self) -> None:
        frame = b"not json at all\n"
        code, out, err = with_injection(frame)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, frame)

    def test_mcp_servers_of_the_wrong_type_is_replaced_not_refused(self) -> None:
        frame = (b'{"jsonrpc": "2.0", "method": "session/new", "params":'
                 b' {"cwd": "/v", "mcpServers": "nonsense"}, "id": 2}\n')
        code, out, err = with_injection(frame)
        self.assertEqual(code, 0, err)
        servers = json.loads(out)["params"]["mcpServers"]
        self.assertEqual([s["name"] for s in servers], ["probe"])


class TestClientServersWin(unittest.TestCase):
    """Toad sends `[]` today. A future Toad, or another client, may not."""

    def test_a_clients_own_server_is_kept_and_ours_appended(self) -> None:
        frame = (b'{"jsonrpc": "2.0", "method": "session/new", "params":'
                 b' {"cwd": "/v", "mcpServers": [{"name": "theirs",'
                 b' "command": "/bin/true", "args": [], "env": []}]}, "id": 2}\n')
        code, out, err = with_injection(frame)
        self.assertEqual(code, 0, err)
        servers = json.loads(out)["params"]["mcpServers"]
        self.assertEqual([s["name"] for s in servers], ["theirs", "probe"])

    def test_a_name_collision_leaves_the_clients_entry_alone(self) -> None:
        frame = (b'{"jsonrpc": "2.0", "method": "session/new", "params":'
                 b' {"cwd": "/v", "mcpServers": [{"name": "probe",'
                 b' "command": "/bin/true", "args": [], "env": []}]}, "id": 2}\n')
        code, out, err = with_injection(frame)
        self.assertEqual(code, 0, err)
        # Nothing to add, so nothing is rewritten at all — byte-identical.
        self.assertEqual(out, frame)


class TestSpecParsing(unittest.TestCase):
    def test_absolute_path_is_resolved(self) -> None:
        server = inject.parse_spec("p=sh")
        self.assertTrue(Path(server["command"]).is_absolute())
        self.assertEqual(server["env"], [])

    def test_missing_equals(self) -> None:
        with self.assertRaises(inject.SpecError):
            inject.parse_spec("just-a-name")

    def test_empty_command(self) -> None:
        with self.assertRaises(inject.SpecError):
            inject.parse_spec("name=")

    def test_nonexistent_command_is_refused_at_startup(self) -> None:
        """A typo must fail loudly here, not become an MCP server that
        silently never appears in the session."""
        with self.assertRaises(inject.SpecError):
            inject.parse_spec("p=smrt-definitely-not-a-real-binary")

    def test_duplicate_names_refused(self) -> None:
        code, _out, err = run_proxy(
            b"", proxy_args=("--no-trace", "--mcp", "a=sh", "--mcp", "a=sh")
        )
        self.assertEqual(code, 2)
        self.assertIn(b"duplicate --mcp names", err)


class TestMergeUnit(unittest.TestCase):
    def test_nothing_to_add_returns_none(self) -> None:
        ours = [{"name": "probe"}]
        self.assertIsNone(inject.merge([{"name": "probe"}], ours))

    def test_non_list_treated_as_empty(self) -> None:
        self.assertEqual(inject.merge(None, [{"name": "p"}]), [{"name": "p"}])

    def test_rewrite_declines_non_injectable_methods(self) -> None:
        frame = {"jsonrpc": "2.0", "method": "session/prompt", "params": {}, "id": 1}
        self.assertIsNone(inject.rewrite(frame, [{"name": "p"}]))

    def test_rewrite_declines_when_no_servers_configured(self) -> None:
        frame = json.loads(NEW)
        self.assertIsNone(inject.rewrite(frame, []))


class TestTrace(unittest.TestCase):
    def test_injection_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            code, _out, err = with_injection(NEW, trace=str(path))
            self.assertEqual(code, 0, err)
            records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

        notes = {r.get("event"): r for r in records if r.get("kind") == "note"}
        self.assertIn("mcp_injected", notes)
        self.assertEqual(notes["mcp_injected"]["added"], ["probe"])
        self.assertEqual(notes["mcp_injected"]["method"], "session/new")
        self.assertGreater(
            notes["mcp_injected"]["bytes_after"],
            notes["mcp_injected"]["bytes_before"],
        )
        # The frame is still traced as it ARRIVED, so the observation of what
        # the client really sent stays honest.
        self.assertEqual(notes["mcp_servers_observed"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
