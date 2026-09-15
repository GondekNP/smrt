"""Does the grading hold when the agent is wrong about it? It must.

The two checks worth testing are the ones the agent cannot perform on its own
behalf: `answer_quiz` computing `pick_correct` itself, and `grade_explain`
refusing a verdict that does not account for exactly the committed rubric.
Everything else here is input validation, which matters mainly because a
confusing refusal costs a turn in a live session.

Refusals are `ToolError` rather than `ValueError` on purpose: the SDK relays
only the text of an anticipated failure, and here the message is the mechanism.

Stdlib `unittest`, but not stdlib-only: importing the server imports the MCP
SDK, so this runs in the image (`scripts/test-tools.sh`), not on a bare host.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from vault_tools import ledger, server
from vault_tools.server import (
    QuizOption,
    answer_quiz,
    explain,
    grade_explain,
    quiz,
)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        server._QUIZZES.clear()
        server._EXPLAINS.clear()

    def pose(self, **over):
        kwargs = dict(
            prompt="Which estimator is the sample mean?",
            options=[
                QuizOption(id="a", text="the MLE of a normal mean"),
                QuizOption(id="b", text="the MLE of a normal variance"),
            ],
            correct_option_id="a",
            explanation="The mean maximizes the normal likelihood.",
            # These tests are about grading, not about display order. Shuffling
            # is exercised on its own in TestShuffle.
            shuffle=False,
        )
        kwargs.update(over)
        return quiz(**kwargs)


class TestQuizValidation(Base):
    def test_one_option_is_refused(self) -> None:
        with self.assertRaisesRegex(ToolError, "at least two"):
            self.pose(options=[QuizOption(id="a", text="only")])

    def test_duplicate_option_ids_are_refused(self) -> None:
        with self.assertRaisesRegex(ToolError, "duplicate option ids"):
            self.pose(options=[QuizOption(id="a", text="x"),
                               QuizOption(id="a", text="y")])

    def test_correct_option_must_exist(self) -> None:
        with self.assertRaisesRegex(ToolError, "not one of"):
            self.pose(correct_option_id="z")

    def test_explanation_is_required(self) -> None:
        """The options are forbidden to carry reasoning, so if the explanation
        is empty the reasoning exists nowhere at all."""
        with self.assertRaisesRegex(ToolError, "explanation is required"):
            self.pose(explanation="   ")


class TestQuizPosing(Base):
    def test_the_answer_key_is_not_in_the_payload(self) -> None:
        """Tool results are rendered in the client's UI, so anything returned
        here should be assumed visible to the learner immediately."""
        posed = self.pose()
        rendered = repr(posed)
        self.assertNotIn("correct_option_id", rendered)
        self.assertNotIn("maximizes the normal likelihood", rendered)

    def test_ids_are_distinct_across_questions(self) -> None:
        self.assertNotEqual(self.pose().question_id, self.pose().question_id)


class TestOptionLint(Base):
    """The tells `docs/teaching-loop.md` names, checked mechanically. Warnings
    rather than errors: a false positive must never cost a lesson."""

    def test_a_clean_question_warns_about_nothing(self) -> None:
        self.assertEqual(self.pose().warnings, [])

    def test_justification_inside_an_option_is_refused_not_warned(self) -> None:
        """Promoted from a warning on 2026-09-12. The style tells stay
        advisory; this one is structural, and a live probe showed what it
        costs -- the learner's justification can only restate the option."""
        with self.assertRaisesRegex(ToolError, "because"):
            self.pose(options=[
                QuizOption(id="a",
                           text="the mean, because it maximizes the likelihood"),
                QuizOption(id="b", text="the variance"),
            ])

    def test_the_correct_option_being_longest_is_flagged(self) -> None:
        """The number one giveaway, per rule 1."""
        posed = self.pose(options=[
            QuizOption(id="a", text="the maximum likelihood estimator of the "
                                    "mean of a normal distribution with known "
                                    "variance"),
            QuizOption(id="b", text="the median"),
            QuizOption(id="c", text="the mode"),
        ])
        self.assertTrue(any("mean distractor length" in w for w in posed.warnings))

    def test_asymmetric_bolding_is_flagged(self) -> None:
        posed = self.pose(options=[
            QuizOption(id="a", text="the **mean**"),
            QuizOption(id="b", text="the variance"),
        ])
        self.assertTrue(any("bolding" in w for w in posed.warnings))

    def test_symmetric_bolding_is_not_flagged(self) -> None:
        posed = self.pose(options=[
            QuizOption(id="a", text="the **mean**"),
            QuizOption(id="b", text="the **variance**"),
        ])
        self.assertEqual(posed.warnings, [])


