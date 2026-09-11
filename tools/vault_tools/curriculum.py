"""The curriculum layer: load the canon, seed topic notes, audit coverage.

See `docs/curriculum.md` for why the node set is imported rather than
generated. This module is the mechanism, and two of its properties are
deliberate rather than incidental.

**Seeding creates and never modifies.** A topic note holds two kinds of
field: canon (which course, which unit, the OCW title) and judgment
(`relevance`, who decided it, what was taught, how it went). Seeding writes
the first kind exactly once. It will not touch an existing note even when the
canon has changed, because the alternative is a mechanism that can silently
overwrite the judgment layer -- and a design built on "nothing is lost
quietly" cannot have an overwriting seeder at the bottom of it.

A canon that has moved is therefore a *reported* condition, not a resolved
one. `audit()` names the drift and a human decides.

**The canon lives in the repo, not the vault.** That is what makes "never
edited by the agent" structural rather than a promise: the agent works in
/vault, and the canon is not there. Topic notes in the vault are generated
from it.

**A canon is not always a course.** Three kinds load through the same path:
a `course` (a syllabus), a `text` (a book's table of contents) and a `paper`.
All three are externally authored node sets with a citation, which is the only
property this layer actually depends on. They differ in what citing them
requires -- a book has an edition where a course has a URL -- and in how they
should be *used*, which is the teach skill's problem rather than this module's.

Topics may carry a `locator`: where in the source the topic lives (`pp.
108-113`, `§5.4`). That field is why the import pays off twice. Coverage is the
obvious use; the second is that a locator turns "ground this lesson in my
textbook" from a whole-book context problem into a bounded read of the pages
for one node.

Runs on Python 3.11+ for `tomllib` -- so inside the image, like the rest of
the tool server, not on a host interpreter.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

# Obsidian forbids these in note filenames, and several break on iOS or
# Windows sync -- which matters because the vault is meant to reach a phone.
# The exact title survives in front matter and as an alias, so `[[Solving
# Ax = 0: Pivot Variables, Special Solutions]]` still resolves.
_UNSAFE = re.compile(r'[:/\\|#^\[\]?*"<>]')

# A printed page or a printed page range. Deliberately narrow: "chapter 5"
# and "around p. 100" belong in `locator`, which is free text.
_PAGES = re.compile(r"\d{1,5}(?:-\d{1,5})?")

# Every kind needs an identity and a date someone checked it. What counts as
# a citation differs by kind, so the rest is per-kind: a course lives at a URL,
# a book is identified by author and edition, a paper by author and a link.
# Asking a book for a `number` would mean inventing one, which is the failure
# this whole layer exists to prevent.
REQUIRED_SOURCE_FIELDS = ("id", "title", "verified")
REQUIRED_BY_KIND = {
    "course": ("number", "url"),
    "text": ("author", "edition"),
    "paper": ("author", "url"),
}
KINDS = tuple(REQUIRED_BY_KIND)
REQUIRED_TOPIC_FIELDS = ("ref", "unit", "name")


class CanonError(Exception):
    """The canon is malformed. Loud, because a bad canon is inherited by every
    vault seeded from it."""


@dataclass(frozen=True)
class SourceFile:
    """One file of a source, and how its page numbers relate to the book's.

    `page_offset` exists because a PDF's page 1 is almost never the book's
    page 1, and a book split into per-chapter PDFs has a *different* offset
    per file. Getting this wrong extracts the wrong pages and says nothing,
    which is the worst way for grounding to fail -- so the arithmetic is done
    here rather than by a model doing sums in its head.

        pdf_page = printed_page + page_offset
    """

    id: str
    path: str
    page_offset: int = 0

    def pdf_page(self, printed: int) -> int:
        return printed + self.page_offset


@dataclass(frozen=True)
class Topic:
    ref: str
    unit: str
    name: str
    #: Where in the source this lives: "pp. 108-113", "§5.4", "Lecture 12".
    #: Optional, because a syllabus that does not say must not be made to.
    locator: str = ""
    #: Which `[[file]]` id holds it. Defaults to the only one, if there is one.
    file: str = ""
    #: Printed page range, "31" or "31-45". Structured so it can be resolved
    #: to a pdftotext invocation; `locator` stays free text for citation.
    pages: str = ""
    #: What distinguishes this note's filename from another topic with the
    #: same title. `load` adds the ref when a title repeats inside one canon;
    #: `load_all` adds the canon's tag when two canons share a title. Held as
    #: data rather than baked into the name so `filename` stays a pure
    #: function and the two cases compose.
    qualifiers: tuple[str, ...] = ()

    @property
    def page_range(self) -> tuple[int, int] | None:
        if not self.pages:
            return None
        first, _, last = self.pages.partition("-")
        return (int(first), int(last or first))

    @property
    def filename(self) -> str:
        stem = _safe_name(self.name)
        if self.qualifiers:
            inner = " · ".join(_safe_name(q) for q in self.qualifiers)
            stem = f"{stem} ({inner})"
        return stem + ".md"


@dataclass(frozen=True)
class Canon:
    course_id: str
    number: str
    title: str
    url: str
    verified: str
    topics: tuple[Topic, ...]
    kind: str = "course"
    author: str = ""
    edition: str = ""
    short: str = ""
    prerequisites: str = ""
    textbook: str = ""
    excluded: str = ""
    #: Directory holding this source's files, relative to the subject mount.
    root: str = ""
    files: tuple[SourceFile, ...] = ()

    def file_for(self, topic: Topic) -> SourceFile | None:
        if topic.file:
            return next((f for f in self.files if f.id == topic.file), None)
        return self.files[0] if len(self.files) == 1 else None

    def locate(self, topic: Topic) -> tuple[str, int, int] | None:
        """(path under the subject mount, first pdf page, last pdf page).

        None when the canon does not say where the topic is -- which is a
        legitimate answer and must not be guessed at.
        """
        handle = self.file_for(topic)
        printed = topic.page_range
        if handle is None or printed is None:
            return None
        path = f"{self.root}/{handle.path}" if self.root else handle.path
        return (path, handle.pdf_page(printed[0]), handle.pdf_page(printed[1]))

    @property
    def units(self) -> tuple[str, ...]:
        seen: list[str] = []
        for topic in self.topics:
            if topic.unit not in seen:
                seen.append(topic.unit)
        return tuple(seen)

    @property
    def tag(self) -> str:
        """The short handle: `18.05`, `BDA3`. Used in note headers and as the
        disambiguating suffix, so it wants to be brief and stable."""
        return self.short or self.number or self.course_id

    @property
    def label(self) -> str:
        """One line naming the source, however it is identified."""
        if self.kind == "course":
            return f"{self.number} {self.title}".strip()
        author = f"{self.author}, " if self.author else ""
        edition = f" ({self.edition})" if self.edition else ""
        return f"{author}{self.title}{edition}"

    @property
    def citation(self) -> str:
        """Markdown. A course or paper links; a book with no URL still cites."""
        return f"[{self.label}]({self.url})" if self.url else self.label


def _safe_name(name: str) -> str:
    cleaned = _UNSAFE.sub("-", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    if not cleaned:
        raise CanonError(f"topic name reduces to nothing: {name!r}")
    return cleaned


def load(path: str | Path) -> Canon:
    """Parse and validate one canon file."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise CanonError(f"{path.name}: {error}") from error

    # `[source]` and `[course]` are the same table under two names. A book
    # under a heading called [course] reads as a mistake, and a heading that
    # reads as a mistake eventually becomes one.
    if isinstance(raw.get("source"), dict) and isinstance(raw.get("course"), dict):
        raise CanonError(f"{path.name}: has both [source] and [course]; pick one")
    course = raw.get("source") or raw.get("course")
    if not isinstance(course, dict):
        raise CanonError(f"{path.name}: missing a [source] table")

    kind = course.get("kind", "course")
    if kind not in REQUIRED_BY_KIND:
        raise CanonError(f"{path.name}: kind {kind!r} is not one of {list(KINDS)}")

    required = REQUIRED_SOURCE_FIELDS + REQUIRED_BY_KIND[kind]
    missing = [f for f in required if not course.get(f)]
    if missing:
        raise CanonError(f"{path.name}: [{kind}] is missing {missing}")

    files: list[SourceFile] = []
    for index, entry in enumerate(raw.get("file") or [], 1):
        absent = [f for f in ("id", "path") if not entry.get(f)]
        if absent:
            raise CanonError(f"{path.name}: file {index} is missing {absent}")
        offset = entry.get("page_offset", 0)
        if not isinstance(offset, int):
            raise CanonError(f"{path.name}: file {entry['id']} has a "
                             f"non-integer page_offset {offset!r}")
        files.append(SourceFile(id=str(entry["id"]), path=str(entry["path"]),
                                page_offset=offset))
    ids = [f.id for f in files]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise CanonError(f"{path.name}: duplicate file ids {repeated}")

    entries = raw.get("topic") or []
    if not entries:
        raise CanonError(f"{path.name}: no [[topic]] entries")

    topics: list[Topic] = []
    for index, entry in enumerate(entries, 1):
        absent = [f for f in REQUIRED_TOPIC_FIELDS if not entry.get(f)]
        if absent:
            raise CanonError(f"{path.name}: topic {index} is missing {absent}")
        handle = str(entry.get("file", ""))
        if handle and handle not in ids:
            # A dangling reference resolves to "no locator", and a locator
            # that silently stops working is worse than one that never was.
            raise CanonError(f"{path.name}: topic {entry['ref']} points at "
                             f"file {handle!r}, which is not declared")
        pages = str(entry.get("pages", ""))
        if pages and not _PAGES.fullmatch(pages):
            raise CanonError(f"{path.name}: topic {entry['ref']} has pages "
                             f"{pages!r}; expected \"31\" or \"31-45\"")
        if pages and not handle and len(files) != 1:
            raise CanonError(
                f"{path.name}: topic {entry['ref']} gives pages but no file, "
                f"and there are {len(files)} to choose from"
            )
        topic = Topic(ref=entry["ref"], unit=entry["unit"], name=entry["name"],
                      locator=str(entry.get("locator", "")),
                      file=handle, pages=pages)
        span = topic.page_range
        if span and span[0] > span[1]:
            raise CanonError(f"{path.name}: topic {entry['ref']} has pages "
                             f"{pages!r} running backwards")
        topics.append(topic)

    refs = [t.ref for t in topics]
    duplicates = sorted({r for r in refs if refs.count(r) > 1})
    if duplicates:
        raise CanonError(f"{path.name}: duplicate topic refs {duplicates}")

    # A book reuses section titles: ASM has "Introduction", "Data generation"
    # and "Summary and outlook" in most of its 21 chapters. That is how books
    # are written, not a defect in the import, so repeated titles are
    # qualified by ref rather than refused. Refs are unique (checked above),
    # so this always resolves.
    #
    # It also covers the case this check originally existed for -- two titles
    # differing only in punctuation, "A/B" and "A-B", which sanitize alike.
    # Those are still suspicious, but the harm was a silent merge and
    # qualifying prevents it either way.
    counts = Counter(t.filename for t in topics)
    repeated = {name for name, seen in counts.items() if seen > 1}
    if repeated:
        topics = [
            replace(t, qualifiers=t.qualifiers + (t.ref,))
            if t.filename in repeated else t
            for t in topics
        ]
        left = sorted(name for name, seen
                      in Counter(t.filename for t in topics).items() if seen > 1)
        if left:
            raise CanonError(
                f"{path.name}: topics still collide on filename {left} after "
                "qualifying by ref — distinguish the titles"
            )

    return Canon(
        course_id=course["id"],
        number=course.get("number", ""),
        title=course["title"],
        url=course.get("url", ""),
        verified=str(course["verified"]),
        topics=tuple(topics),
        kind=kind,
        author=course.get("author", ""),
        edition=course.get("edition", ""),
        short=course.get("short", ""),
        prerequisites=course.get("prerequisites", ""),
        textbook=course.get("textbook", ""),
        excluded=course.get("excluded", ""),
        root=course.get("root", ""),
        files=tuple(files),
    )


