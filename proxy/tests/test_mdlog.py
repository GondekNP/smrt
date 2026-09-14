"""Does the mirror say what happened, and does it ever spoil a question?

The second one is the whole reason this lives in the proxy. `learn`'s md-log
keeps the answer out of the question block by convention — the extension
chooses not to write it. Here it is a property of what the module is given:
the mirror reads a pose call's *output*, and `QuizPosed` is built to be
exactly what the learner may see. So there is no moment at which the key is in
hand and a rule has to hold.

These tests feed frames of the real shape and then assert against the file.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acp_proxy import mdlog

# What `quiz` actually receives. The key is here, and this is the frame the
# mirror must never write from.
QUIZ_INPUT = {
    "prompt": "Which carries the information about precision?",
    "options": [
        {"id": "a", "text": "The curvature of the LL near the MLE."},
        {"id": "b", "text": "The maximized LL value itself."},
    ],
    "correct_option_id": "a",
    "explanation": "Curvature is the observed Fisher information.",
}

# What `quiz` returns: shuffled, relabelled, and with no key.
QUIZ_OUTPUT = {
    "question_id": "quiz-abc123",
    "prompt": "Which carries the information about precision?",
    "options": [
        {"id": "A", "text": "The maximized LL value itself."},
        {"id": "B", "text": "The curvature of the LL near the MLE."},
    ],
    "hint": None,
    "warnings": [],
}

QUIZ_RESULT = {
    "pick_correct": False,
    "reason_verdict": "coherent",
    "diagnosis": "misconception",
    "next_step": "Dig into its extent.",
    "explanation": "Curvature is the observed Fisher information.",
}

EXPLAIN_OUTPUT = {
    "question_id": "explain-def456",
    "question": "Why does inverting the Hessian give standard errors?",
    "rubric_items": 3,
    "vocabulary": [{"name": "Fisher information", "tier": "advisory"}],
}

EXPLAIN_RESULT = {
    "hit": ["the score has mean zero"],
    "missed": ["identify the negative expected Hessian"],
    "passed": False,
    "rubric": ["the score has mean zero",
               "differentiate the log-likelihood twice",
               "identify the negative expected Hessian"],
    "next_step": "Back up one level.",
    "vocabulary": [],
}


def update(**fields) -> dict:
    return {"jsonrpc": "2.0", "method": "session/update",
            "params": {"sessionId": "s1", "update": fields}}


def completed(call_id: str, raw_output: dict, raw_input: dict | None = None) -> dict:
    body = {"sessionUpdate": "tool_call_update", "toolCallId": call_id,
            "status": "completed", "rawOutput": raw_output}
    if raw_input is not None:
        body["rawInput"] = raw_input
    return update(**body)


def text(chunk: str) -> dict:
    return update(sessionUpdate="agent_message_chunk",
                  content={"type": "text", "text": chunk})


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log = mdlog.MdLog(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def read(self) -> str:
        self.log.close()
        return self.log.path.read_text(encoding="utf-8")

    def feed(self, *frames: dict) -> None:
        for frame in frames:
            self.log.observe("agent->client", frame)


class TestTheAnswerIsNeverSpoiled(Base):
    def test_the_key_is_absent_even_when_the_frame_carries_it(self) -> None:
        """`rawInput` is on the same frame. The mirror reads `rawOutput`."""
        self.feed(completed("t1", QUIZ_OUTPUT, raw_input=QUIZ_INPUT))
        written = self.read()
        self.assertIn("Which carries the information", written)
        self.assertFalse(mdlog.contains_key(written, QUIZ_INPUT))
        self.assertNotIn("correct_option_id", written)

    def test_the_explanation_appears_only_after_grading(self) -> None:
        self.feed(completed("t1", QUIZ_OUTPUT, raw_input=QUIZ_INPUT))
        before = self.log.path.read_text(encoding="utf-8")
        self.assertNotIn("observed Fisher information", before)

        self.feed(completed("t2", QUIZ_RESULT))
        after = self.read()
        self.assertIn("observed Fisher information", after)
        self.assertLess(after.index("Which carries"),
                        after.index("observed Fisher information"))

    def test_the_rubric_is_withheld_at_posing(self) -> None:
        """The count, never the items. That there are three things to cover is
        part of the question; what they are is the answer."""
        self.feed(completed("t1", EXPLAIN_OUTPUT))
        written = self.log.path.read_text(encoding="utf-8")
        self.assertIn("Rubric committed: 3 items", written)
        self.assertNotIn("the score has mean zero", written)

    def test_the_explain_question_is_not_restated(self) -> None:
        """A tool call cannot ask anyone anything, so the question was posed in
        prose and is already in the file above this block."""
        self.feed(completed("t1", EXPLAIN_OUTPUT))
        self.assertNotIn("Why does inverting the Hessian",
                         self.log.path.read_text(encoding="utf-8"))

    def test_the_rubric_is_written_once_graded(self) -> None:
        """Plaintext only now, so it can be checked against the committed
        hash."""
        self.feed(completed("t1", EXPLAIN_OUTPUT), completed("t2", EXPLAIN_RESULT))
        written = self.read()
        self.assertIn("the score has mean zero", written)
        self.assertIn("Rubric, as committed", written)


class TestWhatItRecords(Base):
    def test_the_question_is_written_as_displayed(self) -> None:
        """Shuffled order and A/B labels — what was actually asked, not what
        was authored."""
        self.feed(completed("t1", QUIZ_OUTPUT, raw_input=QUIZ_INPUT))
        written = self.read()
        self.assertIn("- **A.** The maximized LL value itself.", written)
        self.assertIn("- **B.** The curvature of the LL near the MLE.", written)
        self.assertLess(written.index("**A.**"), written.index("**B.**"))

    def test_the_learners_prompt_is_recorded(self) -> None:
        self.log.observe("client->agent", {
            "jsonrpc": "2.0", "id": 3, "method": "session/prompt",
            "params": {"sessionId": "s1", "prompt": [
                {"type": "text", "text": "teach me maximum likelihood"}]},
        })
        self.assertIn("teach me maximum likelihood", self.read())

    def test_streamed_text_is_joined_into_one_block(self) -> None:
        """Chunks are deltas. Writing each one would shred every paragraph."""
        self.feed(text("The curvature "), text("of the "), text("log-likelihood."))
        self.assertIn("The curvature of the log-likelihood.", self.read())

    def test_latex_survives_untouched(self) -> None:
        """The entire point of the file: it is read where math renders."""
        self.feed(text(r"$$I(\theta) = -E[\ell''(\theta)]$$"))
        self.assertIn(r"$$I(\theta) = -E[\ell''(\theta)]$$", self.read())

    def test_machinery_is_not_mirrored(self) -> None:
        """A lesson, not a transcript of every file read."""
        self.feed(completed("t1", {"stdout": "pdftotext output", "code": 0}))
        self.assertNotIn("pdftotext output", self.read())

    def test_a_repeated_completion_is_written_once(self) -> None:
        """`tool_call` and `tool_call_update` can both carry the result."""
        self.feed(completed("t1", QUIZ_OUTPUT), completed("t1", QUIZ_OUTPUT))
        self.assertEqual(self.read().count("Which carries the information"), 1)


class TestItNeverBreaksTheSession(unittest.TestCase):
    """Same rule as the trace: losing the mirror is a degraded session,
    crashing on it is a broken one."""

    def test_a_disabled_log_writes_nothing_and_does_not_raise(self) -> None:
        log = mdlog.MdLog(None)
        log.observe("agent->client", completed("t1", QUIZ_OUTPUT))
        log.close()
        self.assertIsNone(log.path)

    def test_an_unwritable_directory_is_survivable(self) -> None:
        log = mdlog.MdLog(Path("/proc/one/cannot/write/here"))
        log.observe("agent->client", completed("t1", QUIZ_OUTPUT))
        log.close()
        self.assertIsNone(log.path)

    def test_a_malformed_frame_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = mdlog.MdLog(Path(tmp))
            for junk in (None, [], "text", {"params": None},
                         update(sessionUpdate="tool_call_update",
                                status="completed", rawOutput="not a dict")):
                log.observe("agent->client", junk)
            log.close()
            self.assertTrue(log.path.exists())


class TestWhereItGoes(unittest.TestCase):
    def test_off_disables_it(self) -> None:
        import os
        before = os.environ.get("SMRT_MD_LOG")
        os.environ["SMRT_MD_LOG"] = "off"
        try:
            self.assertIsNone(mdlog.default_dir())
        finally:
            if before is None:
                del os.environ["SMRT_MD_LOG"]
            else:
                os.environ["SMRT_MD_LOG"] = before

    def test_an_explicit_path_wins(self) -> None:
        import os
        before = os.environ.get("SMRT_MD_LOG")
        os.environ["SMRT_MD_LOG"] = "/tmp/somewhere"
        try:
            self.assertEqual(mdlog.default_dir(), Path("/tmp/somewhere"))
        finally:
            if before is None:
                del os.environ["SMRT_MD_LOG"]
            else:
                os.environ["SMRT_MD_LOG"] = before


if __name__ == "__main__":
    unittest.main()


class TestFramesAsTheyReallyArrive(Base):
    """Shapes measured on the wire, not assumed.

    `claude-agent-acp` sends an MCP tool's structured output as a JSON
    *string* and `rawInput` as null. The first version of this module required
    a dict, matched nothing, and silently wrote a whole session with no
    questions and no grades in it — while looking like it worked, because the
    agent's own prose was still being mirrored.
    """

    @staticmethod
    def as_string(call_id: str, payload: dict) -> dict:
        import json
        return update(sessionUpdate="tool_call_update", toolCallId=call_id,
                      status="completed", rawInput=None,
                      rawOutput=json.dumps(payload))

    def test_a_json_string_payload_is_read(self) -> None:
        self.feed(self.as_string("t1", QUIZ_RESULT))
        self.assertIn("misconception", self.read())

    def test_content_blocks_are_unwrapped(self) -> None:
        import json
        self.feed(update(sessionUpdate="tool_call_update", toolCallId="t1",
                         status="completed",
                         rawOutput=[{"type": "text",
                                     "text": json.dumps(QUIZ_RESULT)}]))
        self.assertIn("misconception", self.read())

    def test_a_string_that_is_not_json_is_ignored(self) -> None:
        self.feed(update(sessionUpdate="tool_call_update", toolCallId="t1",
                         status="completed", rawOutput="README.md\nnotes\n"))
        self.assertNotIn("README", self.read())


class TestItDoesNotDuplicateTheQuestion(Base):
    """The agent must pose the question in prose — a tool call cannot ask
    anyone anything — so the tool's copy underneath would show it twice, in
    plainer notation than the version actually read."""

    POSED = ("Which converges?\n\n- **A.** The first one.\n"
             "- **B.** The second one.\n")

    def test_the_block_is_skipped_when_prose_already_posed_it(self) -> None:
        self.feed(text(self.POSED), completed("t1", QUIZ_OUTPUT))
        written = self.read()
        self.assertEqual(written.count("The maximized LL value itself."), 0)
        self.assertIn("- **A.** The first one.", written)

    def test_the_block_is_written_when_prose_did_not(self) -> None:
        """The fallback, and also the tell that the skill's format slipped."""
        self.feed(text("Here is a question for you."),
                  completed("t1", QUIZ_OUTPUT))
        self.assertIn("- **A.** The maximized LL value itself.", self.read())


