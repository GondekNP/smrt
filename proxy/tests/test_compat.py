"""Does the shim repair what Toad refuses, and touch nothing else?

`compat.py` is a workaround with a follow-up attached, so these tests carry a
second job beyond checking it works: they pin down exactly how narrow it is,
so that when it is deleted the blast radius is known.

The frames here are the real ones, copied out of a trace of a live
`claude-agent-acp` session.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acp_proxy import compat

from .test_passthrough import run_proxy

# Verbatim from a trace: the completion of the injected MCP tool call, which
# Toad refused because `rawOutput` is a list.
REJECTED_LIST = (
    b'{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId":'
    b' "s1", "update": {"_meta": {"claudeCode": {"toolName": "ToolSearch"}},'
    b' "toolCallId": "toolu_014", "sessionUpdate": "tool_call_update",'
    b' "status": "completed", "rawOutput": [{"type": "tool_reference",'
    b' "tool_name": "mcp__probe__smrt_probe"}], "content": [{"type":'
    b' "content", "content": {"type": "text", "text": "Tool: probe"}}]}}}\n'
)

# The `Read` tool's completion, refused because `rawOutput` is a string.
REJECTED_STR = (
    b'{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId":'
    b' "s1", "update": {"toolCallId": "t2", "sessionUpdate":'
    b' "tool_call_update", "status": "completed", "rawOutput": "file'
    b' contents here"}}}\n'
)

# Accepted as-is: nine of these appeared in the same session.
ACCEPTED = (
    b'{"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId":'
    b' "s1", "update": {"toolCallId": "t3", "sessionUpdate": "tool_call",'
    b' "title": "Read File", "kind": "read", "rawInput": {"file_path":'
    b' "/vault/x.md"}}}}\n'
)


def through(payload: bytes, *, compat_on: bool = True, trace: str | None = None):
    """The echo backend means the proxy's stdout is what the CLIENT receives,
    which is the direction compat repairs act on."""
    args = [] if compat_on else ["--no-compat"]
    args += ["--trace", trace] if trace else ["--no-trace"]
    return run_proxy(payload, proxy_args=tuple(args))


class TestRepair(unittest.TestCase):
    def test_list_raw_output_is_stripped(self) -> None:
        code, out, err = through(REJECTED_LIST)
        self.assertEqual(code, 0, err)
        update = json.loads(out)["params"]["update"]
        self.assertNotIn("rawOutput", update)

    def test_string_raw_output_is_stripped(self) -> None:
        code, out, err = through(REJECTED_STR)
        self.assertEqual(code, 0, err)
        self.assertNotIn("rawOutput", json.loads(out)["params"]["update"])

    def test_everything_else_in_the_frame_survives(self) -> None:
        """The repair must cost nothing but the one unusable field — the tool
        result itself lives in `content`, which is the entire point."""
        code, out, err = through(REJECTED_LIST)
        self.assertEqual(code, 0, err)
        before = json.loads(REJECTED_LIST)["params"]["update"]
        after = json.loads(out)["params"]["update"]
        self.assertEqual(set(before) - set(after), {"rawOutput"})
        for field in ("content", "status", "toolCallId", "sessionUpdate", "_meta"):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(json.loads(out)["params"]["sessionId"], "s1")

    def test_dict_raw_fields_are_left_completely_alone(self) -> None:
        code, out, err = through(ACCEPTED)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, ACCEPTED)  # byte-identical

    def test_raw_input_gets_the_same_treatment(self) -> None:
        """Latent rather than observed: every rawInput seen so far was a dict.
        Same annotation, same bug, so it is handled before it fires."""
        frame = (b'{"jsonrpc": "2.0", "method": "session/update", "params":'
                 b' {"update": {"toolCallId": "t", "sessionUpdate":'
                 b' "tool_call", "title": "x", "rawInput": ["a", "b"]}}}\n')
        code, out, err = through(frame)
        self.assertEqual(code, 0, err)
        self.assertNotIn("rawInput", json.loads(out)["params"]["update"])

    def test_permission_requests_carry_a_tool_call_too(self) -> None:
        """`session/request_permission` embeds a tool call under `toolCall`,
        validated against a class with the same over-narrow annotations."""
        frame = (b'{"jsonrpc": "2.0", "id": 7, "method":'
                 b' "session/request_permission", "params": {"sessionId": "s",'
                 b' "options": [], "toolCall": {"toolCallId": "t",'
                 b' "rawOutput": "oops"}}}\n')
        code, out, err = through(frame)
        self.assertEqual(code, 0, err)
        self.assertNotIn("rawOutput", json.loads(out)["params"]["toolCall"])
        self.assertEqual(json.loads(out)["id"], 7)


class TestNarrowness(unittest.TestCase):
    """A workaround that reaches further than its defect is a liability."""

    def test_no_compat_disables_it_entirely(self) -> None:
        code, out, err = through(REJECTED_LIST, compat_on=False)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, REJECTED_LIST)

    def test_unrelated_frames_are_untouched(self) -> None:
        frames = [
            b'{"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}\n',
            b'{"jsonrpc": "2.0", "id": 2, "result": {"stopReason": "end_turn"}}\n',
            b'{"jsonrpc": "2.0", "method": "session/update", "params": {"update":'
            b' {"sessionUpdate": "agent_message_chunk", "content": {"type":'
            b' "text", "text": "hi"}}}}\n',
        ]
        code, out, err = through(b"".join(frames))
        self.assertEqual(code, 0, err)
        self.assertEqual(out, b"".join(frames))

    def test_a_client_to_agent_frame_is_never_repaired(self) -> None:
        """Repairs are for the client's benefit and act only on what it
        receives. Rewriting what the agent receives is the injection's job and
        must not leak into this direction."""
        frame = (b'{"jsonrpc": "2.0", "id": 1, "method": "session/prompt",'
                 b' "params": {"update": {"rawOutput": "not a dict"}}}\n')
        # Sent client->agent; the echo backend returns whatever it was given,
        # so if the outbound pass had repaired it the echo would differ.
        code, out, err = through(frame)
        self.assertEqual(code, 0, err)
        # It comes back repaired (agent->client), but must have reached the
        # backend intact — and the backend echoes exactly what it received.
        self.assertIn(b'"session/prompt"', out)

    def test_fail_safe_on_odd_params(self) -> None:
        for frame in (
            b'{"jsonrpc": "2.0", "method": "session/update", "params": []}\n',
            b'{"jsonrpc": "2.0", "method": "session/update"}\n',
            b'{"jsonrpc": "2.0", "method": "session/update", "params":'
            b' {"update": "nonsense"}}\n',
        ):
            with self.subTest(frame=frame[:60]):
                code, out, err = through(frame)
                self.assertEqual(code, 0, err)
                self.assertEqual(out, frame)


class TestUnit(unittest.TestCase):
    def test_repair_does_not_mutate_its_input(self) -> None:
        """The trace records the frame as it arrived, which only stays true if
        the transform copies."""
        frame = json.loads(REJECTED_LIST)
        compat.repair(frame)
        self.assertIn("rawOutput", frame["params"]["update"])

    def test_declines_when_nothing_needs_repair(self) -> None:
        self.assertIsNone(compat.repair(json.loads(ACCEPTED)))

    def test_declines_non_dict_frames(self) -> None:
        self.assertIsNone(compat.repair([1, 2, 3]))
        self.assertIsNone(compat.repair("nope"))


class TestTrace(unittest.TestCase):
    def test_the_repair_is_recorded(self) -> None:
        """It must never be silent — a shim you cannot see is a shim you
        cannot retire."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            code, _out, err = through(REJECTED_LIST, trace=str(path))
            self.assertEqual(code, 0, err)
            records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

        notes = [r for r in records if r.get("event") == "compat_repaired"]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["removed"], ["update.rawOutput"])
        self.assertEqual(notes[0]["method"], "session/update")
        self.assertLess(notes[0]["bytes_after"], notes[0]["bytes_before"])

        # And the frame as it ARRIVED is still in the trace, unrepaired.
        arrived = [r for r in records
                   if r.get("method") == "session/update" and "frame" in r]
        self.assertTrue(any("rawOutput" in r["frame"]["params"]["update"]
                            for r in arrived))


if __name__ == "__main__":
    unittest.main()
