"""Does the canon stay the canon, and does seeding ever lose a judgment?

The load tests are about refusing a malformed canon loudly, because a bad
canon is inherited by every vault seeded from it and the errors it introduces
are the silent kind this layer exists to prevent.

The seed tests are about one property: **seeding creates and never modifies.**
A topic note carries canon fields and judgment fields in the same file, so an
updating seeder could overwrite a relevance decision. It must not be able to.
"""

from __future__ import annotations

import re
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


class TestLoadAll(unittest.TestCase):
    @staticmethod
    def _two(second: str) -> str:
        """A second canon, distinct identity, same topic titles."""
        return (second.replace('id = "test-101"', 'id = "test-202"')
                      .replace('number = "TEST.101"', 'number = "TEST.202"'))

    def test_the_same_title_in_two_canons_is_scoped_not_refused(self) -> None:
        """Obsidian resolves wikilinks by filename across the whole vault, so
        two notes named alike make the link AMBIGUOUS rather than broken --
        it silently resolves to whichever Obsidian picks.

        This was a load error until a textbook needed importing. A course's
        text shares most of its topic titles with the course, and refusing
        that would make the import impossible, so the shared ones get scoped
        filenames instead."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(self._two(MINIMAL))
            first, second = load_all(directory)
            self.assertEqual(first.topics[0].filename,
                             "First Thing (TEST.101).md")
            self.assertEqual(second.topics[0].filename,
                             "First Thing (TEST.202).md")

    def test_a_scoped_note_gets_no_alias(self) -> None:
        """An alias restoring the bare title would re-create through aliases
        the exact ambiguity the suffix removed."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(self._two(MINIMAL))
            canon = load_all(directory)[0]
            scoped = canon.topics[1]          # "Second: Thing", sanitized too
            self.assertTrue(scoped.suffix)
            self.assertNotIn("aliases:", curriculum.note_body(canon, scoped))

    def test_overlaps_are_reported_not_just_handled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(self._two(MINIMAL))
            shared = curriculum.overlaps(load_all(directory))
            self.assertEqual(shared["First Thing"], ["TEST.101", "TEST.202"])

    def test_canons_sharing_a_tag_and_a_title_are_refused(self) -> None:
        """The suffix is only a fix if the tags differ."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(
                MINIMAL.replace('id = "test-101"', 'id = "test-202"'))
            with self.assertRaisesRegex(CanonError, "share a tag"):
                load_all(directory)

    def test_nothing_is_scoped_when_nothing_collides(self) -> None:
        """The suffix must not appear just because two canons are loaded --
        it would rename every existing note in the vault."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(
                self._two(MINIMAL)
                .replace('name = "First Thing"', 'name = "Other Thing"')
                .replace('name = "Second: Thing"', 'name = "Another Thing"'))
            for canon in load_all(directory):
                for topic in canon.topics:
                    self.assertEqual(topic.suffix, "")

    def test_distinct_courses_load_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(
                MINIMAL.replace('id = "test-101"', 'id = "test-202"')
                       .replace('number = "TEST.101"', 'number = "TEST.202"')
                       .replace('name = "First Thing"', 'name = "Other Thing"')
                       .replace('name = "Second: Thing"', 'name = "Another Thing"')
            )
            self.assertEqual(len(load_all(directory)), 2)


TEXT = """
[source]
kind = "text"
id = "a-book"
title = "A Book About Things"
author = "Someone"
edition = "2nd ed."
short = "BOOK"
verified = "2026-09-11"
excluded = "the exercises"

[[topic]]
ref = "1.3"
unit = "Part I: Beginnings"
name = "The First Chapter"
locator = "pp. 4-31"

[[topic]]
ref = "5.4"
unit = "Part II: Later On"
name = "A Chapter With No Pages Given"
"""