def load_all(directory: str | Path) -> list[Canon]:
    found = sorted(Path(directory).glob("*.toml"))
    if not found:
        raise CanonError(f"no canon files in {directory}")
    return _disambiguate([load(path) for path in found])


def overlaps(canons: Sequence[Canon]) -> dict[str, list[str]]:
    """Topic titles that more than one canon covers, mapped to their tags.

    Worth reporting rather than only handling. Overlap is the signal that two
    sources teach the same thing, which is exactly where "cover, but reframe"
    decisions live -- a textbook's chapter and a syllabus's lecture on the same
    topic are one thing to learn and two accounts of it.
    """
    where: dict[str, list[str]] = {}
    for canon in canons:
        for topic in canon.topics:
            tags = where.setdefault(topic.name, [])
            # Distinct canons, not occurrences. A book reusing "Introduction"
            # in sixteen chapters is not sixteen sources covering it, and
            # reporting it as "ASM, ASM, ASM, ..." was worse than useless.
            if canon.tag not in tags:
                tags.append(canon.tag)
    return {name: tags for name, tags in sorted(where.items()) if len(tags) > 1}


def repeats(canon: Canon) -> dict[str, list[str]]:
    """Titles this canon uses more than once, mapped to the refs using them.

    Normal in a book and worth surfacing anyway: it is why those notes have
    qualified filenames instead of plain ones.
    """
    where: dict[str, list[str]] = {}
    for topic in canon.topics:
        where.setdefault(topic.name, []).append(topic.ref)
    return {name: refs for name, refs in sorted(where.items()) if len(refs) > 1}


