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
import unittest.mock
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

    def test_titles_that_collide_after_sanitizing_do_not_merge(self) -> None:
        """Two titles differing only in forbidden punctuation would seed into
        one note and silently lose one of them. They are now qualified by ref
        instead of refused -- the harm was the merge, and a book legitimately
        reuses section titles, so refusing would have blocked real imports."""
        # "A/B" and "A-B" both sanitize to "A-B" -- a slash against a hyphen
        # is exactly the pair that collides, which is why the first version of
        # this test ("First Thing" vs "First/Thing") did not.
        clash = MINIMAL.replace('name = "First Thing"', 'name = "A/B"')
        clash = clash.replace('name = "Second: Thing"', 'name = "A-B"')
        canon = load(write(clash))
        self.assertEqual([t.filename for t in canon.topics],
                         ["A-B (U1-01).md", "A-B (U1-02).md"])

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
            self.assertTrue(scoped.qualifiers)
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
                    self.assertEqual(topic.qualifiers, ())

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
        self.assertIn("qualified (TEST.101)", body)


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


BOOK = """
[source]
kind = "text"
id = "split-book"
short = "SPLIT"
title = "A Book In Pieces"
author = "Someone"
edition = "1st ed."
verified = "2026-09-11"
root = "Shelf/Chapters"

[[file]]
id = "ch1"
path = "one.pdf"
page_offset = 0

[[file]]
id = "ch2"
path = "two.pdf"
page_offset = -14

[[topic]]
ref = "1.1"
unit = "Chapter 1"
name = "Introduction"
file = "ch1"
pages = "2-6"

[[topic]]
ref = "2.1"
unit = "Chapter 2"
name = "Introduction"
file = "ch2"
pages = "31-44"
"""