class TestAnswerQuiz(Base):
    def test_pick_correct_is_computed_not_accepted(self) -> None:
        """The whole point: `answer_quiz` takes no `pick_correct` argument, so
        a sycophantic agent has no way to report a wrong pick as right."""
        import inspect

        self.assertNotIn("pick_correct",
                         inspect.signature(answer_quiz).parameters)

        posed = self.pose()
        wrong = answer_quiz(posed.question_id, pick="B",
                            reason="variance feels right",
                            reason_verdict="coherent")
        self.assertFalse(wrong.pick_correct)

    def test_the_outcomes_match_the_documented_table(self) -> None:
        cases = {
            ("A", "sound"): "solid",
            ("A", "coherent"): "lucky_guess",
            ("A", "incoherent"): "lucky_guess",
            ("B", "sound"): "slip",
            ("B", "coherent"): "misconception",
            ("B", "incoherent"): "gap",
        }
        for (pick, verdict), expected in cases.items():
            posed = self.pose()
            result = answer_quiz(posed.question_id, pick=pick,
                                 reason="a reason", reason_verdict=verdict)
            self.assertEqual(result.diagnosis, expected,
                             f"pick={pick} reason_verdict={verdict}")
            self.assertTrue(result.next_step)

    def test_a_sound_reason_with_a_wrong_pick_is_a_slip_not_a_gap(self) -> None:
        """The finding from the first live session. The learner described the
        correct option accurately and then picked a different one; a boolean
        verdict forced that into "gap", prescribing "back up a level" for a
        mis-click."""
        posed = self.pose()
        result = answer_quiz(
            posed.question_id, pick="B",
            reason="it maximizes the likelihood of the data we observed, "
                   "given a fixed theta",
            reason_verdict="sound",
        )
        self.assertFalse(result.pick_correct)
        self.assertEqual(result.diagnosis, "slip")
        self.assertIn("mismatch", result.next_step)
        self.assertNotIn("back up", result.next_step.lower().replace(
            "do not back up", ""))

    def test_an_unknown_verdict_is_refused(self) -> None:
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "reason_verdict must be"):
            answer_quiz(posed.question_id, pick="A", reason="r",
                        reason_verdict="maybe")

    def test_the_explanation_is_released_only_now(self) -> None:
        posed = self.pose()
        result = answer_quiz(posed.question_id, pick="A", reason="r",
                             reason_verdict="sound")
        self.assertIn("maximizes the normal likelihood", result.explanation)

    def test_a_question_cannot_be_answered_twice(self) -> None:
        """Re-answering would let a learner converge by elimination, which
        destroys the signal the question was posed to collect."""
        posed = self.pose()
        answer_quiz(posed.question_id, pick="B", reason="r", reason_verdict="incoherent")
        with self.assertRaisesRegex(ToolError, "already been answered"):
            answer_quiz(posed.question_id, pick="A", reason="r",
                        reason_verdict="sound")

    def test_unknown_question_id_says_what_is_known(self) -> None:
        posed = self.pose()
        with self.assertRaises(ToolError) as caught:
            answer_quiz("quiz-nope", pick="A", reason="r", reason_verdict="sound")
        self.assertIn(posed.question_id, str(caught.exception))

    def test_a_pick_outside_the_options_is_refused(self) -> None:
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "not one of"):
            answer_quiz(posed.question_id, pick="z", reason="r",
                        reason_verdict="sound")

    def test_a_blank_reason_is_refused(self) -> None:
        """A pick without a justification is the plain multiple choice this
        tool exists to avoid."""
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "reason is required"):
            answer_quiz(posed.question_id, pick="A", reason="  ",
                        reason_verdict="sound")


