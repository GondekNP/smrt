"""Are the tools actually reachable over MCP, and do refusals arrive as errors?

`test_tools.py` calls the functions directly, which proves the grading logic
and nothing about the wire. This drives a real client against a real server
process over stdio — the same transport `claude-agent-acp` will use once the
proxy injects this server into `session/new`.

It also exercises the thing the in-memory commitment store depends on: that a
`question_id` from one call is still valid on the next, because both land in
the same process.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

TIMEOUT = 60


def drive(body, command=None, args=None, cwd=None, env=None):
    """Run one client session against a freshly spawned server."""

    async def run():
        params = StdioServerParameters(
            command=command or sys.executable,
            args=args if command else ["-m", "vault_tools.server"],
            cwd=cwd,
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                return await body(session, init)

    return asyncio.run(asyncio.wait_for(run(), TIMEOUT))


def payload(result):
    """The structured half of a tool result, whichever casing the SDK uses."""
    return (getattr(result, "structuredContent", None)
            or getattr(result, "structured_content", None))


def failed(result):
    """`isError` in the schema, `is_error` on the model object."""
    flag = getattr(result, "is_error", None)
    return getattr(result, "isError", flag)


def text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


def schema(tool):
    return getattr(tool, "inputSchema", None) or getattr(tool, "input_schema")


QUIZ = {
    "prompt": "Which is the MLE of a normal mean?",
    "options": [{"id": "a", "text": "the sample mean"},
                {"id": "b", "text": "the sample median"}],
    "correct_option_id": "a",
    "explanation": "The mean maximizes the normal likelihood.",
}

RUBRIC = ["the score has mean zero",
          "differentiate the log-likelihood twice",
          "identify the negative expected Hessian"]

# Deliberately shares no phrase with any rubric item, so "the rubric does not
# leak into the posed payload" is actually testable.
EXPLAIN_Q = "Where does curvature come into the variance bound?"


class TestSurface(unittest.TestCase):
    def test_exactly_the_four_implemented_tools_are_offered(self) -> None:
        async def body(session, _init):
            return [t.name for t in (await session.list_tools()).tools]

        self.assertEqual(sorted(drive(body)),
                         ["answer_quiz", "explain", "grade_explain", "quiz"])

    def test_instructions_reach_the_client(self) -> None:
        """The one place to state discipline not attached to a single tool."""
        async def body(_session, init):
            return init.instructions or ""

        self.assertIn("never an ask", drive(body))

    def test_the_dataclass_signature_became_a_real_schema(self) -> None:
        """`list[QuizOption]` has to arrive as a referenced object type, not as
        an opaque array — this is the leverage the SDK was chosen for."""
        async def body(session, _init):
            tool = next(t for t in (await session.list_tools()).tools
                        if t.name == "quiz")
            return schema(tool)

        found = drive(body)
        self.assertIn("QuizOption", json.dumps(found))
        self.assertEqual(
            sorted(found["required"]),
            ["correct_option_id", "explanation", "options", "prompt"],
        )


class TestTheWrapperOnPath(unittest.TestCase):
    """`vault-tools` is the command the proxy injects, so it has to work when
    spawned the way a client spawns it -- which is not the way a shell does.

    This caught a real failure: the MCP stdio client passes only HOME, PATH and
    TERM, so the image's PYTHONPATH was gone and `python3 -m vault_tools.server`
    could not find its own package. The client saw "Connection closed" and
    nothing else. The wrapper now sets PYTHONPATH itself.
    """

    def test_serving_through_the_wrapper(self) -> None:
        if shutil.which("vault-tools") is None:
            self.skipTest("vault-tools is not on PATH (running outside the image?)")

        async def body(session, _init):
            return [t.name for t in (await session.list_tools()).tools]

        # `cwd` is load-bearing, and getting it wrong is why the first version
        # of this test passed against the broken wrapper: `python3 -m` puts the
        # working directory on sys.path, so running from the tools directory
        # imports the package no matter what PYTHONPATH says. A real server is
        # spawned with the SESSION's cwd -- /vault -- where it is not.
        self.assertIn("quiz",
                      drive(body, command="vault-tools", args=[], cwd="/"))

    def test_serving_with_a_hostile_path(self) -> None:
        """The wrapper must not depend on which `python3` a client's PATH finds.

        This image has three: the pixi `python` environment (the only one with
        the MCP SDK), Toad's own, and Debian's. Launched from Toad the server
        died with `ModuleNotFoundError: No module named 'mcp'` while working
        from another client in the same image -- and the client reported only
        "Connection failed (CONNECTION_CLOSED)", which is why this is worth a
        test rather than vigilance.

        A PATH containing only the system directories is the worst case: it
        finds a python3, and that python3 is wrong.
        """
        if shutil.which("vault-tools") is None:
            self.skipTest("vault-tools is not on PATH (running outside the image?)")

        async def body(session, _init):
            return [t.name for t in (await session.list_tools()).tools]

        self.assertIn("quiz", drive(
            body,
            command=shutil.which("vault-tools"),
            args=[],
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "")},
        ))


class TestRoundTrip(unittest.TestCase):
    def test_pose_then_answer_within_one_session(self) -> None:
        """A wrong pick with coherent reasoning is a misconception, and the
        server has to remember the key between the two calls to say so."""
        async def body(session, _init):
            posed = payload(await session.call_tool("quiz", QUIZ))
            answered = await session.call_tool("answer_quiz", {
                "question_id": posed["question_id"],
                "pick": "b",
                "reason": "the median is robust, so it must be the MLE",
                # Coherent, not sound: a position someone could hold, and
                # wrong. "sound" here would make it a slip.
                "reason_verdict": "coherent",
            })
            return posed, payload(answered)

        posed, result = drive(body)
        self.assertEqual(posed["warnings"], [])
        self.assertNotIn("likelihood", json.dumps(posed))
        self.assertFalse(result["pick_correct"])
        self.assertEqual(result["diagnosis"], "misconception")
        self.assertIn("likelihood", result["explanation"])

    def test_explain_commits_a_hash_and_grades_against_it(self) -> None:
        async def body(session, _init):
            posed = payload(await session.call_tool(
                "explain", {"question": EXPLAIN_Q, "rubric": RUBRIC, "concepts": []}))
            graded = payload(await session.call_tool("grade_explain", {
                "question_id": posed["question_id"],
                "answer": "curvature of the log-likelihood",
                "hit": RUBRIC[:1],
                "missed": RUBRIC[1:],
            }))
            return posed, graded

        posed, graded = drive(body)
        for item in RUBRIC:
            self.assertNotIn(item, json.dumps(posed))
        self.assertEqual(len(posed["rubric_sha256"]), 64)
        self.assertFalse(graded["passed"])
        self.assertEqual(graded["rubric_sha256"], posed["rubric_sha256"])
        self.assertEqual(graded["rubric"], RUBRIC)


class TestRefusals(unittest.TestCase):
    """A refusal has to arrive as a tool error the model can read and act on,
    not as a dead server or a silent success."""

    def test_a_softened_rubric_is_refused_over_the_wire(self) -> None:
        async def body(session, _init):
            posed = payload(await session.call_tool(
                "explain", {"question": "q", "rubric": RUBRIC, "concepts": []}))
            return await session.call_tool("grade_explain", {
                "question_id": posed["question_id"],
                "answer": "hand-wavy",
                "hit": ["mentioned curvature, close enough"],
                "missed": [],
            })

        result = drive(body)
        self.assertTrue(failed(result))
        self.assertIn("not in the committed rubric", text(result))

    def test_the_server_survives_a_refusal(self) -> None:
        """The next call still works — a validation error must not wedge the
        session, since these tools sit on the critical path of a lesson."""
        async def body(session, _init):
            bad = await session.call_tool("quiz", {**QUIZ, "correct_option_id": "z"})
            good = await session.call_tool("quiz", QUIZ)
            return bad, payload(good)

        bad, good = drive(body)
        self.assertTrue(failed(bad))
        self.assertIn("not one of", text(bad))
        self.assertTrue(good["question_id"].startswith("quiz-"))


class TestTheCallLog(unittest.TestCase):
    """The log is the only window into a server four processes down, and the
    records worth having are the refusals — whether the model then corrects
    itself is the question it exists to answer.

    `env` is passed explicitly because the client decides the server's
    environment and by default hands over only HOME, PATH and TERM: the same
    sanitization that broke the wrapper silently drops SMRT_TOOLS_LOG.
    """

    def test_a_refusal_is_recorded_as_a_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tools.jsonl"

            async def body(session, _init):
                await session.call_tool("explain", {"question": EXPLAIN_Q,
                                                    "rubric": RUBRIC,
                                                    "concepts": []})
                await session.call_tool("grade_explain", {
                    "question_id": "explain-nope",
                    "answer": "x", "hit": [], "missed": [],
                })

            drive(body, env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", ""),
                "SMRT_TOOLS_LOG": str(path),
            })

            records = [json.loads(l) for l in
                       path.read_text(encoding="utf-8").splitlines() if l.strip()]

        calls = {r["tool"]: r for r in records if r["method"] == "tools/call"}
        self.assertEqual(calls["explain"]["outcome"], "ok")
        self.assertEqual(calls["grade_explain"]["outcome"], "refused")
        self.assertIn("unknown question_id", calls["grade_explain"]["error"])
        # The arguments are recorded, which is what makes a refusal diagnosable
        # rather than merely visible.
        self.assertEqual(calls["explain"]["arguments"]["rubric"], RUBRIC)

    def test_logging_off_is_honoured(self) -> None:
        async def body(session, _init):
            return [t.name for t in (await session.list_tools()).tools]

        self.assertIn("quiz", drive(body, env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "SMRT_TOOLS_LOG": "off",
        }))


if __name__ == "__main__":
    unittest.main()