def _disambiguate(canons: list[Canon]) -> list[Canon]:
    """Suffix the filename of any topic title that two canons share.

    Within a canon, a filename collision is an error (see `load`): two titles
    differing only in punctuation would seed into one note and lose one.

    Across canons it is a different condition with a different remedy. Seeding
    puts each canon in its own directory, so nothing is overwritten -- but
    Obsidian resolves wikilinks by filename across the entire vault, so a
    duplicate makes `[[Bayes' Theorem]]` AMBIGUOUS rather than broken, which is
    worse: it silently resolves to whichever note Obsidian picks.

    This used to be a load error, on the reasoning that two MIT courses sharing
    a topic title meant the import was wrong. That reasoning does not survive
    contact with a second kind of source. A textbook for a course *will* share
    most of its topic titles with that course's syllabus, and so will a second
    course on the same subject -- the overlap is true, not a mistake, and
    refusing to load it would make importing your own class's text impossible.

    So the shared ones become `Bayes' Theorem (18.05)` and
    `Bayes' Theorem (BDA3)`, and the bare link stops existing rather than
    resolving arbitrarily. `overlaps()` reports which titles this happened to.
    """
    counts = Counter(t.filename for canon in canons for t in canon.topics)
    shared = {name for name, seen in counts.items() if seen > 1}
    if not shared:
        return canons

    # The suffix is only a fix if the tags themselves are distinct.
    tags = [c.tag for c in canons]
    ambiguous = sorted({t for t in tags if tags.count(t) > 1})
    if ambiguous:
        raise CanonError(
            f"canons share a tag {ambiguous} and also share topic titles, so "
            "there is no unambiguous filename to give them — set a distinct "
            "`short` in one of them"
        )

    resolved = [
        replace(canon, topics=tuple(
            replace(topic, qualifiers=topic.qualifiers + (canon.tag,))
            if topic.filename in shared else topic
            for topic in canon.topics
        ))
        for canon in canons
    ]

    # Belt and braces: a topic literally titled "X (BDA3)" in one canon and
    # "X" in a canon tagged BDA3 would collide again after suffixing. Vanishing
    # odds, but the guarantee this function exists to provide is that no two
    # seeded notes share a filename, so it is checked rather than assumed.
    still = Counter(t.filename for canon in resolved for t in canon.topics)
    left = sorted(name for name, seen in still.items() if seen > 1)
    if left:
        raise CanonError(f"topics still collide after disambiguating: {left}")
    return resolved


