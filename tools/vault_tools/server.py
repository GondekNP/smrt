"""Vault tool server — PLACEHOLDER.

Defines the tool surface so the shape can be argued about before anything is
implemented. Every handler returns a stub.

The tool signatures here are the thing worth reviewing: this server is the
only component shared between L0 (learning) and L1 (design), so these
signatures are inherited by the design layer.

TODO: pick an MCP SDK and make this real.

Design notes that the signatures encode
---------------------------------------

**The note is the submission.** `derive` does not take an image path. It writes
a note into the vault, and you attach your photo into that note the way you
attach anything in Obsidian. The note then holds the task, the attempt, and the
grading together, in the graph, with backlinks and git history. See
`docs/OPEN.md` decision 7.

**Nothing blocks.** MCP is request/response, so a `derive` that waited for a
photo would wedge the session. `derive` writes the note and returns
immediately; the agent asks you conversationally, and reads the submission only
once you say you are done.

**The rubric is committed by hash, not in plaintext.** Writing the expected
steps into a note you are about to look at would spoil the exercise, but
writing them only afterwards would make the pre-commitment unverifiable. So
`derive` records `rubric_sha256` up front and `record_grade` writes the full
rubric afterwards. You can then check the hash and know the bar was not moved
after your answer was seen — which is the whole point of pre-commitment, since
the default failure of LLM grading is sycophancy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "/vault"))
SUBJECT_ROOT = Path(os.environ.get("SUBJECT_ROOT", "/subject"))


# --------------------------------------------------------------------------
# Question types
# --------------------------------------------------------------------------

@dataclass
class QuizOption:
    """One multiple-choice option.

    Must be a BARE CLAIM. No justification, no "because", no reasoning of any
    kind — the single biggest tell is the correct option carrying its own
    rationale while distractors are bare, making it longer and more specific.
    All reasoning belongs in `explanation`, shown only after answering.
    """

    id: str
    text: str


@dataclass
class QuizResult:
    """Pick and reason are graded SEPARATELY. That separation is the point:
    it distinguishes a correct answer from a correct answer held for the
    right reason, which plain multiple choice cannot see at all.

    Four outcomes:
      right / right      -> solid, advance
      right / wrong      -> lucky guess. the most valuable signal here.
      wrong / coherent   -> a specific, nameable misconception
      wrong / incoherent -> genuine gap, back up a level
    """

    pick_correct: bool
    reason_correct: bool
    diagnosis: str


def quiz(
    prompt: str,
    options: list[QuizOption],
    correct_option_id: str,
    explanation: str,
    hint: str | None = None,
) -> QuizResult:
    """Multiple choice requiring a pick AND a one-line justification.

    Distractor construction — write the correct claim first, then mutate it
    into each distractor by stating what someone holding a specific
    misconception would claim, in the same skeleton, grain size and register.
    Parallelism then falls out by construction instead of being audited
    afterwards.

    If you can tell which option is right while cold on the material,
    regenerate rather than patch.

    Used heavily in the probe phase: twelve cheap signals beat twelve essays.
    Probing applies to every subject, code included — see OPEN.md decision 6.
    """
    raise NotImplementedError("placeholder")


def explain(question: str, rubric: list[str]) -> dict:
    """Free response graded against a rubric.

    `rubric` MUST be committed before the question is shown to the learner.
    This is not ceremony: the default failure of LLM free-response grading is
    sycophancy, and it will call a hand-wavy answer excellent. A rubric
    written before it sees the answer is the fix, and it restores the
    diagnostic property that multiple choice gets by construction.

    Returns which rubric items were hit and which were missed — named
    specifically, not scored.

    This is the gate for advancing. Passing means you can teach it.
    """
    raise NotImplementedError("placeholder")


@dataclass
class DeriveNote:
    """Where a derivation lives. Returned by `derive`, consumed by
    `submit_artifact` and `record_grade`."""

    note_path: Path
    task_id: str
    rubric_sha256: str


def derive(
    task: str,
    rubric: list[str],
    concept: str,
    note_path: str | None = None,
) -> DeriveNote:
    """Ask for a proof or a diagram, submitted by attaching an image to a note.

    Writes a note into the vault and RETURNS IMMEDIATELY — it does not wait for
    the submission. The agent tells the learner where the note is, the learner
    attaches a photo in Obsidian (desktop or mobile), says so, and only then
    does the agent call `submit_artifact`.

    Graded on the steps, not the answer.

    `concept` is a wikilink target (e.g. "[[Fisher information]]") so the note
    joins the graph rather than sitting orphaned. `rubric` is the list of steps
    a correct derivation must contain; it is stored as a hash now and written
    out in full by `record_grade`, so the bar is verifiably fixed in advance
    without spoiling the exercise.

    Stats: derive the Hessian, Fisher information, a likelihood ratio.
    Design: draw the module dependency DAG from memory — and that one has a
    deterministic answer key, because the import graph is machine-derivable
    at L1. Fuzzy submission, hard key.

    See `vault-template/templates/derive.md` for the note schema.
    """
    raise NotImplementedError("placeholder")


def ask(question: str, options: list[str] | None = None) -> str:
    """Genuine fork. No right answer.

    Preferences, direction, what you want next.

    NEVER use this for anything gradable. If the question has a right answer
    it is a quiz. Misusing `ask` for gradable content is precisely what makes
    agent check-ins feel like hand-holding.
    """
    raise NotImplementedError("placeholder")


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------

def submit_artifact(source: str) -> dict:
    """Read a submission and return it as image content blocks.

    `source` is either:

      - a NOTE path — the normal case. Resolves every `![[...]]` embed under
        the note's `## Attempt` heading and returns them in document order,
        along with any prose the learner wrote alongside. This is what makes
        the note the durable record: the image is already where Obsidian put
        it, and the note already links to it.
      - an IMAGE path — the escape hatch, for a submission with no note.

    Distinguished by extension. Paths are resolved relative to VAULT_ROOT and
    MUST stay inside it.
    """
    resolved = (VAULT_ROOT / source).resolve()
    if not resolved.is_relative_to(VAULT_ROOT.resolve()):
        raise ValueError(f"refusing to read outside the vault: {source}")
    raise NotImplementedError("placeholder")


def record_grade(
    note_path: str,
    rubric: list[str],
    hit: list[str],
    missed: list[str],
    comment: str,
) -> None:
    """Write grading back into the derivation's own note.

    Appends a `## Grading` section as Obsidian callouts (`> [!success]` /
    `> [!warning]`, which render natively) and updates the note's front matter:
    `status: graded`, `score`, `graded`, and the full `rubric` whose hash
    `derive` committed earlier.

    Structured front matter rather than prose because that is what makes the
    record queryable — Dataview can then answer "every derivation I got wrong"
    or "everything touching [[Fisher information]]", which is the difference
    between a pile of sessions and a learning record.

    Never hand-edit the section this writes.
    """
    raise NotImplementedError("placeholder")


@dataclass
class LogSession:
    """Link a markdown file in the vault to the session.

    TODO: one file per session, or append to a daily note?
    """

    path: Path
    entries: list[str] = field(default_factory=list)


def md_log(session: LogSession, content: str) -> None:
    """Append to the session log.

    This is the transcript. Derivation notes written by `derive` are a separate,
    more structured record and are not duplicated here — link to them instead.

    Obsidian renders LaTeX and mermaid natively — write both properly rather
    than in ASCII approximation.
    """
    raise NotImplementedError("placeholder")


# --------------------------------------------------------------------------

def main() -> None:
    print("vault-tools: placeholder. See tools/README.md.")
    print(f"  VAULT_ROOT   = {VAULT_ROOT} (exists: {VAULT_ROOT.exists()})")
    print(f"  SUBJECT_ROOT = {SUBJECT_ROOT} (exists: {SUBJECT_ROOT.exists()})")
    print("\nTools defined (all NotImplementedError):")
    for name in (
        "quiz", "explain", "derive", "ask",
        "submit_artifact", "record_grade", "md_log",
    ):
        print(f"  - {name}")


if __name__ == "__main__":
    main()
