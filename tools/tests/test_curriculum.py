"""Does the canon stay the canon, and does seeding ever lose a judgment?

The load tests are about refusing a malformed canon loudly, because a bad
canon is inherited by every vault seeded from it and the errors it introduces
are the silent kind this layer exists to prevent.

The seed tests are about one property: **seeding creates and never modifies.**
A topic note carries canon fields and judgment fields in the same file, so an
updating seeder could overwrite a relevance decision. It must not be able to.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vault_tools import curriculum
from vault_tools.curriculum import CanonError, audit, load, load_all, seed

REPO_CANON = Path("/workspace/curriculum")

MINIMAL = """
[course]
id = "test-101"
number = "TEST.101"
title = "A Course"
url = "https://example.invalid/"
verified = "2026-09-11"

[[topic]]
ref = "U1-01"
unit = "Unit I"
name = "First Thing"

[[topic]]
ref = "U1-02"
unit = "Unit I"
name = "Second: Thing"
"""


def write(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    handle.write(text)
    handle.close()
    return Path(handle.name)


class TestLoad(unittest.TestCase):
    def test_a_minimal_canon_loads(self) -> None:
        canon = load(write(MINIMAL))
        self.assertEqual(canon.course_id, "test-101")
        self.assertEqual(len(canon.topics), 2)
        self.assertEqual(canon.units, ("Unit I",))

    def test_missing_course_fields_are_refused(self) -> None:
        with self.assertRaisesRegex(CanonError, "missing"):
            load(write(MINIMAL.replace('url = "https://example.invalid/"', "")))

    def test_a_canon_with_no_topics_is_refused(self) -> None:
        head = MINIMAL.split("[[topic]]")[0]
        with self.assertRaisesRegex(CanonError, "no \\[\\[topic\\]\\]"):
            load(write(head))

    def test_duplicate_refs_are_refused(self) -> None:
        with self.assertRaisesRegex(CanonError, "duplicate topic refs"):
            load(write(MINIMAL.replace('ref = "U1-02"', 'ref = "U1-01"')))

    def test_titles_that_collide_after_sanitizing_are_refused(self) -> None:
        """Two titles differing only in forbidden punctuation would seed into
        one note and silently lose one of them."""
        # "A/B" and "A-B" both sanitize to "A-B" -- a slash against a hyphen
        # is exactly the pair that collides, which is why the first version of
        # this test ("First Thing" vs "First/Thing") did not.
        clash = MINIMAL.replace('name = "First Thing"', 'name = "A/B"')
        clash = clash.replace('name = "Second: Thing"', 'name = "A-B"')
        with self.assertRaisesRegex(CanonError, "collide on filename"):
            load(write(clash))

    def test_malformed_toml_names_the_file(self) -> None:
        path = write("[course\nid = 1")
        with self.assertRaisesRegex(CanonError, path.name):
            load(path)


class TestFilenames(unittest.TestCase):
    def test_forbidden_characters_are_replaced(self) -> None:
        """Obsidian forbids some of these outright and others break on iOS or
        Windows sync, which matters because the vault is meant to reach a
        phone."""
        canon = load(write(MINIMAL))
        second = canon.topics[1]
        self.assertEqual(second.name, "Second: Thing")
        self.assertEqual(second.filename, "Second- Thing.md")

    def test_the_exact_title_survives_as_an_alias(self) -> None:
        """So `[[Second: Thing]]` still resolves despite the filename."""
        canon = load(write(MINIMAL))
        body = curriculum.note_body(canon, canon.topics[1])
        self.assertIn('aliases: ["Second: Thing"]', body)
        self.assertIn('topic: "Second: Thing"', body)

    def test_no_alias_when_the_title_needed_no_change(self) -> None:
        canon = load(write(MINIMAL))
        self.assertNotIn("aliases:", curriculum.note_body(canon, canon.topics[0]))


class TestSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.canon = load(write(MINIMAL))
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_seeding_creates_one_note_per_topic(self) -> None:
        report = seed(self.canon, self.vault)
        self.assertEqual(len(report.created), 2)
        directory = self.vault / "curriculum" / "test-101"
        self.assertEqual(
            sorted(p.name for p in directory.iterdir()),
            ["First Thing.md", "Second- Thing.md"],
        )

    def test_topics_start_unjudged(self) -> None:
        """`relevance: unset` is the queryable hole, and it is the default so
        the holes exist as data on day one."""
        seed(self.canon, self.vault)
        text = (self.vault / "curriculum" / "test-101" / "First Thing.md").read_text()
        self.assertIn("relevance: unset", text)

    def test_re_seeding_changes_nothing(self) -> None:
        seed(self.canon, self.vault)
        path = self.vault / "curriculum" / "test-101" / "First Thing.md"
        before = path.read_bytes()
        report = seed(self.canon, self.vault)
        self.assertEqual(report.created, [])
        self.assertEqual(len(report.existing), 2)
        self.assertEqual(path.read_bytes(), before)

    def test_seeding_cannot_overwrite_a_judgment(self) -> None:
        """The property this module is built around. A note holds canon and
        judgment in one file, so an updating seeder could destroy the second.
        Even a changed canon must not."""
        seed(self.canon, self.vault)
        path = self.vault / "curriculum" / "test-101" / "First Thing.md"
        path.write_text(
            path.read_text().replace("relevance: unset", "relevance: skip")
            + "\nMy own note, in my own words.\n"
        )
        judged = path.read_text()

        moved = load(write(MINIMAL.replace('unit = "Unit I"', 'unit = "Unit ONE"')))
        seed(moved, self.vault)

        self.assertEqual(path.read_text(), judged)
        self.assertIn("relevance: skip", path.read_text())
        self.assertIn("My own note", path.read_text())


class TestAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.canon = load(write(MINIMAL))
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        seed(self.canon, self.vault)
        self.directory = self.vault / "curriculum" / "test-101"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_freshly_seeded_vault_is_all_unjudged(self) -> None:
        report = audit(self.canon, self.vault)
        self.assertEqual(report.holes, [])
        self.assertEqual(report.orphans, [])
        self.assertEqual(len(report.unjudged), 2)

    def test_a_missing_note_is_a_hole(self) -> None:
        """The condition this layer exists for: a canonical topic with no note
        is one nobody can even record a decision about."""
        (self.directory / "First Thing.md").unlink()
        self.assertEqual(audit(self.canon, self.vault).holes, ["U1-01"])

    def test_an_unlisted_note_is_an_orphan(self) -> None:
        (self.directory / "Invented.md").write_text("stray")
        self.assertEqual(audit(self.canon, self.vault).orphans, ["Invented.md"])

    def test_judgments_are_counted_by_verdict(self) -> None:
        path = self.directory / "First Thing.md"
        path.write_text(path.read_text().replace("relevance: unset",
                                                 "relevance: cover"))
        report = audit(self.canon, self.vault)
        self.assertEqual(report.judged["cover"], ["U1-01"])
        self.assertEqual(len(report.unjudged), 1)

    def test_an_unseeded_vault_is_all_holes_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            report = audit(self.canon, empty)
            self.assertEqual(len(report.holes), 2)


class TestTheRealCanon(unittest.TestCase):
    """The checked-in canon has to load, because everything downstream of it
    assumes it does."""

    def test_the_repo_canon_loads_and_is_cited(self) -> None:
        if not REPO_CANON.is_dir():
            self.skipTest(f"{REPO_CANON} not mounted")
        for canon in load_all(REPO_CANON):
            self.assertTrue(canon.url.startswith("https://"), canon.course_id)
            self.assertTrue(canon.verified, canon.course_id)
            self.assertTrue(canon.topics, canon.course_id)

    def test_18_06_has_its_three_units(self) -> None:
        path = REPO_CANON / "mit-18.06sc.toml"
        if not path.exists():
            self.skipTest("18.06SC canon not mounted")
        canon = load(path)
        self.assertEqual(len(canon.units), 3)
        self.assertEqual(len(canon.topics), 32)
        # Exam reviews are excluded on purpose, and the canon says so.
        self.assertIn("exam", canon.excluded.lower())
        self.assertFalse([t for t in canon.topics if "Exam" in t.name])


if __name__ == "__main__":
    unittest.main()