def note_body(canon: Canon, topic: Topic) -> str:
    """A seeded topic note: canon in front matter, judgment left blank.

    `relevance: unset` is the queryable hole — a canonical topic neither party
    has judged yet. It is the default precisely so that the holes exist as
    data on day one rather than being discovered by their absence.

    Note that `source:` is *provenance* — `canon` here, `agent` on a node the
    agent added beyond any canon — while `canon_*` fields cite which canon.
    Two different questions that look like one.
    """
    alias = ""
    if topic.qualifiers:
        # No alias at all. The bare title is shared -- with another section of
        # this same source, or with another canon -- and an alias restoring it
        # would re-create through aliases exactly the ambiguity the qualified
        # filename removes.
        pass
    elif _safe_name(topic.name) != topic.name:
        alias = f'aliases: ["{topic.name}"]\n'

    locator = f'locator: "{topic.locator}"\n' if topic.locator else ""
    if topic.file:
        locator += f'file: "{topic.file}"\n'
    if topic.pages:
        locator += f'pages: "{topic.pages}"\n'
    printed = f"pp. {topic.pages}" if topic.pages else ""
    where = " — ".join(x for x in (canon.tag, topic.unit,
                                   topic.locator or printed) if x)
    shared = ""
    if topic.qualifiers:
        inner = " · ".join(topic.qualifiers)
        shared = (
            f"\nThis title is not unique, so the note is qualified ({inner}) "
            "and carries no alias — a bare link would be ambiguous. Link it "
            "explicitly.\n"
        )
    return f"""---
type: curriculum-topic
curriculum: {canon.course_id}
canon_kind: {canon.kind}
canon_title: "{canon.label}"
canon_ref: "{canon.course_id}/{topic.ref}"
{locator}unit: "{topic.unit}"
topic: "{topic.name}"
source: canon
{alias}relevance: unset          # unset | cover | skip | deferred
relevance_decided_by: ""  # user | agent | joint
relevance_note: ""
first_taught: ""
outcomes: []
---

# {topic.name}

*{where}*

Canonical topic, imported from {canon.citation}. Nothing below this line is
written by the import.
{shared}

## Relevance

<!--
Why this matters for the current objectives, or why it does not. Prose,
because the useful judgment is usually "cover, but reframe" rather than a
plain yes or no — and no enum holds that. Set `relevance` in the front
matter to make it countable, and say why here.
-->

## Notes

<!-- Yours. -->
"""