class TestMessagesDoNotRunTogether(Base):
    """Two agent messages either side of a tool call were written as one
    paragraph, which is how `…not teaching yet.**Probe 1**…` happened."""

    def test_a_tool_call_ends_the_message_before_it(self) -> None:
        self.feed(text("First message."),
                  update(sessionUpdate="tool_call", toolCallId="t9",
                         status="pending", rawInput={"command": "ls"}),
                  text("Second message."))
        written = self.read()
        self.assertNotIn("First message.Second message.", written)
        self.assertIn("First message.", written)
        self.assertIn("Second message.", written)


class TestDrawingsSurvive(Base):
    """Figures reach the log as text in the agent's message — there is no
    machinery for them, which is the point. These assert the mirror does not
    become machinery by accident."""

    SVG = ('<svg viewBox="0 0 100 50" xmlns="http://www.w3.org/2000/svg">\n'
           '  <circle cx="50" cy="25" r="20" fill="none" '
           'stroke="currentColor"/>\n</svg>')

    def test_inline_svg_passes_through_byte_for_byte(self) -> None:
        self.feed(text(self.SVG))
        self.assertIn(self.SVG, self.read())

    def test_a_fenced_mermaid_block_survives(self) -> None:
        block = '```mermaid\ngraph LR\n  A["π P = π"] --> B\n```'
        self.feed(text(block))
        self.assertIn(block, self.read())

    def test_a_drawing_split_across_chunks_is_rejoined(self) -> None:
        """Streaming deltas cut wherever they like, including mid-tag."""
        half = len(self.SVG) // 2
        self.feed(text(self.SVG[:half]), text(self.SVG[half:]))
        self.assertIn(self.SVG, self.read())
