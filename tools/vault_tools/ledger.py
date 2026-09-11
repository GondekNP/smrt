"""The concept ledger: what you have demonstrated, across sessions.

The other half of the vault's memory. `curriculum.py` holds what there is to
demonstrate; this holds what you have, and it exists because a single session
cannot answer the question that matters — "do they actually know this, or have
they now described it correctly three times in a row without ever using the
word for it?"

## The tiered vocabulary rule

Credit understanding the first time. Tighten as a concept keeps coming back
undernamed. Three tiers, driven by a **streak** rather than a lifetime total,
because the rule is about failing to internalize *continually*: naming the
concept once resets the pressure.

| Streak of unnamed credits | Tier | Behaviour |
|---|---|---|
| `< LENIENT_UNTIL` | `lenient` | Credit it. No friction, nothing said |
| `< GATE_AT` | `advisory` | Credit it, and the agent is **told** to supply the term. It may say so; it may not silently waive anything |
| `>= GATE_AT` | `gated` | Naming is required. Grading an unnamed credit is **refused** |

A gate is lifted only by a human editing `gate: off` in the concept's note.

## What this can and cannot enforce

The refusal is real: `grade_explain` will not accept a tier-3 concept as
credited-but-unnamed, so an agreeable agent cannot talk its way past the bar
the way it could past a rule written in a prompt.

It is not airtight, and the honest statement is worth making. The agent can
write to `/vault`, so it could in principle edit a concept note and set
`gate: off` itself. What stops that being silent is that the vault is a git
repository: the edit is a tracked change to a file the agent has no business
touching. Same shape as everywhere else in this project — the mount is the
boundary, and the gate is discipline with an audit trail, not a sandbox.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Tunable, and expected to be tuned once there are real numbers. Defaults from
# the design conversation: lenient for the first two encounters, advisory for
# the next two, gated after that.
LENIENT_UNTIL = int(os.environ.get("SMRT_VOCAB_LENIENT_UNTIL", "2"))
GATE_AT = int(os.environ.get("SMRT_VOCAB_GATE_AT", "4"))

TIERS = ("lenient", "advisory", "gated")

_UNSAFE = re.compile(r'[:/\\|#^\[\]?*"<>]')
_FIELD = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*?)\s*$")


def _safe_name(name: str) -> str:
    cleaned = _UNSAFE.sub("-", name)
    return re.sub(r"\s+", " ", cleaned).strip(" .-")


@dataclass
class Concept:
    """One concept's standing. `unnamed_streak` drives the tier; the totals are
    for the record and for looking back at how a term was actually learned."""

    name: str
    unnamed_streak: int = 0
    credited_unnamed: int = 0
    named: int = 0
    gate: str = "auto"
    first_seen: str = ""
    last_seen: str = ""

    @property
    def tier(self) -> str:
        if self.gate == "off":
            return "lenient"
        if self.unnamed_streak >= GATE_AT:
            return "gated"
        if self.unnamed_streak >= LENIENT_UNTIL:
            return "advisory"
        return "lenient"

    @property
    def naming_required(self) -> bool:
        return self.tier == "gated"

    def status(self) -> dict:
        """What the posing call hands back, so a rubric can be written knowing
        which terms are now required."""
        return {
            "concept": self.name,
            "tier": self.tier,
            "unnamed_streak": self.unnamed_streak,
            "naming_required": self.naming_required,
            "gate": self.gate,
            "advice": _ADVICE[self.tier].format(name=self.name),
        }


_ADVICE = {
    "lenient": "New or recently named. Credit a correct description even if "
               "{name!s} is not the word used.",
    "advisory": "Described correctly without naming it before. Credit it "
                "again, but supply the term '{name!s}' explicitly and say it "
                "will be expected next time. Do not waive anything silently.",
    "gated": "The term '{name!s}' has gone unnamed too many times in a row. "
             "Naming it is now required: an answer that describes it without "
             "the word does not earn the rubric item. This cannot be waived "
             "from here — only by editing `gate: off` in the concept's note.",
}


def concept_path(name: str, vault_root: str | Path) -> Path:
    return Path(vault_root) / "concepts" / f"{_safe_name(name)}.md"


def _template(concept: Concept) -> str:
    alias = ""
    if _safe_name(concept.name) != concept.name:
        alias = f'aliases: ["{concept.name}"]\n'
    return f"""---
type: concept
concept: "{concept.name}"
unnamed_streak: {concept.unnamed_streak}
credited_unnamed: {concept.credited_unnamed}
named: {concept.named}
gate: {concept.gate}
first_seen: {concept.first_seen}
last_seen: {concept.last_seen}
{alias}---