@dataclass
class SeedReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    #: Topics whose note exists under its older, unscoped filename. Skipped
    #: rather than written, because writing would leave two notes for one
    #: topic with the judgment in the one the canon no longer names.
    awaiting_rename: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        waiting = (f", {len(self.awaiting_rename)} awaiting a rename"
                   if self.awaiting_rename else "")
        return (f"{len(self.created)} created, "
                f"{len(self.existing)} already present" + waiting)


def seed(canon: Canon, vault_root: str | Path) -> SeedReport:
    """Write a note per canonical topic. Creates only; never modifies."""
    target = Path(vault_root) / "curriculum" / canon.course_id
    target.mkdir(parents=True, exist_ok=True)
    report = SeedReport()
    for topic in canon.topics:
        path = target / topic.filename
        if path.exists():
            report.existing.append(topic.ref)
            continue
        # A newly imported canon can make an existing note's title ambiguous,
        # scoping the filename this topic now expects. The note already on
        # disk may carry a judgment, and creating the scoped one as well would
        # answer "one topic has no note" with "one topic has two notes" --
        # leaving the judgment in whichever one the canon stopped naming.
        # `audit` reports the move; seeding declines to make it worse.
        scoped = canon.tag in topic.qualifiers
        without = tuple(q for q in topic.qualifiers if q != canon.tag)
        if scoped and (target / replace(topic, qualifiers=without).filename).exists():
            report.awaiting_rename.append(topic.ref)
            continue
        path.write_text(note_body(canon, topic), encoding="utf-8")
        report.created.append(topic.ref)
    return report


