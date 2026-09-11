"""Does the ledger keep the counters without eating the note around them?

`curriculum.py` avoids this whole class of problem by never modifying a file.
The ledger cannot: counters have to go up, in a note that also holds the
learner's prose, their own front matter, and the one field that is theirs
alone — `gate: off`. So the tests here are mostly about what `save` leaves
behind.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vault_tools import ledger
from vault_tools.ledger import Concept, concept_path, load, record_named, record_unnamed, save


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestTiers(Base):
    def test_the_documented_progression(self) -> None:
        expected = (["lenient"] * ledger.LENIENT_UNTIL
                    + ["advisory"] * (ledger.GATE_AT - ledger.LENIENT_UNTIL))
        seen = []
        for _ in range(ledger.GATE_AT):
            seen.append(load("x", self.vault).tier)
            record_unnamed("x", self.vault)
        self.assertEqual(seen, expected)
        self.assertEqual(load("x", self.vault).tier, "gated")

    def test_naming_resets_the_streak_but_keeps_the_history(self) -> None:
        for _ in range(ledger.GATE_AT):
            record_unnamed("x", self.vault)
        concept = record_named("x", self.vault)
        self.assertEqual(concept.unnamed_streak, 0)
        self.assertEqual(concept.credited_unnamed, ledger.GATE_AT)
        self.assertEqual(concept.named, 1)
        self.assertEqual(concept.tier, "lenient")

    def test_gate_off_is_honoured(self) -> None:
        for _ in range(ledger.GATE_AT + 2):
            record_unnamed("x", self.vault)
        self.assertTrue(load("x", self.vault).naming_required)
        path = concept_path("x", self.vault)
        path.write_text(path.read_text().replace("gate: auto", "gate: off"))
        self.assertFalse(load("x", self.vault).naming_required)

    def test_gated_reports_only_the_gated_ones(self) -> None:
        for _ in range(ledger.GATE_AT):
            record_unnamed("blocked", self.vault)
        record_unnamed("fine", self.vault)
        self.assertEqual(ledger.gated(["blocked", "fine"], self.vault),
                         ["blocked"])


class TestPersistence(Base):
    def test_a_missing_note_reads_as_a_fresh_concept(self) -> None:
        concept = load("never seen", self.vault)
        self.assertEqual(concept.unnamed_streak, 0)
        self.assertEqual(concept.tier, "lenient")

    def test_counters_survive_a_round_trip(self) -> None:
        record_unnamed("x", self.vault)
        record_unnamed("x", self.vault)
        record_named("x", self.vault)
        again = load("x", self.vault)
        self.assertEqual(again.credited_unnamed, 2)
        self.assertEqual(again.named, 1)
        self.assertEqual(again.unnamed_streak, 0)

    def test_saving_preserves_the_learners_prose(self) -> None:
        record_unnamed("x", self.vault)
        path = concept_path("x", self.vault)
        path.write_text(path.read_text() + "\nMy own note about this.\n")
        record_unnamed("x", self.vault)
        self.assertIn("My own note about this.", path.read_text())

    def test_saving_preserves_unknown_front_matter(self) -> None:
        """A note may carry fields this module knows nothing about — tags,
        wikilinks to curriculum topics, whatever Obsidian plugins want."""
        record_unnamed("x", self.vault)
        path = concept_path("x", self.vault)
        path.write_text(path.read_text().replace(
            "gate: auto", 'gate: auto\ntags: [vocabulary]\nmine: "keep me"'))
        record_unnamed("x", self.vault)
        text = path.read_text()
        self.assertIn("tags: [vocabulary]", text)
        self.assertIn('mine: "keep me"', text)
        self.assertIn("unnamed_streak: 2", text)

    def test_a_malformed_note_costs_a_tightened_bar_not_a_lesson(self) -> None:
        """An unreadable ledger entry must not raise into a grading call. It
        reads as a fresh concept, which is lenient — the failure direction
        that loses a record rather than a session."""
        path = concept_path("x", self.vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is not front matter at all\nunnamed_streak: abc\n")
        concept = load("x", self.vault)
        self.assertEqual(concept.unnamed_streak, 0)

    def test_counters_are_added_to_a_note_that_lacks_them(self) -> None:
        path = concept_path("x", self.vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\ntype: concept\nconcept: "x"\n---\n\nHand-made.\n')
        record_unnamed("x", self.vault)
        text = path.read_text()
        self.assertIn("unnamed_streak: 1", text)
        self.assertIn("Hand-made.", text)

    def test_dates_are_stamped(self) -> None:
        concept = record_unnamed("x", self.vault)
        self.assertTrue(concept.first_seen)
        self.assertEqual(concept.first_seen, concept.last_seen)


class TestNaming(Base):
    def test_forbidden_characters_are_sanitized_with_an_alias(self) -> None:
        record_unnamed("Bayes' rule: the short form", self.vault)
        path = concept_path("Bayes' rule: the short form", self.vault)
        self.assertNotIn(":", path.name)
        self.assertIn("aliases:", path.read_text())

    def test_a_sanitized_concept_still_round_trips(self) -> None:
        name = "P(x|θ) vs P(θ|x)"
        record_unnamed(name, self.vault)
        record_unnamed(name, self.vault)
        self.assertEqual(load(name, self.vault).unnamed_streak, 2)


if __name__ == "__main__":
    unittest.main()
