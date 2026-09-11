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
class Topic:
    ref: str
    unit: str
    name: str
    #: Where in the source this lives: "pp. 108-113", "§5.4", "Lecture 12".
    #: Optional, because a syllabus that does not say must not be made to.
    locator: str = ""
    #: Set by `load_all` when two canons share a topic title. See
    #: `_disambiguate`; a bare suffix here keeps `filename` a pure function.
    suffix: str = ""

    @property
    def filename(self) -> str:
        stem = _safe_name(self.name)
        if self.suffix:
            stem = f"{stem} ({_safe_name(self.suffix)})"
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

    entries = raw.get("topic") or []
    if not entries:
        raise CanonError(f"{path.name}: no [[topic]] entries")

    topics: list[Topic] = []
    for index, entry in enumerate(entries, 1):
        absent = [f for f in REQUIRED_TOPIC_FIELDS if not entry.get(f)]
        if absent:
            raise CanonError(f"{path.name}: topic {index} is missing {absent}")
        topics.append(Topic(ref=entry["ref"], unit=entry["unit"],
                            name=entry["name"],
                            locator=str(entry.get("locator", ""))))

    refs = [t.ref for t in topics]
    duplicates = sorted({r for r in refs if refs.count(r) > 1})
    if duplicates:
        raise CanonError(f"{path.name}: duplicate topic refs {duplicates}")

    files = [t.filename for t in topics]
    collisions = sorted({f for f in files if files.count(f) > 1})
    if collisions:
        # Two topics whose titles differ only in punctuation would seed into
        # one note and silently lose one of them.
        raise CanonError(
            f"{path.name}: topics collide on filename {collisions} — "
            "distinguish the titles"
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
            where.setdefault(topic.name, []).append(canon.tag)
    return {name: tags for name, tags in sorted(where.items()) if len(tags) > 1}


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
            replace(topic, suffix=canon.tag) if topic.filename in shared
            else topic
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
    if topic.suffix:
        # No alias at all. The bare title is shared with another canon, and an
        # alias restoring it would re-create through aliases exactly the
        # ambiguity the filename suffix removed.
        pass
    elif _safe_name(topic.name) != topic.name:
        alias = f'aliases: ["{topic.name}"]\n'

    locator = f'locator: "{topic.locator}"\n' if topic.locator else ""
    where = " — ".join(x for x in (canon.tag, topic.unit, topic.locator) if x)
    shared = ""
    if topic.suffix:
        shared = (
            "\nAnother canon covers a topic under this same title, so this "
            f"note is filename-scoped to {canon.tag} and carries no alias. "
            "Link it explicitly.\n"
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
        if topic.suffix and (target / replace(topic, suffix="").filename).exists():
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
        if not topic.suffix:
            continue
        bare = replace(topic, suffix="").filename
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
            if canon.excluded:
                print(f"  excluded: {canon.excluded}")
        shared = overlaps(canons)
        if shared:
            print(f"\n{len(shared)} topic titles appear in more than one canon; "
                  "their notes are filename-scoped:")
            for name, tags in shared.items():
                print(f"  {name} — {', '.join(tags)}")
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