class TestSourceFiles(unittest.TestCase):
    """A book split into per-chapter PDFs has a different page offset per
    file, and getting one wrong extracts the wrong pages while reporting
    nothing. So the arithmetic lives in code, and the canon is what gets
    checked."""

    def setUp(self) -> None:
        self.canon = load(write(BOOK))

    def test_printed_pages_resolve_to_pdf_pages(self) -> None:
        second = self.canon.topics[1]
        self.assertEqual(second.page_range, (31, 44))
        self.assertEqual(
            self.canon.locate(second),
            ("Shelf/Chapters/two.pdf", 17, 30),
        )

    def test_a_zero_offset_file_resolves_unchanged(self) -> None:
        self.assertEqual(self.canon.locate(self.canon.topics[0]),
                         ("Shelf/Chapters/one.pdf", 2, 6))

    def test_a_single_page_is_a_range_of_one(self) -> None:
        one = load(write(BOOK.replace('pages = "2-6"', 'pages = "2"')))
        self.assertEqual(one.locate(one.topics[0])[1:], (2, 2))

    def test_a_topic_with_no_pages_does_not_resolve(self) -> None:
        """None is a legitimate answer. The alternative is guessing."""
        bare = load(write(BOOK.replace('pages = "2-6"', "")))
        self.assertIsNone(bare.locate(bare.topics[0]))

    def test_a_dangling_file_reference_is_refused(self) -> None:
        """It would resolve to "no locator" -- a locator that silently stops
        working is worse than one that never existed."""
        with self.assertRaisesRegex(CanonError, "not declared"):
            load(write(BOOK.replace('file = "ch2"', 'file = "ch9"')))

    def test_duplicate_file_ids_are_refused(self) -> None:
        with self.assertRaisesRegex(CanonError, "duplicate file ids"):
            load(write(BOOK.replace('id = "ch2"', 'id = "ch1"')))

    def test_a_non_integer_offset_is_refused(self) -> None:
        with self.assertRaisesRegex(CanonError, "page_offset"):
            load(write(BOOK.replace("page_offset = -14", 'page_offset = "-14"')))

    def test_malformed_pages_are_refused(self) -> None:
        for bad in ('"chapter 5"', '"31--44"', '"around 31"'):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(CanonError, "expected"):
                    load(write(BOOK.replace('pages = "31-44"', f"pages = {bad}")))

    def test_backwards_pages_are_refused(self) -> None:
        with self.assertRaisesRegex(CanonError, "backwards"):
            load(write(BOOK.replace('pages = "31-44"', 'pages = "44-31"')))

    def test_pages_without_a_file_are_refused_when_ambiguous(self) -> None:
        with self.assertRaisesRegex(CanonError, "no file"):
            load(write(BOOK.replace('file = "ch2"\n', "")))

    def test_one_file_needs_no_reference(self) -> None:
        """The single-PDF book case: naming the file every time is noise."""
        single = BOOK.split("[[file]]\nid = \"ch2\"")[0] + '''
[[topic]]
ref = "1.1"
unit = "Chapter 1"
name = "Introduction"
pages = "2-6"
'''
        canon = load(write(single))
        self.assertEqual(canon.locate(canon.topics[0]),
                         ("Shelf/Chapters/one.pdf", 2, 6))

    def test_a_repeated_title_is_qualified_by_ref(self) -> None:
        """ASM has "Introduction" in sixteen chapters. That is how books are
        written, so it is qualified rather than refused."""
        self.assertEqual([t.filename for t in self.canon.topics],
                         ["Introduction (1.1).md", "Introduction (2.1).md"])

    def test_repeats_are_reported_by_ref_not_by_canon(self) -> None:
        self.assertEqual(curriculum.repeats(self.canon),
                         {"Introduction": ["1.1", "2.1"]})

    def test_overlaps_counts_distinct_canons(self) -> None:
        """A book reusing a title in sixteen chapters is not sixteen sources
        covering it, and reporting it as "ASM, ASM, ASM" was worse than
        useless."""
        self.assertEqual(curriculum.overlaps([self.canon]), {})

    def test_qualifiers_compose_across_both_causes(self) -> None:
        """A title repeated inside one canon AND shared with another needs
        both qualifiers, or one of the two notes is still ambiguous."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "a.toml").write_text(BOOK)
            (Path(directory) / "b.toml").write_text(
                BOOK.replace('id = "split-book"', 'id = "other-book"')
                    .replace('short = "SPLIT"', 'short = "OTHER"'))
            first = load_all(directory)[0]
            names = [t.filename for t in first.topics]
            self.assertEqual(names, ["Introduction (1.1 · SPLIT).md",
                                     "Introduction (2.1 · SPLIT).md"])
            self.assertEqual(len(set(names)), 2)

    def test_the_note_records_the_file_and_pages(self) -> None:
        body = curriculum.note_body(self.canon, self.canon.topics[1])
        self.assertIn('file: "ch2"', body)
        self.assertIn('pages: "31-44"', body)
        self.assertIn("SPLIT — Chapter 2 — pp. 31-44", body)


class TestTheASMCanon(unittest.TestCase):
    """The set text for the live class. Imported from the book's own Contents
    PDF, so the citation and the source are the same file."""

    def canon(self) -> curriculum.Canon:
        path = REPO_CANON / "kery-asm.toml"
        if not path.exists():
            self.skipTest("ASM canon not mounted")
        return load(path)

    def test_it_loads_with_a_file_per_chapter(self) -> None:
        canon = self.canon()
        self.assertEqual(canon.kind, "text")
        self.assertEqual(len(canon.files), 21)
        self.assertEqual(len(canon.units), 21)

    def test_every_topic_resolves_to_a_page_range(self) -> None:
        """The whole point of the import. A topic that cannot be located is a
        topic the lesson has to guess at."""
        canon = self.canon()
        for topic in canon.topics:
            with self.subTest(ref=topic.ref):
                self.assertIsNotNone(canon.locate(topic))

    def test_page_ranges_stay_inside_their_chapter(self) -> None:
        canon = self.canon()
        starts = {f.id: 1 - f.page_offset for f in canon.files}
        for topic in canon.topics:
            first, last = topic.page_range
            with self.subTest(ref=topic.ref):
                self.assertGreaterEqual(first, starts[topic.file])
                self.assertGreaterEqual(last, first)

    def test_refs_match_their_chapter_and_unit(self) -> None:
        """A topic filed under the wrong chapter would read the wrong PDF."""
        canon = self.canon()
        for topic in canon.topics:
            with self.subTest(ref=topic.ref):
                self.assertEqual(topic.file, "ch" + topic.ref.split(".")[0])
                self.assertTrue(
                    topic.unit.startswith(f"Chapter {topic.ref.split('.')[0]}:"),
                    topic.unit)


class TestLocateAndFigure(unittest.TestCase):
    """Both exist so that no model converts printed pages to PDF pages. A
    wrong sum returns plausible text about the wrong subject, or a picture of
    the wrong page, and reports nothing either way."""

    def run_cli(self, *args: str) -> tuple[int, str]:
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "b.toml").write_text(BOOK)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = curriculum.main([*args, directory, "/tmp"])
            return code, out.getvalue()

    def test_locate_applies_the_offset(self) -> None:
        code, out = self.run_cli("locate", "SPLIT/2.1")
        self.assertEqual(code, 0)
        self.assertIn("printed pp. 31-44  ->  pdf pp. 17-30", out)
        self.assertIn("pdftotext -f 17 -l 30", out)

    def test_figure_applies_the_offset_to_one_page(self) -> None:
        code, out = self.run_cli("figure", "SPLIT/2.1", "33")
        self.assertEqual(code, 0)
        self.assertIn("printed p. 33 -> pdf p. 19", out)
        self.assertIn("-f 19 -l 19", out)

    def test_figure_uses_singlefile_so_the_embed_name_is_knowable(self) -> None:
        """Without it pdftoppm pads the page suffix to the width of the
        document's last page, so the same command yields "-19" in a 62-page
        chapter and "-019" in a 579-page book."""
        _, out = self.run_cli("figure", "SPLIT/2.1", "33")
        self.assertIn("-singlefile", out)
        self.assertIn("![[split-book-p33.png]]", out)

    def test_a_page_outside_the_topic_warns_but_still_works(self) -> None:
        """A figure often sits a page outside the section that discusses it."""
        code, out = self.run_cli("figure", "SPLIT/2.1", "50")
        self.assertEqual(code, 0)
        self.assertIn("outside", out)
        self.assertIn("-f 36 -l 36", out)

    def test_an_unknown_ref_fails_rather_than_guessing(self) -> None:
        code, out = self.run_cli("locate", "SPLIT/9.9")
        self.assertEqual(code, 1)
        self.assertIn("no topic", out)

    def test_a_topic_with_no_pages_says_so(self) -> None:
        code, out = self.run_cli("locate", "TEST.101/U1-01")
        self.assertEqual(code, 1)

    def test_figure_needs_a_page_number(self) -> None:
        """Called without the trailing directories, because `figure` takes its
        page positionally and a temp dir in that slot is not a page."""
        import contextlib
        import io

        if not REPO_CANON.is_dir():
            self.skipTest(f"{REPO_CANON} not mounted")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = curriculum.main(["figure", "ASM/2.5"])
        self.assertEqual(code, 2)
        self.assertIn("usage", out.getvalue())


class TestSnip(unittest.TestCase):
    """`snip` cuts a region out of a page, because `pdftotext` preserves prose
    and destroys layout.

    Measured on 2026-09-15 against Kery p. 98: a table of R output extracts
    with its headers and its values on separate lines, so "reg2:hab2 is -50"
    is a reconstruction the learner has no way to check. The failure this
    prevents is a tutor describing a table it cannot actually read."""

    def run_cli(self, *args: str) -> tuple[int, str]:
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "b.toml").write_text(BOOK)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = curriculum.main([*args, directory, "/tmp"])
            return code, out.getvalue()

    def test_without_a_box_it_renders_a_preview_to_look_at(self) -> None:
        code, out = self.run_cli("snip", "SPLIT/2.1", "33")
        self.assertEqual(code, 0)
        self.assertIn(f"-r {curriculum.PREVIEW_DPI}", out)
        self.assertIn("-f 19 -l 19", out)
        self.assertIn("LOOK at it", out)

    def test_the_preview_does_not_land_in_the_vault(self) -> None:
        """Scaffolding for choosing coordinates. The notes graph is for notes,
        and a directory of half-chosen page renders is not one."""
        _, out = self.run_cli("snip", "SPLIT/2.1", "33")
        self.assertIn("/tmp/preview-p33", out)
        self.assertNotIn("/vault/attachments/split-book-p33", out)

    def test_the_box_is_scaled_from_preview_dpi_to_snip_dpi(self) -> None:
        """The reason this is a command rather than a line in a skill.
        pdftoppm's -x/-y/-W/-H are pixels AT THE CHOSEN -r, so a box measured
        on the preview names different pixels on the sharper render. Handing
        it over unscaled crops the wrong part of the page, confidently."""
        code, out = self.run_cli("snip", "SPLIT/2.1", "33", "90,405,495,165")
        self.assertEqual(code, 0)
        factor = curriculum.SNIP_DPI // curriculum.PREVIEW_DPI
        self.assertIn(f"-x {90 * factor} -y {405 * factor} "
                      f"-W {495 * factor} -H {165 * factor}", out)
        self.assertIn(f"-r {curriculum.SNIP_DPI}", out)

    def test_the_cut_lands_in_the_vault_with_a_knowable_name(self) -> None:
        code, out = self.run_cli("snip", "SPLIT/2.1", "33", "10,10,50,50")
        self.assertEqual(code, 0)
        self.assertIn("-singlefile", out)
        self.assertIn("/vault/attachments/split-book-p33", out)
        self.assertIn("![[split-book-p33.png]]", out)

    def test_it_says_how_to_cite_what_it_cut(self) -> None:
        """The other half of the complaint that prompted this: material the
        learner could not locate in their own copy. A snip without a printed
        page number is still unfindable."""
        _, out = self.run_cli("snip", "SPLIT/2.1", "33", "10,10,50,50")
        self.assertIn("cite it: SPLIT p. 33", out)

    def test_a_malformed_box_is_not_read_as_a_directory(self) -> None:
        """It sits in the same argument slot as the canon directory, so left
        alone `snip X/Y 98 90,405,495` surfaces as "no canon files in
        90,405,495" -- an error about the wrong thing entirely."""
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = curriculum.main(["snip", "SPLIT/2.1", "33", "90,405,495"])
        self.assertEqual(code, 2)
        self.assertIn("not a crop box", out.getvalue())

    def test_a_page_outside_the_topic_warns_but_still_works(self) -> None:
        code, out = self.run_cli("snip", "SPLIT/2.1", "50", "10,10,50,50")
        self.assertEqual(code, 0)
        self.assertIn("outside", out)