class TestSourceKinds(unittest.TestCase):
    """A canon is not always a course. What citing one requires differs by
    kind, and asking a book for a course number would mean inventing one --
    the exact failure this layer exists to prevent."""

    def test_a_text_loads_without_a_url_or_a_number(self) -> None:
        canon = load(write(TEXT))
        self.assertEqual(canon.kind, "text")
        self.assertEqual(canon.url, "")
        self.assertEqual(canon.number, "")
        self.assertEqual(canon.tag, "BOOK")
        self.assertEqual(canon.label, "Someone, A Book About Things (2nd ed.)")

    def test_a_text_without_a_url_still_cites(self) -> None:
        self.assertEqual(load(write(TEXT)).citation,
                         "Someone, A Book About Things (2nd ed.)")

    def test_a_course_still_needs_its_url(self) -> None:
        with self.assertRaisesRegex(CanonError, "url"):
            load(write(MINIMAL.replace('url = "https://example.invalid/"', "")))

    def test_a_text_needs_its_edition(self) -> None:
        """The per-kind half of the citation. A book identified only by title
        is a book nobody can check a topic against."""
        with self.assertRaisesRegex(CanonError, "edition"):
            load(write(TEXT.replace('edition = "2nd ed."', "")))

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaisesRegex(CanonError, "not one of"):
            load(write(TEXT.replace('kind = "text"', 'kind = "podcast"')))

    def test_course_is_still_accepted_as_the_table_name(self) -> None:
        """The four checked-in canons use it."""
        self.assertEqual(load(write(MINIMAL)).kind, "course")

    def test_both_table_names_at_once_is_refused(self) -> None:
        both = TEXT + MINIMAL.split("[[topic]]")[0]
        with self.assertRaisesRegex(CanonError, "both"):
            load(write(both))

    def test_a_paper_needs_a_link(self) -> None:
        paper = TEXT.replace('kind = "text"', 'kind = "paper"')
        with self.assertRaisesRegex(CanonError, "url"):
            load(write(paper))
        linked = paper.replace('edition = "2nd ed."',
                               'url = "https://example.invalid/p.pdf"')
        self.assertEqual(load(write(linked)).kind, "paper")


class TestLocator(unittest.TestCase):
    """A locator is what makes grounding affordable: the pages for one node
    instead of the whole book."""

    def setUp(self) -> None:
        self.canon = load(write(TEXT))

    def test_a_locator_reaches_the_front_matter(self) -> None:
        body = curriculum.note_body(self.canon, self.canon.topics[0])
        self.assertIn('locator: "pp. 4-31"', body)

    def test_a_locator_reaches_the_header_line(self) -> None:
        body = curriculum.note_body(self.canon, self.canon.topics[0])
        self.assertIn("*BOOK — Part I: Beginnings — pp. 4-31*", body)

    def test_no_locator_emits_no_key(self) -> None:
        """A source that does not say where a topic lives must not be made to
        say. An empty `locator:` reads as a value."""
        body = curriculum.note_body(self.canon, self.canon.topics[1])
        self.assertNotIn("locator:", body)

    def test_locators_are_optional_in_the_schema(self) -> None:
        self.assertEqual(load(write(MINIMAL)).topics[0].locator, "")