RUBRIC = [
    "states that the score has mean zero",
    "differentiates the log-likelihood twice",
    "identifies the negative expected Hessian",
]


class VaultBase(Base):
    """Explain and grading now touch the concept ledger, which lives under
    VAULT_ROOT. Point it somewhere disposable rather than at a real vault."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._real_root = server.VAULT_ROOT
        server.VAULT_ROOT = Path(self._tmp.name)

    def tearDown(self) -> None:
        server.VAULT_ROOT = self._real_root
        self._tmp.cleanup()


class TestExplain(VaultBase):
    def test_a_rubric_is_required(self) -> None:
        with self.assertRaisesRegex(ToolError, "rubric is required"):
            explain("Why is Fisher information the negative expected Hessian?", [], [])

    def test_duplicate_and_blank_items_are_refused(self) -> None:
        with self.assertRaisesRegex(ToolError, "duplicate rubric items"):
            explain("q", ["same", "same"], [])
        with self.assertRaisesRegex(ToolError, "must not be blank"):
            explain("q", ["real", "  "], [])

    def test_the_rubric_is_not_in_the_payload_but_its_hash_is(self) -> None:
        posed = explain("Why the negative expected Hessian?", RUBRIC, [])
        rendered = repr(posed)
        for item in RUBRIC:
            self.assertNotIn(item, rendered)
        self.assertEqual(posed.rubric_items, 3)
        self.assertEqual(len(posed.rubric_sha256), 64)

    def test_the_hash_is_reproducible_by_hand(self) -> None:
        """A learner who cannot verify the hash themselves is taking the
        pre-commitment on faith, which defeats it. One item per line, so
        `sha256sum` reproduces this."""
        posed = explain("q", RUBRIC, [])
        expected = hashlib.sha256("\n".join(RUBRIC).encode("utf-8")).hexdigest()
        self.assertEqual(posed.rubric_sha256, expected)


class TestGradeExplain(VaultBase):
    def pose(self):
        return explain("Why the negative expected Hessian?", RUBRIC, [])

    def test_a_complete_partition_grades(self) -> None:
        posed = self.pose()
        result = grade_explain(posed.question_id, answer="because curvature",
                               hit=RUBRIC[:2], missed=RUBRIC[2:])
        self.assertEqual(result.hit, RUBRIC[:2])
        self.assertEqual(result.missed, RUBRIC[2:])
        self.assertFalse(result.passed)
        self.assertEqual(result.rubric, RUBRIC)
        self.assertEqual(result.rubric_sha256, posed.rubric_sha256)

    def test_everything_hit_passes(self) -> None:
        posed = self.pose()
        result = grade_explain(posed.question_id, answer="a good answer",
                               hit=RUBRIC, missed=[])
        self.assertTrue(result.passed)
        self.assertIn("advance", result.next_step.lower())

    def test_an_invented_rubric_item_is_refused(self) -> None:
        """The check that makes the pre-commitment real: an agent looking at a
        weak answer cannot grade against a rubric it softened, because the
        softened items are not the committed ones."""
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "not in the committed rubric"):
            grade_explain(posed.question_id, answer="hand-wavy",
                          hit=["mentioned curvature, close enough"],
                          missed=[])

    def test_a_dropped_rubric_item_is_refused(self) -> None:
        """Silently omitting the item the answer missed would be the same
        softening by subtraction."""
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "neither hit nor missed"):
            grade_explain(posed.question_id, answer="partial",
                          hit=RUBRIC[:1], missed=[])

    def test_an_item_in_both_lists_is_refused(self) -> None:
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "both hit and missed"):
            grade_explain(posed.question_id, answer="a",
                          hit=RUBRIC, missed=RUBRIC[:1])

    def test_grading_twice_is_refused(self) -> None:
        posed = self.pose()
        grade_explain(posed.question_id, answer="a", hit=RUBRIC, missed=[])
        with self.assertRaisesRegex(ToolError, "already been graded"):
            grade_explain(posed.question_id, answer="a", hit=RUBRIC, missed=[])

    def test_a_blank_answer_is_refused(self) -> None:
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "answer is required"):
            grade_explain(posed.question_id, answer="", hit=RUBRIC, missed=[])


class TestVocabularyGate(VaultBase):
    """The tiered rule, end to end through the tools rather than the ledger.

    The point of the gate is that it cannot be talked past: an agreeable agent
    can waive a rule written in a prompt, and cannot waive this one.
    """

    def pose(self):
        return explain("Why the negative expected Hessian?", RUBRIC,
                       ["monotonicity"])

    def test_posing_reports_where_a_concept_stands(self) -> None:
        posed = self.pose()
        self.assertEqual(len(posed.vocabulary), 1)
        entry = posed.vocabulary[0]
        self.assertEqual(entry["concept"], "monotonicity")
        self.assertEqual(entry["tier"], "lenient")
        self.assertFalse(entry["naming_required"])
        self.assertIn("Credit a correct description", entry["advice"])

    def test_unnamed_credits_accumulate_and_then_gate(self) -> None:
        tiers = []
        for _ in range(ledger.GATE_AT):
            posed = self.pose()
            tiers.append(posed.vocabulary[0]["tier"])
            grade_explain(posed.question_id, answer="a description",
                          hit=RUBRIC, missed=[], unnamed=["monotonicity"])
        self.assertEqual(tiers[0], "lenient")
        self.assertEqual(tiers[-1], "advisory")

        gated = self.pose()
        self.assertEqual(gated.vocabulary[0]["tier"], "gated")
        self.assertTrue(gated.vocabulary[0]["naming_required"])
        with self.assertRaisesRegex(ToolError, "cannot be waived"):
            grade_explain(gated.question_id, answer="a description",
                          hit=RUBRIC, missed=[], unnamed=["monotonicity"])

    def test_a_refusal_leaves_the_ledger_untouched(self) -> None:
        """So the call can simply be retried. Checked before anything is
        recorded."""
        for _ in range(ledger.GATE_AT):
            posed = self.pose()
            grade_explain(posed.question_id, answer="d", hit=RUBRIC, missed=[],
                          unnamed=["monotonicity"])
        before = ledger.load("monotonicity", server.VAULT_ROOT)
        blocked = self.pose()
        with self.assertRaises(ToolError):
            grade_explain(blocked.question_id, answer="d", hit=RUBRIC,
                          missed=[], unnamed=["monotonicity"])
        after = ledger.load("monotonicity", server.VAULT_ROOT)
        self.assertEqual(after.unnamed_streak, before.unnamed_streak)
        self.assertEqual(after.credited_unnamed, before.credited_unnamed)

    def test_naming_it_resets_the_streak(self) -> None:
        """The rule is about failing to internalize a term continually."""
        for _ in range(ledger.GATE_AT):
            posed = self.pose()
            grade_explain(posed.question_id, answer="d", hit=RUBRIC, missed=[],
                          unnamed=["monotonicity"])
        posed = self.pose()
        self.assertTrue(posed.vocabulary[0]["naming_required"])
        result = grade_explain(posed.question_id, answer="it is monotonic",
                               hit=RUBRIC, missed=[], named=["monotonicity"])
        self.assertEqual(result.vocabulary[0]["tier"], "lenient")
        self.assertEqual(
            ledger.load("monotonicity", server.VAULT_ROOT).unnamed_streak, 0)

    def test_a_human_can_lift_the_gate_and_the_tool_honours_it(self) -> None:
        for _ in range(ledger.GATE_AT):
            posed = self.pose()
            grade_explain(posed.question_id, answer="d", hit=RUBRIC, missed=[],
                          unnamed=["monotonicity"])
        path = ledger.concept_path("monotonicity", server.VAULT_ROOT)
        path.write_text(path.read_text().replace("gate: auto", "gate: off"))

        posed = self.pose()
        self.assertFalse(posed.vocabulary[0]["naming_required"])
        grade_explain(posed.question_id, answer="d", hit=RUBRIC, missed=[],
                      unnamed=["monotonicity"])

    def test_an_undeclared_concept_is_refused(self) -> None:
        """Grading can only speak about concepts the question committed to."""
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "not declared"):
            grade_explain(posed.question_id, answer="d", hit=RUBRIC, missed=[],
                          named=["ergodicity"])

    def test_a_concept_cannot_be_both_named_and_unnamed(self) -> None:
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "both named and unnamed"):
            grade_explain(posed.question_id, answer="d", hit=RUBRIC, missed=[],
                          named=["monotonicity"], unnamed=["monotonicity"])


class TestSurface(unittest.TestCase):
    def test_check_sh_still_sees_all_seven_documented_names(self) -> None:
        """`scripts/check.sh` reports the surface by `hasattr`, and the five
        unimplemented tools stay as module-level functions partly for that."""
        for name in ("quiz", "explain", "derive", "ask",
                     "submit_artifact", "record_grade", "md_log"):
            self.assertTrue(hasattr(server, name), name)

    def test_only_the_implemented_tools_are_registered(self) -> None:
        """A stub in `tools/list` reads to the model as a capability."""
        self.assertEqual(server.IMPLEMENTED,
                         ("quiz", "answer_quiz", "explain", "grade_explain"))
        for name in server.PLACEHOLDERS:
            with self.assertRaises(NotImplementedError):
                getattr(server, name)(*_placeholder_args(name))


def _placeholder_args(name: str):
    return {
        "derive": ("task", ["step"], "[[c]]"),
        "ask": ("q",),
        "submit_artifact": ("notes/x.md",),
        "record_grade": ("notes/x.md", ["r"], ["r"], [], "c"),
        "md_log": (server.LogSession(path=server.VAULT_ROOT / "log.md"), "x"),
    }[name]


if __name__ == "__main__":
    unittest.main()


class TestOptionsMayNotExplainThemselves(unittest.TestCase):
    """Verbatim from the first live probe, 2026-09-12.

    The learner's report: "a-d also give me a lot of context, and it wants a
    one-line reason, it seems the obvious answer is to just reiterate what the
    answer is." Exactly right, and it makes the two-call design pointless --
    the justification measures nothing if the option already contains it.
    """

    # The option that got through. `so` was matched only as "so that", and
    # `means` only as "which means", so no keyword fired; at 1.38x the mean
    # distractor length it also slipped under the 1.5x check.
    LEAKED = ("The curvature (second derivative) of the LL near the MLE — a "
              "sharper peak means the LL drops fast as θ moves away from the "
              "MLE, so the data rule out nearby values strongly.")
    # The agent's own regeneration once the length check did fire. This one
    # must keep passing: it is the control that says the rule is not simply
    # "refuse anything detailed".
    CLEAN = ("The second-derivative matrix of NLL, which is the same thing as "
             "the observed Fisher information matrix.")

    def pose(self, correct_text: str, **kw):
        options = [
            QuizOption(id="A", text=correct_text),
            QuizOption(id="B", text="The maximized LL value itself."),
            QuizOption(id="C", text="The location of the MLE versus the truth."),
            QuizOption(id="D", text="The width of the range where LL is finite."),
        ]
        return quiz(prompt="Which one?", options=options,
                    correct_option_id="A",
                    explanation="Curvature carries the information.",
                    **kw)

    def test_the_option_that_got_through_is_now_refused(self) -> None:
        with self.assertRaises(ToolError) as caught:
            self.pose(self.LEAKED)
        self.assertIn("restate", str(caught.exception))

    def test_a_bare_claim_with_a_relative_clause_still_passes(self) -> None:
        """The control. "which is the same thing as" describes the claim; it
        does not argue for it."""
        self.assertTrue(self.pose(self.CLEAN).question_id)

    def test_a_dash_followed_by_an_argument_is_refused(self) -> None:
        with self.assertRaises(ToolError):
            self.pose("The curvature of the LL near the MLE — the data rule "
                      "out nearby values strongly.")

    def test_a_short_aside_after_a_dash_is_not_an_argument(self) -> None:
        self.assertTrue(self.pose("The curvature — the second derivative.")
                        .question_id)

    def test_a_leaking_distractor_is_refused_too(self) -> None:
        """Not only the correct option. A distractor that argues for itself
        is just as readable a tell."""
        with self.assertRaises(ToolError) as caught:
            quiz(
                prompt="Which one?",
                options=[
                    QuizOption(id="A", text="g''(θ₀) = -f''(θ₀), always."),
                    QuizOption(id="B", text="g''(θ₀) = f''(θ₀), always, since "
                                            "negating a function just reflects "
                                            "its graph."),
                ],
                correct_option_id="A",
                explanation="Differentiation is linear.",
            )
        self.assertIn("'B'", str(caught.exception))

    def test_being_the_longest_is_flagged_below_the_old_threshold(self) -> None:
        """1.38x was under the 1.5x bar and still the giveaway."""
        options = [
            server.QuizOption(id="A", text="x" * 172),
            server.QuizOption(id="B", text="x" * 144),
            server.QuizOption(id="C", text="x" * 152),
            server.QuizOption(id="D", text="x" * 79),
        ]
        self.assertTrue(any("longest" in w
                            for w in server._lint_options(options, "A")))

    def test_a_short_correct_option_is_not_flagged(self) -> None:
        options = [
            server.QuizOption(id="A", text="x" * 40),
            server.QuizOption(id="B", text="x" * 144),
            server.QuizOption(id="C", text="x" * 152),
        ]
        self.assertEqual(server._lint_options(options, "A"), [])


class TestShuffle(unittest.TestCase):
    """Borrowed from `amosblomqvist/learn`, which shuffles before display so
    that grading matches the order the learner saw.

    Two habits it defeats, neither visible in the authored order: where a model
    tends to put the right answer, and where a reader tends to look.
    """

    FOUR = [QuizOption(id=str(i), text=f"claim {i}") for i in range(1, 5)]

    def pose(self, **over):
        kwargs = dict(prompt="Which one?", options=self.FOUR,
                      correct_option_id="1", explanation="Because.")
        kwargs.update(over)
        return quiz(**kwargs)

    def test_options_are_relabelled_by_position(self) -> None:
        """Reordering while keeping the authored ids would show the learner
        "C" first, which reads as a bug."""
        posed = self.pose()
        # Five: the four authored, plus the appended "I don't know".
        self.assertEqual([o.id for o in posed.options],
                         ["A", "B", "C", "D", "E"])

    def test_the_texts_are_preserved_exactly(self) -> None:
        posed = self.pose()
        self.assertEqual(sorted(o.text for o in posed.options),
                         ["I don't know.", "claim 1", "claim 2",
                          "claim 3", "claim 4"])

    def test_the_key_follows_the_option_it_belongs_to(self) -> None:
        """The whole thing is wrong if the answer stays at a fixed label."""
        for _ in range(40):
            posed = self.pose()
            shown = {o.id: o.text for o in posed.options}
            key = server._QUIZZES[posed.question_id].correct_option_id
            self.assertEqual(shown[key], "claim 1")

    def test_the_answer_does_not_sit_at_one_label(self) -> None:
        """40 draws over 4 positions landing on one label every time would be
        1 in 4^39. If this ever fails, shuffling silently stopped."""
        seen = {server._QUIZZES[self.pose().question_id].correct_option_id
                for _ in range(40)}
        self.assertGreater(len(seen), 1)

    def test_grading_uses_the_displayed_label(self) -> None:
        posed = self.pose()
        key = server._QUIZZES[posed.question_id].correct_option_id
        result = answer_quiz(posed.question_id, pick=key, reason="r",
                             reason_verdict="sound")
        self.assertTrue(result.pick_correct)
        self.assertEqual(result.diagnosis, "solid")

    def test_an_authored_id_is_no_longer_a_valid_pick(self) -> None:
        """The authored ids are gone from the learner's view, so accepting one
        would mean grading something they were never shown."""
        posed = self.pose()
        with self.assertRaisesRegex(ToolError, "not one of"):
            answer_quiz(posed.question_id, pick="1", reason="r",
                        reason_verdict="sound")

    def test_shuffle_false_keeps_the_authored_order(self) -> None:
        """For questions where the order carries meaning — steps in a
        sequence, magnitudes to rank."""
        posed = self.pose(shuffle=False)
        self.assertEqual([o.text for o in posed.options],
                         ["claim 1", "claim 2", "claim 3", "claim 4",
                          server.DONT_KNOW])
        self.assertEqual(server._QUIZZES[posed.question_id].correct_option_id,
                         "A")

    def test_the_mapping_back_to_authored_ids_is_kept(self) -> None:
        """So the explanation, which may name an authored id, stays readable."""
        posed = self.pose()
        authored = server._QUIZZES[posed.question_id].authored
        self.assertEqual(sorted(authored), ["A", "B", "C", "D"])
        self.assertEqual(sorted(authored.values()), ["1", "2", "3", "4"])


class TestIDontKnow(unittest.TestCase):
    """Five of ten probes in the 2026-09-13 session were answered "I don't
    remember", and not one produced a grading call — there was nowhere to put
    that answer, so eight posed questions left no record of being asked.

    Finding the floor is what probing is *for*, so the most likely answer
    during a probe was the one the tool could not represent.
    """

    OPTIONS = [QuizOption(id=str(i), text=f"claim {i}") for i in range(1, 4)]

    def pose(self, **over):
        kwargs = dict(prompt="Which one?", options=self.OPTIONS,
                      correct_option_id="1", explanation="Because.",
                      shuffle=False)
        kwargs.update(over)
        return quiz(**kwargs)

    def test_every_quiz_offers_it_without_being_asked(self) -> None:
        """An affordance that depends on being remembered goes missing in the
        session where it matters most."""
        self.assertEqual(self.pose().options[-1].text, server.DONT_KNOW)

    def test_it_is_always_last_even_when_shuffled(self) -> None:
        for _ in range(20):
            self.assertEqual(self.pose(shuffle=True).options[-1].text,
                             server.DONT_KNOW)

    def test_it_is_never_the_correct_answer(self) -> None:
        posed = self.pose()
        record = server._QUIZZES[posed.question_id]
        self.assertNotEqual(record.correct_option_id, record.dont_know_id)

    def test_declining_is_not_graded_as_wrong(self) -> None:
        """Scoring it wrong would send the lesson hunting for a misconception
        that is not there."""
        posed = self.pose()
        result = answer_quiz(
            posed.question_id, pick=posed.options[-1].id,
            reason="I don't remember what eigenvalues mean",
            reason_verdict="incoherent")
        self.assertFalse(result.pick_correct)
        self.assertEqual(result.diagnosis, "floor")
        self.assertNotIn("misconception", result.next_step)

    def test_fragments_are_distinguished_from_a_floor(self) -> None:
        """"I remember only that eigenvectors are the fundamental of the
        system" is not the same answer as "I don't remember, really", and the
        next move is not the same either."""
        posed = self.pose()
        result = answer_quiz(posed.question_id, pick=posed.options[-1].id,
                             reason="something about a fundamental direction",
                             reason_verdict="coherent")
        self.assertEqual(result.diagnosis, "partial")

    def test_knowing_it_but_not_committing_is_its_own_outcome(self) -> None:
        posed = self.pose()
        result = answer_quiz(posed.question_id, pick=posed.options[-1].id,
                             reason="repeated application only rescales it",
                             reason_verdict="sound")
        self.assertEqual(result.diagnosis, "unsure")
        self.assertIn("confidence", result.next_step)

    def test_a_reason_is_still_required(self) -> None:
        """What they *do* half-remember is the useful part of a don't-know."""
        posed = self.pose()
        with self.assertRaises(ToolError):
            answer_quiz(posed.question_id, pick=posed.options[-1].id,
                        reason="   ", reason_verdict="incoherent")

    def test_the_three_unknown_rows_are_all_reachable(self) -> None:
        for verdict, expected in (("sound", "unsure"),
                                  ("coherent", "partial"),
                                  ("incoherent", "floor")):
            with self.subTest(verdict=verdict):
                posed = self.pose()
                self.assertEqual(
                    answer_quiz(posed.question_id, pick=posed.options[-1].id,
                                reason="r", reason_verdict=verdict).diagnosis,
                    expected)