class TestAnchoredCrops(unittest.TestCase):
    """Choosing a crop box by looking at a preview does not work.

    Measured 2026-09-15: asked for the design matrix on p. 99, a model guessed
    a box, saw the result was short, guessed a taller one from the same origin,
    and still cut off rows 4-6 and clipped the first line. The page has a text
    layer that knows where every line is, to the point."""

    PAGE = [
        # (yMin, yMax, xMin, xMax, text) in points
        (100.0, 110.0, 50.0, 300.0, "Some earlier paragraph"),
        (130.0, 140.0, 50.0, 280.0, "Finally, here is the means parameterization"),
        (150.0, 160.0, 50.0, 260.0, "Coefficients:"),
        (170.0, 180.0, 50.0, 400.0, "reg1:hab1 reg2:hab1 reg1:hab2"),
        (190.0, 200.0, 50.0, 200.0, "[ . . . ]"),
        (220.0, 230.0, 50.0, 300.0, "A later paragraph entirely"),
    ]

    def box(self, start: str, end: str, dpi: int = 220):
        with unittest.mock.patch.object(curriculum, "_lines_with_boxes",
                                        return_value=self.PAGE):
            return curriculum.anchor_box("ignored.pdf", 1, start, end, dpi)

    def test_the_box_spans_the_anchored_lines(self) -> None:
        x, y, w, h = self.box("Finally, here is", "[ . . . ]")
        scale = 220 / 72
        # Top edge sits between the previous line and the first anchored one,
        # bottom between the last anchored one and the next.
        self.assertGreater(y, 110.0 * scale)
        self.assertLess(y, 130.0 * scale)
        self.assertGreater(y + h, 200.0 * scale)
        self.assertLess(y + h, 220.0 * scale)

    def test_it_does_not_eat_the_neighbouring_lines(self) -> None:
        """A crop with a sliced-off row of text at its edge reads as a mistake
        even when everything asked for is present."""
        _, y, _, h = self.box("Coefficients:", "[ . . . ]")
        scale = 220 / 72
        self.assertGreater(y, 140.0 * scale)      # clear of the line above
        self.assertLess(y + h, 220.0 * scale)     # clear of the line below

    def test_the_match_is_case_and_whitespace_insensitive(self) -> None:
        a = self.box("finally,   HERE is", "[ . . . ]")
        b = self.box("Finally, here is", "[ . . . ]")
        self.assertEqual(a, b)

    def test_to_matches_the_LAST_occurrence(self) -> None:
        """Which is why a distinctive phrase matters: `--to "1"` would run to
        the bottom of the page rather than to the line meant."""
        _, _, _, near = self.box("Coefficients:", "Coefficients:")
        _, _, _, far = self.box("Coefficients:", "[ . . . ]")
        self.assertLess(near, far)

    def test_a_phrase_that_matches_nothing_is_an_error(self) -> None:
        """Not a silent crop of whatever was nearby."""
        with self.assertRaises(curriculum._Unresolved) as caught:
            self.box("no such line anywhere", "[ . . . ]")
        self.assertIn("no line", str(caught.exception))

    def test_an_end_above_the_start_is_an_error(self) -> None:
        with self.assertRaises(curriculum._Unresolved):
            self.box("[ . . . ]", "Some earlier paragraph")

    def test_a_page_with_no_text_layer_says_so(self) -> None:
        """A scan. The whole locator path depends on a text layer, and this is
        the one place it can be diagnosed precisely."""
        with unittest.mock.patch.object(curriculum, "_lines_with_boxes",
                                        return_value=[]):
            with self.assertRaises(curriculum._Unresolved) as caught:
                curriculum.anchor_box("scan.pdf", 1, "a", "b", 220)
        self.assertIn("no text layer", str(caught.exception))

    def test_points_convert_to_pixels_at_the_render_dpi(self) -> None:
        """pdftoppm crops in pixels; the layout is in points. 72 to the inch."""
        _, y_low, _, _ = self.box("Coefficients:", "[ . . . ]", dpi=72)
        _, y_high, _, _ = self.box("Coefficients:", "[ . . . ]", dpi=144)
        self.assertEqual(y_high, y_low * 2)