@dataclass
class AuditReport:
    """What the vault and the canon disagree about.

    `holes` is the one this layer exists for: a canonical topic with no note
    is a topic nobody can even record a decision about.
    """

    holes: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    unjudged: list[str] = field(default_factory=list)
    judged: dict[str, list[str]] = field(default_factory=dict)
    #: (note that exists, name the canon now expects). Arises when a newly
    #: imported canon shares a topic title, so the older note's bare filename
    #: became ambiguous and is now scoped. Reported, never performed: the note
    #: on the left may carry a judgment, and this module does not move those.
    renamed: list[tuple[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        counts = ", ".join(f"{k}={len(v)}" for k, v in sorted(self.judged.items()))
        renamed = f", {len(self.renamed)} to rename" if self.renamed else ""
        return (f"{len(self.holes)} holes, {len(self.orphans)} orphans, "
                f"{len(self.unjudged)} unjudged" + renamed
                + (f" [{counts}]" if counts else ""))


_RELEVANCE = re.compile(r"^relevance:\s*(\S+)", re.MULTILINE)


def audit(canon: Canon, vault_root: str | Path) -> AuditReport:
    """Compare the canon against what the vault holds.

    Reports rather than repairs. A canon that has moved is a human's decision,
    because the note on the other side may carry a judgment worth keeping.
    """
    target = Path(vault_root) / "curriculum" / canon.course_id
    report = AuditReport()
    expected = {t.filename: t for t in canon.topics}

    present = (
        {p.name for p in target.iterdir() if p.suffix == ".md"}
        if target.is_dir() else set()
    )

    for filename, topic in expected.items():
        if filename not in present:
            report.holes.append(topic.ref)
            continue
        text = (target / filename).read_text(encoding="utf-8")
        match = _RELEVANCE.search(text)
        verdict = match.group(1) if match else "unset"
        report.judged.setdefault(verdict, []).append(topic.ref)
        if verdict == "unset":
            report.unjudged.append(topic.ref)

    # A note seeded before another canon made its title ambiguous sits at the
    # unsuffixed name. Without this it would read as a hole plus an unrelated
    # orphan, which is the same information arranged to be confusing.
    stray = present - set(expected)
    for topic in canon.topics:
        if canon.tag not in topic.qualifiers:
            continue
        # Only the canon tag can have been added after this note was seeded;
        # ref qualifiers are decided by the canon alone and never move.
        without = tuple(q for q in topic.qualifiers if q != canon.tag)
        bare = replace(topic, qualifiers=without).filename
        if bare in stray:
            report.renamed.append((bare, topic.filename))
            stray.discard(bare)
            # Not also a hole. Seeding would answer a hole by writing a second
            # note, leaving two notes for one topic and the judgment in the
            # one the canon no longer names.
            if topic.ref in report.holes:
                report.holes.remove(topic.ref)

    report.orphans = sorted(stray)
    return report


def main(argv: list[str] | None = None) -> int:
    """`python3 -m vault_tools.curriculum {seed|audit|list} [...]`"""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    action = args.pop(0) if args else "list"
    spec = args.pop(0) if action == "locate" and args else ""
    canon_dir = args.pop(0) if args else "/workspace/curriculum"
    vault = args.pop(0) if args else "/vault"

    try:
        canons = load_all(canon_dir)
    except CanonError as error:
        print(f"canon error: {error}", file=sys.stderr)
        return 1

    if action == "list":
        for canon in canons:
            print(f"{canon.tag:<10} {canon.label}  [{canon.kind}]")
            units = len(canon.units)
            located = sum(1 for t in canon.topics if t.locator)
            print(f"  {len(canon.topics)} topics, {units} "
                  f"{'unit' if units == 1 else 'units'}, "
                  f"verified {canon.verified}")
            if located:
                print(f"  {located}/{len(canon.topics)} topics carry a locator")
            if canon.files:
                print(f"  {len(canon.files)} source "
                      f"{'file' if len(canon.files) == 1 else 'files'}"
                      + (f" under {canon.root}/" if canon.root else ""))
            again = repeats(canon)
            if again:
                print(f"  {len(again)} titles repeat inside this canon "
                      "(normal in a book); those notes are qualified by ref")
            if canon.excluded:
                print(f"  excluded: {canon.excluded}")
        shared = overlaps(canons)
        if shared:
            print(f"\n{len(shared)} topic titles appear in more than one canon; "
                  "their notes are qualified by canon:")
            for name, tags in shared.items():
                print(f"  {name} — {', '.join(tags)}")
        return 0

    if action == "locate":
        # `smrt-curriculum locate ASM/2.5` -> the exact command to run.
        # The point of this existing at all is that nothing else has to do the
        # printed-page-to-pdf-page arithmetic. A model doing that sum in its
        # head and being quietly wrong extracts the wrong pages and reports
        # nothing, which is the worst available failure.
        tag, _, ref = spec.rpartition("/")
        if not tag or not ref:
            print("usage: locate <canon>/<ref>    e.g. locate ASM/2.5",
                  file=sys.stderr)
            return 2
        matches = [c for c in canons
                   if tag in (c.tag, c.course_id, c.number)]
        if not matches:
            print(f"no canon matching {tag!r}; try `list`", file=sys.stderr)
            return 1
        canon = matches[0]
        topic = next((t for t in canon.topics if t.ref == ref), None)
        if topic is None:
            print(f"{canon.tag} has no topic {ref!r}", file=sys.stderr)
            return 1
        print(f"{canon.tag} {topic.ref}  {topic.name}")
        placed = canon.locate(topic)
        if placed is None:
            print("  no locator recorded — the canon does not say where this "
                  "is, and it must not be guessed")
            return 1
        path, first, last = placed
        print(f"  printed pp. {topic.pages}  ->  pdf pp. {first}-{last}")
        print(f'  pdftotext -f {first} -l {last} "$SUBJECT_ROOT/{path}" -')
        return 0

    if action == "seed":
        for canon in canons:
            report = seed(canon, vault)
            print(f"{canon.tag}: {report}")
            for ref in report.awaiting_rename:
                print(f"  SKIPPED {ref} — an existing note holds this topic "
                      "under an unscoped filename; `audit` names the move")
        return 0

    if action == "audit":
        worst = 0
        for canon in canons:
            report = audit(canon, vault)
            print(f"{canon.tag}: {report}")
            for ref in report.holes:
                print(f"  HOLE    {ref} — no note; run seed")
            for name in report.orphans:
                print(f"  ORPHAN  {name} — not in the canon")
            for old, new in report.renamed:
                print(f"  RENAME  {old} → {new} — another canon now shares "
                      "this title; move it by hand to keep its judgment")
            if report.holes or report.orphans or report.renamed:
                worst = 1
        return worst

    print(f"unknown action {action!r}; use seed, audit or list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