class TestOptionsAreNamedNotLettered(unittest.TestCase):
    """An explanation may not refer to an option by letter.

    It is committed at posing time, before `_shuffle` assigns A-E, so a letter
    in it names the agent's own authoring order rather than the learner's.
    This is not carelessness to be coached out: at the moment of writing, the
    labels the reader will see do not exist.

    Measured 2026-09-15. Authored opt1 "identically zero" (correct), opt2
    "linear combination", opt3 "alphabetical", opt4 "no intercept"; shown as
    A alphabetical, B no intercept, C identically zero, D linear combination.
    The explanation then read "C is wrong: there is no alphabetical-drop
    rule" -- about the option the learner had just correctly picked."""

    def options(self):
        return [server.QuizOption(id="opt1", text="Identically zero."),
                server.QuizOption(id="opt2", text="A linear combination."),
                server.QuizOption(id="opt3", text="Sorted alphabetically."),
                server.QuizOption(id="opt4", text="No intercept.")]

    def pose(self, explanation: str):
        return server.quiz(prompt="Why is it NA?", options=self.options(),
                           correct_option_id="opt1", explanation=explanation)

    def test_the_real_explanation_is_refused(self) -> None:
        with self.assertRaises(ToolError) as caught:
            self.pose("B is wrong because the columns are indicators. "
                      "C is wrong: there is no alphabetical-drop rule.")
        self.assertIn("by letter", str(caught.exception))

    def test_the_parenthesised_form_is_refused(self) -> None:
        """From the first live probe: "Option (a) swaps pop3 with ..."."""
        with self.assertRaises(ToolError) as caught:
            self.pose("Option (a) swaps the two terms, and option (c) "
                      "confuses a difference with an absolute value.")
        self.assertIn("by letter", str(caught.exception))

    def test_an_authored_id_is_refused_when_distinctive(self) -> None:
        with self.assertRaises(ToolError):
            self.pose("opt1 is right because the column is zero everywhere.")

    def test_naming_the_claim_passes(self) -> None:
        """The form actually wanted, and the one that reads better: the reader
        does not have to hold a letter-to-claim mapping in their head."""
        posed = self.pose(
            "The 'identically zero' option is right: no row has that cell. "
            "The 'linear combination' claim would hold in the effects "
            "parameterization, not this one.")
        self.assertTrue(posed.question_id)

    def test_articles_are_not_option_references(self) -> None:
        """The trap in any bare-letter rule. These must all survive."""
        posed = self.pose(
            "A vector of ones codes the intercept. A row of the design matrix "
            "is one observation. A design matrix column is an indicator, and "
            "the answer is a linear combination, which is why lm() reports NA.")
        self.assertTrue(posed.question_id)

    def test_prose_about_rows_and_values_survives(self) -> None:
        posed = self.pose(
            "On row 5: reg2=1, hab2=1, hab3=0, so reg2:hab2=1. The claim that "
            "both are identically zero is wrong, since reg2:hab2 is 1 there.")
        self.assertTrue(posed.question_id)
