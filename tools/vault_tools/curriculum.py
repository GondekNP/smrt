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

Runs on Python 3.11+ for `tomllib` -- so inside the image, like the rest of
the tool server, not on a host interpreter.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Obsidian forbids these in note filenames, and several break on iOS or
# Windows sync -- which matters because the vault is meant to reach a phone.
# The exact title survives in front matter and as an alias, so `[[Solving
# Ax = 0: Pivot Variables, Special Solutions]]` still resolves.
_UNSAFE = re.compile(r'[:/\\|#^\[\]?*"<>]')

REQUIRED_COURSE_FIELDS = ("id", "number", "title", "url", "verified")
REQUIRED_TOPIC_FIELDS = ("ref", "unit", "name")


class CanonError(Exception):
    """The canon is malformed. Loud, because a bad canon is inherited by every
    vault seeded from it."""


@dataclass(frozen=True)
class Topic:
    ref: str
    unit: str
    name: str

    @property
    def filename(self) -> str:
        return _safe_name(self.name) + ".md"


@dataclass(frozen=True)
class Canon:
    course_id: str
    number: str
    title: str
    url: str
    verified: str
    topics: tuple[Topic, ...]
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

    course = raw.get("course")
    if not isinstance(course, dict):
        raise CanonError(f"{path.name}: missing a [course] table")
    missing = [f for f in REQUIRED_COURSE_FIELDS if not course.get(f)]
    if missing:
        raise CanonError(f"{path.name}: [course] is missing {missing}")

    entries = raw.get("topic") or []
    if not entries:
        raise CanonError(f"{path.name}: no [[topic]] entries")

    topics: list[Topic] = []
    for index, entry in enumerate(entries, 1):
        absent = [f for f in REQUIRED_TOPIC_FIELDS if not entry.get(f)]
        if absent:
            raise CanonError(f"{path.name}: topic {index} is missing {absent}")
        topics.append(Topic(ref=entry["ref"], unit=entry["unit"],
                            name=entry["name"]))

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
        number=course["number"],
        title=course["title"],
        url=course["url"],
        verified=str(course["verified"]),
        topics=tuple(topics),
        prerequisites=course.get("prerequisites", ""),
        textbook=course.get("textbook", ""),
        excluded=course.get("excluded", ""),
    )


def load_all(directory: str | Path) -> list[Canon]:
    found = sorted(Path(directory).glob("*.toml"))
    if not found:
        raise CanonError(f"no canon files in {directory}")
    canons = [load(path) for path in found]

    # Within a canon, a filename collision is an error (see `load`). Across
    # canons it is subtler and worth catching here: seeding puts each course in
    # its own directory, so nothing is overwritten, but Obsidian resolves
    # wikilinks by filename across the entire vault. A duplicate makes
    # `[[Central Limit Theorem]]` AMBIGUOUS rather than broken, which is worse
    # -- it silently resolves to whichever note Obsidian picks.
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for canon in canons:
        for topic in canon.topics:
            other = seen.setdefault(topic.filename, canon.number)
            if other != canon.number:
                clashes.append(f"{topic.filename} ({other} and {canon.number})")
    if clashes:
        raise CanonError(
            "topics in different courses share a filename, which makes "
            f"wikilinks ambiguous: {sorted(clashes)}"
        )
    return canons


def note_body(canon: Canon, topic: Topic) -> str:
    """A seeded topic note: canon in front matter, judgment left blank.

    `relevance: unset` is the queryable hole — a canonical topic neither party
    has judged yet. It is the default precisely so that the holes exist as
    data on day one rather than being discovered by their absence.
    """
    alias = ""
    if _safe_name(topic.name) != topic.name:
        alias = f'aliases: ["{topic.name}"]\n'
    return f"""---
type: curriculum-topic
curriculum: {canon.course_id}
course: "{canon.number} {canon.title}"
unit: "{topic.unit}"
topic: "{topic.name}"
ocw_ref: "{canon.course_id}/{topic.ref}"
source: canon
{alias}relevance: unset          # unset | cover | skip | deferred
relevance_decided_by: ""  # user | agent | joint
relevance_note: ""
first_taught: ""
outcomes: []
---

# {topic.name}

*{canon.number} — {topic.unit}*

Canonical topic, imported from [{canon.number}]({canon.url}). Nothing below
this line is written by the import.

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

    def __str__(self) -> str:
        return (f"{len(self.created)} created, "
                f"{len(self.existing)} already present")


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

    def __str__(self) -> str:
        counts = ", ".join(f"{k}={len(v)}" for k, v in sorted(self.judged.items()))
        return (f"{len(self.holes)} holes, {len(self.orphans)} orphans, "
                f"{len(self.unjudged)} unjudged" + (f" [{counts}]" if counts else ""))


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

    report.orphans = sorted(present - set(expected))
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
            print(f"{canon.number:<10} {canon.title}")
            units = len(canon.units)
            print(f"  {len(canon.topics)} topics, {units} "
                  f"{'unit' if units == 1 else 'units'}, "
                  f"verified {canon.verified}")
            if canon.excluded:
                print(f"  excluded: {canon.excluded}")
        return 0

    if action == "seed":
        for canon in canons:
            print(f"{canon.number}: {seed(canon, vault)}")
        return 0

    if action == "audit":
        worst = 0
        for canon in canons:
            report = audit(canon, vault)
            print(f"{canon.number}: {report}")
            for ref in report.holes:
                print(f"  HOLE    {ref} — no note; run seed")
            for name in report.orphans:
                print(f"  ORPHAN  {name} — not in the canon")
            if report.holes or report.orphans:
                worst = 1
        return worst

    print(f"unknown action {action!r}; use seed, audit or list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
