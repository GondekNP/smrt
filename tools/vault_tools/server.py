"""Vault tool server — `quiz` and `explain` are real; the other five are not.

The tool signatures here are the thing worth reviewing: this server is the
only component shared between L0 (learning) and L1 (design), so these
signatures are inherited by the design layer.

Built on the official MCP Python SDK (`mcp` 2.x, `MCPServer`) — see
`docs/OPEN.md` decision 8 for why that one, and note that 2.0 renamed
`FastMCP` to `MCPServer`, so v1 examples do not apply.

Only the implemented tools are registered. A tool that is visible and always
raises is worse than one that is absent: the model spends a turn discovering
it is broken, and a stub in `tools/list` reads as a capability. The unregistered
five stay as plain module-level functions so `scripts/check.sh` can still see
the shape of the surface.

**Refusals are `ToolError`, not `ValueError`.** The SDK reports the text of an
anticipated failure (`ToolError`) to the client and withholds the text of
anything else, treating it as a crash whose internals should not leak. That is
the right default, and it matters here because in these tools the refusal
*message* is the mechanism — "grade against the rubric as committed, quoting
items verbatim" is what makes a refusal actionable. Raised as a `ValueError`,
the model sees only "Error executing tool grade_explain". Found over the wire;
the direct-call tests would never have caught it.

Design notes that the signatures encode
---------------------------------------

**A tool call cannot ask the learner anything.** MCP is request/response, and
the one mechanism that would change that — `elicitation` — is unreachable here:
Toad 0.6.20 implements no handler for it, and `session/request_permission`, the
only inbound method that asks the user something, offers a choice among options
and cannot carry free text. So these tools are **notaries and recorders**. The
question is asked in the conversation; the tool makes the commitment verifiable
and the outcome structured. See `docs/status.md`, "The signature hole".

**Every question therefore costs two calls.** One to pose, which commits the
answer key or the rubric; one to grade, which is checked against what was
committed. Nothing forces the agent to make the second call — but the first
call returns a `question_id`, and an unanswered id is a visible loose end.

**The grade is split between what can be computed and what must be judged.**
`answer_quiz` computes `pick_correct` itself, and `grade_explain` verifies that
the rubric being graded against is the one committed. Those two checks are the
whole point: the documented failure mode of LLM grading is sycophancy, and a
sycophantic agent can no longer report a wrong pick as right, or quietly grade
against a rubric it softened after seeing the answer. What genuinely needs a
model — was the justification sound, which rubric items did the prose hit — is
still the agent's judgment, and is recorded as such.

**The note is the submission.** `derive` does not take an image path. It writes
a note into the vault, and you attach your photo into that note the way you
attach anything in Obsidian. See `docs/OPEN.md` decision 7.

**Nothing blocks.** `derive` writes the note and returns immediately; the agent
asks you conversationally, and reads the submission only once you say you are
done.

**The rubric is committed by hash, not in plaintext.** Writing the expected
steps into a note you are about to look at would spoil the exercise, but
writing them only afterwards would make the pre-commitment unverifiable. So
`derive` records `rubric_sha256` up front and `record_grade` writes the full
rubric afterwards. You can then check the hash and know the bar was not moved
after your answer was seen.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "/vault"))
SUBJECT_ROOT = Path(os.environ.get("SUBJECT_ROOT", "/subject"))

# Instructions travel to the client in `initialize` and are the one place to
# state discipline that is not attached to a single tool.
srv = MCPServer(
    "vault-tools",
    title="SMRT vault tools",
    instructions=(
        "Tools for a teaching session over an Obsidian vault. Questions are "
        "asked in the conversation, not by these tools: each question type is "
        "posed with one call and graded with a second, and the grading call is "
        "checked against what the posing call committed to.\n\n"
        "Never reveal a quiz's correct option or an explain question's rubric "
        "before the learner has answered. Pose the question from the payload "
        "the posing call returns, which deliberately withholds the key.\n\n"
        "If a question has a right answer it is a quiz or an explain, never an "
        "ask."
    ),
)


# --------------------------------------------------------------------------
# Commitments
# --------------------------------------------------------------------------
# Posed questions live in memory for the life of the server process, which is
# the life of the session -- the agent spawns one server per session. That is
# deliberately not durable: an in-process dict is what makes `pick_correct`
# uncheatable, because the answer key is held somewhere the agent cannot
# rewrite between posing and grading. Durable records are a separate job, and
# belong in the vault via `md_log` and `record_grade` once those are real.

def _rubric_sha256(rubric: list[str]) -> str:
    """Hash a rubric so the bar can be shown to have been fixed in advance.

    One item per line, so the hash is reproducible by hand with `sha256sum`.
    A learner who cannot verify the hash themselves is taking the
    pre-commitment on faith, which defeats it.
    """
    return hashlib.sha256("\n".join(rubric).encode("utf-8")).hexdigest()


@dataclass
class _PosedQuiz:
    prompt: str
    option_ids: list[str]
    correct_option_id: str
    explanation: str
    answered: bool = False


@dataclass
class _PosedExplain:
    question: str
    rubric: list[str]
    rubric_sha256: str
    graded: bool = False


_QUIZZES: dict[str, _PosedQuiz] = {}
_EXPLAINS: dict[str, _PosedExplain] = {}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3)}"


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
class QuizPosed:
    """What may be shown to the learner, and nothing else.

    The correct option and the explanation are held back deliberately. This
    payload is what the agent reads the question from, and tool results are
    rendered in the client's own UI — so anything returned here should be
    assumed visible to the learner immediately.
    """

    question_id: str
    prompt: str
    options: list[QuizOption]
    hint: str | None
    warnings: list[str]


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
    next_step: str
    explanation: str


# The four cells of the table in `docs/teaching-loop.md`, as data rather than
# as branches, so the diagnosis cannot drift from the documented one.
_OUTCOMES: dict[tuple[bool, bool], tuple[str, str]] = {
    (True, True): (
        "solid",
        "Advance.",
    ),
    (True, False): (
        "lucky_guess",
        "Right for the wrong reasons, and invisible under plain multiple "
        "choice — this is the most valuable signal available. Probe the same "
        "idea from another angle before advancing.",
    ),
    (False, True): (
        "misconception",
        "A specific, nameable misconception rather than an absence. Name it, "
        "then probe its extent — misconceptions generalize, so it is likely "
        "affecting neighbouring nodes too.",
    ),
    (False, False): (
        "gap",
        "A genuine gap, not a misconception. Back up a level rather than "
        "re-explaining this one.",
    ),
}

# Rule 1 of distractor construction: every option is a bare claim. These are
# the words that smuggle a justification into one.
_JUSTIFYING = re.compile(
    r"\b(because|since|therefore|thus|hence|as a result|which means|"
    r"so that|due to|owing to)\b",
    re.IGNORECASE,
)


def _lint_options(options: list[QuizOption], correct_option_id: str) -> list[str]:
    """Check the documented tells mechanically, and warn rather than refuse.

    These are the failure modes `docs/teaching-loop.md` names, and they are
    exactly the kind a model does not notice in its own output. Warnings, not
    errors, for two reasons: a false positive must never cost a lesson, and
    the fix for a real one is "regenerate, don't patch", which is a judgment
    the agent has to make.
    """
    warnings: list[str] = []

    for option in options:
        found = _JUSTIFYING.search(option.text)
        if found:
            warnings.append(
                f"option {option.id!r} contains {found.group(0)!r}, which "
                "reads as justification — every option must be a bare claim, "
                "with all reasoning in `explanation`"
            )

    correct = next(o for o in options if o.id == correct_option_id)
    distractors = [o for o in options if o.id != correct_option_id]
    if distractors:
        mean = sum(len(o.text) for o in distractors) / len(distractors)
        if mean and len(correct.text) > 1.5 * mean:
            warnings.append(
                f"the correct option is {len(correct.text) / mean:.1f}x the "
                "mean distractor length — the number one giveaway. Regenerate "
                "rather than trimming"
            )

    bolded = [o.id for o in options if "**" in o.text]
    if bolded and len(bolded) != len(options):
        warnings.append(
            f"asymmetric bolding: {bolded} bold where others are not. Bold "
            "the parallel term in every option or in none"
        )

    return warnings


@srv.tool()
def quiz(
    prompt: str,
    options: list[QuizOption],
    correct_option_id: str,
    explanation: str,
    hint: str | None = None,
) -> QuizPosed:
    """Pose multiple choice requiring a pick AND a one-line justification.

    Returns only what the learner may see, and commits the answer key. Grade
    the reply with `answer_quiz`, which computes whether the pick was right.

    Distractor construction — write the correct claim first, then mutate it
    into each distractor by stating what someone holding a specific
    misconception would claim, in the same skeleton, grain size and register.
    Parallelism then falls out by construction instead of being audited
    afterwards.

    If you can tell which option is right while cold on the material,
    regenerate rather than patch. Some of the tells are checked mechanically
    and come back in `warnings`; an empty `warnings` is not a certificate,
    only the absence of the three cheapest signals.

    Used heavily in the probe phase: twelve cheap signals beat twelve essays.
    Probing applies to every subject, code included — see OPEN.md decision 6.
    """
    if len(options) < 2:
        raise ToolError("a quiz needs at least two options")

    ids = [o.id for o in options]
    if len(ids) != len(set(ids)):
        raise ToolError(f"duplicate option ids: {ids}")
    if correct_option_id not in ids:
        raise ToolError(
            f"correct_option_id {correct_option_id!r} is not one of {ids}"
        )
    if not explanation.strip():
        raise ToolError(
            "explanation is required: it carries the reasoning that the "
            "options are forbidden to contain"
        )

    question_id = _new_id("quiz")
    _QUIZZES[question_id] = _PosedQuiz(
        prompt=prompt,
        option_ids=ids,
        correct_option_id=correct_option_id,
        explanation=explanation,
    )
    return QuizPosed(
        question_id=question_id,
        prompt=prompt,
        options=options,
        hint=hint,
        warnings=_lint_options(options, correct_option_id),
    )


@srv.tool()
def answer_quiz(
    question_id: str,
    pick: str,
    reason: str,
    reason_correct: bool,
) -> QuizResult:
    """Grade a quiz answer. `pick_correct` is computed here, not accepted.

    Pass the learner's answer exactly as given. `pick` is the option id they
    chose; `reason` is their one-line justification verbatim, not your summary
    of it.

    `reason_correct` is your judgment, and it is the only part of the grade
    this tool takes on trust. Read it as **sound**, not as identical to your
    own explanation: for a wrong pick it means the reasoning was coherent — a
    position someone could actually hold — rather than noise. That distinction
    is what separates a misconception from a gap, and they call for opposite
    responses.

    A question can only be answered once. Re-answering would let a learner
    converge on the right box by elimination, which destroys the signal the
    question was posed to collect; probe with a new question instead.

    Returns the diagnosis, what to do about it, and the explanation — which is
    released only now.
    """
    posed = _QUIZZES.get(question_id)
    if posed is None:
        known = ", ".join(sorted(_QUIZZES)) or "none"
        raise ToolError(
            f"unknown question_id {question_id!r} (posed this session: {known})"
        )
    if posed.answered:
        raise ToolError(
            f"{question_id!r} has already been answered — pose a new question "
            "rather than re-answering this one"
        )
    if pick not in posed.option_ids:
        raise ToolError(
            f"pick {pick!r} is not one of {posed.option_ids}"
        )
    if not reason.strip():
        raise ToolError(
            "reason is required: the justification is half the signal, and a "
            "pick without one is the plain multiple choice this tool exists "
            "to avoid"
        )

    posed.answered = True
    pick_correct = pick == posed.correct_option_id
    diagnosis, next_step = _OUTCOMES[(pick_correct, reason_correct)]
    return QuizResult(
        pick_correct=pick_correct,
        reason_correct=reason_correct,
        diagnosis=diagnosis,
        next_step=next_step,
        explanation=posed.explanation,
    )


@dataclass
class ExplainPosed:
    """The question, and proof that the bar was set before it was asked."""

    question_id: str
    question: str
    rubric_sha256: str
    rubric_items: int


@dataclass
class ExplainResult:
    hit: list[str]
    missed: list[str]
    passed: bool
    rubric: list[str]
    rubric_sha256: str
    next_step: str


@srv.tool()
def explain(question: str, rubric: list[str]) -> ExplainPosed:
    """Pose a free-response question, committing the rubric first.

    Returns the question and the rubric's hash — never the rubric itself, so
    the payload is safe to show. Grade the answer with `grade_explain`.

    The rubric MUST be the three things a correct explanation has to contain,
    written before the question is shown. This is not ceremony: the default
    failure of LLM free-response grading is sycophancy, and it will call a
    hand-wavy answer excellent. A rubric written before it sees the answer is
    the fix, and it restores the diagnostic property that multiple choice gets
    by construction.

    `grade_explain` will only accept a verdict that accounts for exactly these
    items, so the bar cannot be softened once the answer is in view.

    This is the gate for advancing. Passing means you can teach it.
    """
    if not rubric:
        raise ToolError("a rubric is required — that is the whole mechanism")
    if len(rubric) != len(set(rubric)):
        raise ToolError(f"duplicate rubric items: {rubric}")
    if any(not item.strip() for item in rubric):
        raise ToolError("rubric items must not be blank")

    question_id = _new_id("explain")
    digest = _rubric_sha256(rubric)
    _EXPLAINS[question_id] = _PosedExplain(
        question=question,
        rubric=list(rubric),
        rubric_sha256=digest,
    )
    return ExplainPosed(
        question_id=question_id,
        question=question,
        rubric_sha256=digest,
        rubric_items=len(rubric),
    )


@srv.tool()
def grade_explain(
    question_id: str,
    answer: str,
    hit: list[str],
    missed: list[str],
    comment: str = "",
) -> ExplainResult:
    """Grade a free response against the rubric that was committed.

    `hit` and `missed` must together account for **exactly** the committed
    rubric — every item in one list or the other, none invented, none dropped.
    Anything else is refused, naming what went wrong. That check is what makes
    the pre-commitment real: without it, an agent looking at a weak answer can
    grade against a rubric it has quietly softened, and the hash would still
    match the rubric it published.

    Quote items verbatim from the rubric. Pass the learner's `answer` as given.

    Names what was missed rather than scoring it, because "you did not say why
    the variance term matters" is actionable and "6/10" is not.
    """
    posed = _EXPLAINS.get(question_id)
    if posed is None:
        known = ", ".join(sorted(_EXPLAINS)) or "none"
        raise ToolError(
            f"unknown question_id {question_id!r} (posed this session: {known})"
        )
    if posed.graded:
        raise ToolError(f"{question_id!r} has already been graded")
    if not answer.strip():
        raise ToolError("answer is required")

    committed = set(posed.rubric)
    given = list(hit) + list(missed)
    overlap = set(hit) & set(missed)
    if overlap:
        raise ToolError(
            f"items in both hit and missed: {sorted(overlap)}"
        )
    invented = [item for item in given if item not in committed]
    if invented:
        raise ToolError(
            f"not in the committed rubric: {invented}. Grade against the "
            "rubric as committed, quoting items verbatim"
        )
    unaccounted = sorted(committed - set(given))
    if unaccounted:
        raise ToolError(
            f"committed rubric items accounted for in neither hit nor "
            f"missed: {unaccounted}"
        )

    posed.graded = True
    missed_list = list(missed)
    return ExplainResult(
        hit=list(hit),
        missed=missed_list,
        passed=not missed_list,
        rubric=list(posed.rubric),
        rubric_sha256=posed.rubric_sha256,
        next_step=(
            "Passed — this node is teachable, advance."
            if not missed_list
            else "Not yet. Teach the missed items specifically rather than "
                 "re-explaining the whole node, then re-pose a new question."
        ),
    )


# --------------------------------------------------------------------------
# Not yet implemented, and deliberately not registered
# --------------------------------------------------------------------------
# Left as plain functions: the signatures are still the thing under review,
# and a stub in `tools/list` would read to the model as a capability.
#
# `ask` is the interesting one. It looks trivial -- a question with no right
# answer -- but it was specified to RETURN the learner's choice, and a tool
# call cannot ask anyone anything here. As a recorder it may not need to exist
# at all: an agent asking a genuine question in conversation is just talking.
# That is an item 6 question, not an oversight.

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

IMPLEMENTED = ("quiz", "answer_quiz", "explain", "grade_explain")
PLACEHOLDERS = ("derive", "ask", "submit_artifact", "record_grade", "md_log")


def main() -> None:
    """Serve MCP over stdio.

    Nothing but protocol may reach stdout, so there is no diagnostic printing
    here — `python3 -m vault_tools.server --describe` is the human-readable
    view, and `scripts/check.sh` uses it.
    """
    import sys

    if "--describe" in sys.argv[1:]:
        print("vault-tools")
        print(f"  VAULT_ROOT   = {VAULT_ROOT} (exists: {VAULT_ROOT.exists()})")
        print(f"  SUBJECT_ROOT = {SUBJECT_ROOT} (exists: {SUBJECT_ROOT.exists()})")
        print("  registered:")
        for name in IMPLEMENTED:
            print(f"    - {name}")
        print("  not implemented, not registered:")
        for name in PLACEHOLDERS:
            print(f"    - {name}")
        return

    srv.run("stdio")


if __name__ == "__main__":
    main()