class TestRenameReporting(unittest.TestCase):
    """A note seeded before another canon made its title ambiguous sits at
    the unsuffixed filename. Reported, never performed -- it may carry a
    judgment, and this module does not move those."""

    def test_an_older_note_is_reported_as_a_rename_not_a_hole(self) -> None:
        with tempfile.TemporaryDirectory() as vault:
            alone = load(write(MINIMAL))
            seed(alone, vault)
            path = Path(vault) / "curriculum" / "test-101" / "First Thing.md"
            self.assertTrue(path.exists())

            with tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "a.toml").write_text(MINIMAL)
                (Path(directory) / "b.toml").write_text(
                    MINIMAL.replace('id = "test-101"', 'id = "test-202"')
                           .replace('number = "TEST.101"', 'number = "TEST.202"'))
                scoped = load_all(directory)[0]

            report = audit(scoped, vault)
            self.assertIn(("First Thing.md", "First Thing (TEST.101).md"),
                          report.renamed)
            self.assertNotIn("U1-01", report.holes)
            self.assertNotIn("First Thing.md", report.orphans)

    def test_seeding_declines_to_create_the_second_note(self) -> None:
        """Seeding must not answer "this topic has no note" with "this topic
        has two notes", leaving the judgment in the one the canon stopped
        naming. It skips and the audit says to move it by hand."""
        with tempfile.TemporaryDirectory() as vault:
            seed(load(write(MINIMAL)), vault)
            directory = Path(vault) / "curriculum" / "test-101"
            path = directory / "First Thing.md"
            path.write_text(path.read_text().replace("relevance: unset",
                                                     "relevance: cover"))
            judged = path.read_bytes()

            report = seed(self._scoped(), vault)

            # Both topics in this fixture share their titles with the second
            # canon, so both are waiting.
            self.assertEqual(report.awaiting_rename, ["U1-01", "U1-02"])
            self.assertEqual(report.created, [])
            self.assertEqual(path.read_bytes(), judged)
            self.assertFalse((directory / "First Thing (TEST.101).md").exists())

    @staticmethod
    def _scoped() -> curriculum.Canon:
        """The first canon, as it loads once a second one shares its titles."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(MINIMAL)
            (Path(directory) / "b.toml").write_text(
                MINIMAL.replace('id = "test-101"', 'id = "test-202"')
                       .replace('number = "TEST.101"', 'number = "TEST.202"'))
            return load_all(directory)[0]

    def test_a_scoped_note_says_why_it_is_scoped(self) -> None:
        canon = self._scoped()
        body = curriculum.note_body(canon, canon.topics[0])
        self.assertIn("filename-scoped to TEST.101", body)


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

    def test_the_first_import_set_is_present(self) -> None:
        """18.06SC, 18.05, 18.655 and 6.438 -- the spine for foundations of
        Bayesian modelling, per docs/curriculum.md."""
        if not REPO_CANON.is_dir():
            self.skipTest(f"{REPO_CANON} not mounted")
        numbers = {c.number for c in load_all(REPO_CANON)}
        self.assertLessEqual({"18.06SC", "18.05", "18.655", "6.438"}, numbers)

    def test_every_canon_records_what_it_excluded(self) -> None:
        """"What did the import leave out" has to be answerable, so the field
        is mandatory in practice even though the schema allows it to be
        empty."""
        if not REPO_CANON.is_dir():
            self.skipTest(f"{REPO_CANON} not mounted")
        for canon in load_all(REPO_CANON):
            self.assertTrue(canon.excluded,
                            f"{canon.number} does not say what it excluded")

    def test_no_assessment_sneaked_in_as_a_topic(self) -> None:
        # Word boundaries, not substrings: the first version of this flagged
        # 18.05's "Introduction to Statistics, Examples, Likelihood, MLE"
        # because "examples" contains "exam".
        assessment = re.compile(r"\b(exam|quiz|midterm|final)\b", re.IGNORECASE)
        if not REPO_CANON.is_dir():
            self.skipTest(f"{REPO_CANON} not mounted")
        for canon in load_all(REPO_CANON):
            for topic in canon.topics:
                self.assertIsNone(assessment.search(topic.name),
                                  f"{canon.number} {topic.ref}: {topic.name}")

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


class TestTheCLILabelsEveryKind(unittest.TestCase):
    """`smrt-curriculum seed` printed a bare ":" for a text canon, because it
    labelled its output with `number` -- which a course has and a book does
    not. Cheap bug, and the kind that only shows up the first time a second
    kind of source exists."""

    def test_seed_and_audit_label_a_canon_with_no_number(self) -> None:
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "t.toml").write_text(TEXT)
            with tempfile.TemporaryDirectory() as vault:
                for action in ("list", "seed", "audit"):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        curriculum.main([action, directory, vault])
                    self.assertIn("BOOK", out.getvalue(), action)
                    self.assertNotRegex(out.getvalue(), r"(?m)^: ", action)