# {concept.name}

<!--
Counters above are written by the tool. `gate: off` is the one field that is
yours: setting it lifts the naming requirement permanently.
-->

## Notes
"""


def load(name: str, vault_root: str | Path) -> Concept:
    """Read a concept's standing, or return a fresh one. Never raises on a
    missing or malformed note: an unreadable ledger entry should cost a
    tightened bar, not a lesson."""
    path = concept_path(name, vault_root)
    concept = Concept(name=name)
    if not path.exists():
        return concept
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return concept

    for line in text.splitlines():
        if line.strip() == "---" and concept.first_seen:
            break
        match = _FIELD.match(line)
        if not match:
            continue
        key, value = match.group("key"), match.group("value")
        value = value.split("#")[0].strip().strip('"')
        if key in ("unnamed_streak", "credited_unnamed", "named"):
            try:
                setattr(concept, key, int(value))
            except ValueError:
                pass
        elif key == "gate" and value in ("auto", "off"):
            concept.gate = value
        elif key in ("first_seen", "last_seen"):
            setattr(concept, key, value)
    return concept


def save(concept: Concept, vault_root: str | Path) -> Path:
    """Write the counters back, preserving everything else in the note.

    Rewrites only the fields this module owns. A note may carry the learner's
    own prose, their own front matter keys, and `gate: off` — none of which are
    this function's to touch.
    """
    path = concept_path(concept.name, vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    concept.last_seen = today
    if not concept.first_seen:
        concept.first_seen = today

    if not path.exists():
        path.write_text(_template(concept), encoding="utf-8")
        return path

    owned = {
        "unnamed_streak": str(concept.unnamed_streak),
        "credited_unnamed": str(concept.credited_unnamed),
        "named": str(concept.named),
        "last_seen": concept.last_seen,
    }
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    seen_keys: set[str] = set()
    in_front_matter = False
    for index, line in enumerate(lines):
        if line.strip() == "---":
            in_front_matter = index == 0 or not in_front_matter
            out.append(line)
            continue
        match = _FIELD.match(line) if in_front_matter else None
        if match and match.group("key") in owned:
            key = match.group("key")
            seen_keys.add(key)
            out.append(f"{key}: {owned[key]}")
            continue
        out.append(line)

    missing = [f"{k}: {v}" for k, v in owned.items() if k not in seen_keys]
    if missing:
        # Front matter did not carry a field we own -- insert before its close.
        for position, line in enumerate(out):
            if position and line.strip() == "---":
                out[position:position] = missing
                break
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def record_named(name: str, vault_root: str | Path) -> Concept:
    """The learner used the term. Resets the streak — the rule is about
    failing to internalize *continually*, so naming it relieves the pressure.
    """
    concept = load(name, vault_root)
    concept.named += 1
    concept.unnamed_streak = 0
    save(concept, vault_root)
    return concept


def record_unnamed(name: str, vault_root: str | Path) -> Concept:
    """Credited for understanding without using the term."""
    concept = load(name, vault_root)
    concept.credited_unnamed += 1
    concept.unnamed_streak += 1
    save(concept, vault_root)
    return concept


def status(names: list[str], vault_root: str | Path) -> list[dict]:
    return [load(name, vault_root).status() for name in names]


def gated(names: list[str], vault_root: str | Path) -> list[str]:
    """Which of these currently require the term. Checked BEFORE anything is
    recorded, so a refusal leaves the counters untouched."""
    return [n for n in names if load(n, vault_root).naming_required]


def main(argv: list[str] | None = None) -> int:
    """`python3 -m vault_tools.ledger [list|show NAME] [vault]`"""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    action = args.pop(0) if args else "list"
    vault = Path(args.pop(0) if args else os.environ.get("VAULT_ROOT", "/vault"))

    directory = vault / "concepts"
    if action == "list":
        notes = sorted(directory.glob("*.md")) if directory.is_dir() else []
        if not notes:
            print(f"no concepts recorded in {directory}")
            return 0
        print(f"{'concept':<40} {'tier':<9} {'streak':>6} {'named':>6}  gate")
        for note in notes:
            concept = load(note.stem, vault)
            print(f"{concept.name[:40]:<40} {concept.tier:<9} "
                  f"{concept.unnamed_streak:>6} {concept.named:>6}  "
                  f"{concept.gate}")
        print(f"\nlenient below {LENIENT_UNTIL} unnamed in a row, "
              f"gated at {GATE_AT}")
        return 0

    if action == "show" and args is not None:
        print(load(args[0] if args else "", vault))
        return 0

    print(f"unknown action {action!r}; use list or show", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
