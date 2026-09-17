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
import random
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import ledger, trace

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", "/vault"))
SUBJECT_ROOT = Path(os.environ.get("SUBJECT_ROOT", "/subject"))

# A tool server is spawned by the agent and its stdout is protocol, so the log
# file is the only place to see what it was actually asked -- see trace.py.
LOG = trace.Log()

# Instructions travel to the client in `initialize` and are the one place to
# state discipline that is not attached to a single tool.
srv = MCPServer(
    "vault-tools",
    title="SMRT vault tools",
    middleware=[trace.middleware(LOG)],
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


#: Appended to every quiz by the tool rather than left to the agent to
#: remember. "I don't remember" is the most likely answer during a probe --
#: finding the floor is what probing is *for* -- and without somewhere to put
#: it the answer falls outside the tool and the question leaves no record.
DONT_KNOW = "I don't know."


@dataclass
class _PosedQuiz:
    prompt: str
    option_ids: list[str]
    correct_option_id: str
    explanation: str
    dont_know_id: str = ""
    answered: bool = False
    #: Displayed label -> the id the agent authored. Kept so the explanation,
    #: which may refer to the authored ids, stays readable after shuffling.
    authored: dict[str, str] = field(default_factory=dict)


@dataclass
class _PosedExplain:
    question: str
    rubric: list[str]
    rubric_sha256: str
    concepts: list[str]
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


ReasonVerdict = Literal["sound", "coherent", "incoherent"]


@dataclass
class QuizResult:
    """Pick and reason are graded SEPARATELY. That separation is the point:
    it distinguishes a correct answer from a correct answer held for the
    right reason, which plain multiple choice cannot see at all.

    Eight outcomes, over three pick states:
      right   / sound       -> solid, advance
      right   / not sound   -> lucky guess. the most valuable signal here.
      wrong   / sound       -> a slip. the pick and the reasoning disagree.
      wrong   / coherent    -> a specific, nameable misconception
      wrong   / incoherent  -> genuine gap, back up a level
      unknown / sound       -> unsure. they knew it and would not commit.
      unknown / coherent    -> partial. fragments, not assembled.
      unknown / incoherent  -> the floor for this strand. stop probing down.

    `pick_correct` stays a boolean and is False for "I don't know", because
    the pick was not correct. **`pick_state` is the field that distinguishes
    the three**; do not read `pick_correct` as "wrong".

    That warning was here from the start and was not enough. `pick_state` was
    added on 2026-09-17 because the markdown mirror read exactly the boolean
    it says not to, and rendered an honest "I don't know" as "pick wrong" --
    in front of a learner who had just declined to guess, which is the
    behaviour the option exists to encourage. A comment telling a reader not
    to misuse a field does not stop them; publishing the right field does.

    The three `unknown` rows were added on 2026-09-13 after a probe session in
    which five of ten questions were answered "I don't remember" — and none of
    them produced a grading call at all, because there was nowhere to put that
    answer. Eight posed questions left no record of having been asked.

    They are three rows rather than one because those answers differed:
    "I don't remember, really" is a floor, while "I remember only that the
    eigenvectors are the fundamental of the system" is fragments that have not
    been assembled, and the right next move is not the same.

    `slip` was added on 2026-09-11 after the first live session produced it
    immediately. The learner described the correct option accurately and then
    picked a different one; under a boolean verdict the agent had to call that
    reasoning either correct (making it a "misconception") or incorrect
    (making it a "gap"), and it chose the latter — so the mildest error
    available collected the harshest prescription, "back up a level". Its own
    prose said the reasoning was "internally sound" while the grade it
    submitted said otherwise. The table was missing a cell, not the model.
    """

    pick_correct: bool
    pick_state: PickState
    reason_verdict: ReasonVerdict
    diagnosis: str
    next_step: str
    explanation: str


# The cells of the table in `docs/teaching-loop.md`, as data rather than as
# branches, so the diagnosis cannot drift from the documented one.
_LUCKY = (
    "lucky_guess",
    "Right for the wrong reasons, and invisible under plain multiple "
    "choice — this is the most valuable signal available. Probe the same "
    "idea from another angle before advancing.",
)

# Three pick states, not two. A learner who says "I don't remember" has told
# you something specific and useful, and it is neither a right answer nor a
# wrong one -- treating it as wrong would score the probe as a misconception
# and send the lesson looking for a belief that is not there.
#
# Added 2026-09-13, after a probe session where five of ten questions were
# answered "I don't remember" and none of them produced a grading call at all.
# Eight posed questions left no record of having been asked. Borrowed from
# `amosblomqvist/learn`, whose quiz UI carries an "I don't know" option on
# every question.
PickState = Literal["right", "wrong", "unknown"]

_OUTCOMES: dict[tuple[str, str], tuple[str, str]] = {
    ("unknown", "sound"): (
        "unsure",
        "They described it correctly and then declined to commit. The gap is "
        "confidence, not knowledge — say so plainly, and ask them to commit "
        "next time rather than re-teaching what they just demonstrated.",
    ),
    ("unknown", "coherent"): (
        "partial",
        "Fragments that have not been assembled. Probe adjacent rather than "
        "below: the pieces are present and the connection between them is "
        "what is missing.",
    ),
    ("unknown", "incoherent"): (
        "floor",
        "The floor for this strand, which is what probing is for. Stop "
        "probing downward here, record it, and build from underneath. Do not "
        "teach it now — probing measures, and a probe that teaches "
        "contaminates what it is measuring.",
    ),
    ("right", "sound"): (
        "solid",
        "Advance.",
    ),
    # A coherent-but-wrong reason that still selected the right option and a
    # pure guess are both "right for the wrong reasons". Kept as one outcome
    # because the documented table has one, and the verdict is preserved on
    # the result if the distinction ever earns its own cell.
    ("right", "coherent"): _LUCKY,
    ("right", "incoherent"): _LUCKY,
    ("wrong", "sound"): (
        "slip",
        "A slip, not a gap: the reasoning was right and the pick was not. "
        "Show the learner the mismatch between their own words and their "
        "choice — do not re-teach the concept, and do not back up a level. "
        "Then move on, or re-ask this one later to confirm.",
    ),
    ("wrong", "coherent"): (
        "misconception",
        "A specific, nameable misconception rather than an absence. Name it, "
        "then probe its extent — misconceptions generalize, so it is likely "
        "affecting neighbouring nodes too.",
    ),
    ("wrong", "incoherent"): (
        "gap",
        "A genuine gap, not a misconception. Back up a level rather than "
        "re-explaining this one.",
    ),
}

# Rule 1 of distractor construction: every option is a bare claim. These are
# the words that smuggle a justification into one.
#
# Widened on 2026-09-12 after a live probe got through with
#
#   "The curvature (second derivative) of the LL near the MLE — a sharper peak
#    means the LL drops fast as θ moves away, so the data rule out nearby
#    values strongly."
#
# `so` was only matched as "so that", and `means` only as "which means", so
# nothing fired. The learner's complaint was precise: when the option carries
# the reasoning, the one-line justification has nothing to do but restate it,
# and the pick-plus-reason design loses the half that makes it worth two calls.
_JUSTIFYING = re.compile(
    r"\b(because|since|therefore|thus|hence|as a result|which means|"
    r"so that|due to|owing to|so|means|meaning|indicates|indicating|"
    r"implies|implying|i\.e\.|in other words|that is why)\b",
    re.IGNORECASE,
)

# The dominant shape of a leaking option, and the one no keyword caught: a
# bare claim, a dash, and then the explanation of why it is right. Every
# leaking option in the first live probe had exactly this form.
_APPOSITIVE = re.compile(r"\s[—–]\s|\s--\s")
# Below this, a trailing clause is an aside rather than an argument.
_APPOSITIVE_WORDS = 6


# References to an option by LETTER, which the explanation cannot legally make.
#
# The explanation is committed at posing time, before `_shuffle` assigns the
# A-E labels, so any letter in it names the agent's own authoring order. It is
# not a mistake the author can avoid by being careful: at the moment of
# writing, the labels the learner will see do not exist yet.
#
# Measured 2026-09-15. Authored opt1 "identically zero" (the correct one),
# opt2 "linear combination", opt3 "alphabetical", opt4 "no intercept". Shown
# to the learner as A alphabetical, B no intercept, C identically zero, D
# linear combination. The explanation then read "C is wrong: there is no
# alphabetical-drop rule" -- about the option the learner had just correctly
# chosen. Every letter in it was wrong for its reader.
_OPTION_LETTER = re.compile(r"""(?x)
    # "option c", "Option (A)" -- explicit, in either case.
      \b [Oo]ption \s* \(? [A-Ea-e] \)? (?![A-Za-z])
    # "(c) is wrong", "(a) swaps ..."
    | \( \s* [A-Ea-e] \s* \) \s+ (?=\w)
    # A bare letter doing the work of a noun: "B is wrong", "why C cannot be".
    # UPPERCASE only, which is what makes this safe -- the lowercase article
    # "a" is the trap any bare-letter rule walks into, and a capital A is
    # only ever followed by one of these verbs when it names an option.
    | \b [A-E] \s+ (?: is | are | was | were | cannot | can | could | would
                     | should | does | do | fails | holds | describes
                     | confuses | swaps | applies | treats | assumes
                     | ignores | would ) \b
""")


def _by_letter(explanation: str, options: list[QuizOption]) -> list[str]:
    """Option references the learner cannot resolve. Refused, not warned."""
    found = [m.group(0).strip() for m in _OPTION_LETTER.finditer(explanation)]
    # Authored ids too, when they are distinctive enough to match on purpose.
    # A one- or two-character id is a substring of everything.
    for option in options:
        if len(option.id) > 2 and option.id in explanation:
            found.append(option.id)
    return sorted(set(found))


def _leaking(options: list[QuizOption]) -> list[str]:
    """Options carrying their own reasoning. Structural, so it is refused.

    Split out from the warnings on 2026-09-12. The soft tells stay advisory
    because they are heuristics about *style*; this one is not. An option
    that explains itself destroys the thing the two-call design exists for —
    the learner's justification becomes a restatement of the option, and the
    `sound`/`coherent`/`incoherent` judgment measures nothing.

    The live evidence cuts both ways and is worth keeping in mind: when the
    length warning did fire, the agent regenerated without being told to. So
    the mechanism works, and detection was what failed. It is a refusal
    anyway, because "the agent usually notices" is exactly the kind of
    guarantee this design does not accept elsewhere.
    """
    faults: list[str] = []
    for option in options:
        found = _JUSTIFYING.search(option.text)
        if found:
            faults.append(
                f"option {option.id!r} contains {found.group(0)!r}, which "
                "reads as justification"
            )
            continue
        parts = _APPOSITIVE.split(option.text)
        if len(parts) > 1 and len(parts[-1].split()) >= _APPOSITIVE_WORDS:
            faults.append(
                f"option {option.id!r} is a claim followed by a dash and "
                f"{len(parts[-1].split())} more words, which is an "
                "explanation of why it is right"
            )
    return faults


# Shuffling is off when this is set, so tests and any reproducible replay get
# the authored order. Not a general "disable" switch -- a real session should
# always shuffle.
_SHUFFLE = os.environ.get("SMRT_QUIZ_SHUFFLE", "on").lower() != "off"
_RNG = random.Random()


def _shuffle(
    options: list[QuizOption], correct_option_id: str, requested: bool
) -> tuple[list[QuizOption], dict[str, str], str, str]:
    """Reorder the options and relabel them A, B, C… by position.

    Two problems, one fix. A model writing four options has habits about where
    it puts the right one, and a learner reading them has habits about where
    they look; neither is visible in the authored order. Borrowed from
    `amosblomqvist/learn`, which shuffles before display for the same reason.

    Relabelling by position is what makes it usable rather than merely random.
    Reordering while keeping the authored ids would show the learner "C" first,
    which reads as a bug. So the displayed labels are always A, B, C… in the
    order shown, and `authored` keeps the mapping back for the record.

    Returns (what to show, displayed label -> authored id, the correct label,
    the "I don't know" label).
    """
    order = list(options)
    if requested and _SHUFFLE:
        _RNG.shuffle(order)
    labels = [chr(ord("A") + i) for i in range(len(order))]
    shown = [QuizOption(id=label, text=o.text) for label, o in zip(labels, order)]
    authored = {label: o.id for label, o in zip(labels, order)}
    correct_label = next(
        label for label, original in authored.items()
        if original == correct_option_id
    )
    # Always last, never shuffled, and added here rather than asked of the
    # agent: an affordance that depends on being remembered is one that goes
    # missing in the session where it matters most.
    dont_know_label = chr(ord("A") + len(order))
    shown.append(QuizOption(id=dont_know_label, text=DONT_KNOW))
    return shown, authored, correct_label, dont_know_label


def _lint_options(options: list[QuizOption], correct_option_id: str) -> list[str]:
    """Check the documented style tells mechanically, and warn rather than refuse.

    These are the failure modes `docs/teaching-loop.md` names, and they are
    exactly the kind a model does not notice in its own output. Warnings, not
    errors, for two reasons: a false positive must never cost a lesson, and
    the fix for a real one is "regenerate, don't patch", which is a judgment
    the agent has to make. The one structural fault is refused instead; see
    `_leaking`.
    """
    warnings: list[str] = []

    correct = next(o for o in options if o.id == correct_option_id)
    distractors = [o for o in options if o.id != correct_option_id]
    if distractors:
        mean = sum(len(o.text) for o in distractors) / len(distractors)
        longest = len(correct.text) > max(len(o.text) for o in distractors)
        # 1.5x alone missed a real case: 172 chars against a 125-char mean is
        # only 1.38x, and it was still both the longest option and the one
        # carrying the answer. Being the longest is the tell; the ratio only
        # says how loudly.
        if mean and (len(correct.text) > 1.5 * mean
                     or (longest and len(correct.text) > 1.25 * mean)):
            warnings.append(
                f"the correct option is {len(correct.text) / mean:.1f}x the "
                "mean distractor length"
                + (" and the longest of them" if longest else "")
                + " — the number one giveaway. Regenerate rather than trimming"
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
    shuffle: bool = True,
) -> QuizPosed:
    """Pose multiple choice requiring a pick AND a one-line justification.

    Returns only what the learner may see, and commits the answer key. Grade
    the reply with `answer_quiz`, which computes whether the pick was right.

    **Pose the options in the order and with the labels this returns.** They
    are shuffled and relabelled A, B, C… by position, so the authored order is
    not what the learner sees and `correct_option_id` no longer names the
    answer they will pick. Pass `shuffle=False` only when the order carries
    meaning — steps in a sequence, magnitudes to rank.

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

    leaks = _leaking(options)
    if leaks:
        raise ToolError(
            "the options carry their own reasoning, so the learner's "
            "justification can only restate them: " + "; ".join(leaks)
            + ". Every option is a bare claim; all reasoning goes in "
            "`explanation`, which the learner sees only after answering. "
            "Regenerate the whole set rather than trimming the offender — "
            "the others were written to match it."
        )

    # The hint is committed here too, before the shuffle, so it carries the
    # same defect as the explanation: a letter in it names the authoring
    # order. Checked together so the refusal reports both at once rather than
    # sending the agent round twice.
    lettered = _by_letter(explanation, options) + _by_letter(hint or "", options)
    if lettered:
        raise ToolError(
            "the explanation refers to options by letter (" +
            ", ".join(repr(x) for x in lettered) + "), and those letters are "
            "assigned after this call — the options are shuffled before the "
            "learner sees them, so your ordering is not theirs. A letter here "
            "names a different option for the reader, including, in the case "
            "already observed, calling the correct answer wrong. "
            "Name each option by what it says instead: "
            "\"the 'identically zero' option is wrong because ...\". "
            "That also reads better, since the reader does not have to hold a "
            "letter-to-claim mapping in their head."
        )

    shown, authored, correct_label, dont_know = _shuffle(
        options, correct_option_id, shuffle)

    question_id = _new_id("quiz")
    _QUIZZES[question_id] = _PosedQuiz(
        prompt=prompt,
        option_ids=[o.id for o in shown],
        correct_option_id=correct_label,
        dont_know_id=dont_know,
        explanation=explanation,
        authored=authored,
    )
    return QuizPosed(
        question_id=question_id,
        prompt=prompt,
        options=shown,
        hint=hint,
        warnings=_lint_options(options, correct_option_id),
    )


@srv.tool()
def answer_quiz(
    question_id: str,
    pick: str,
    reason: str,
    reason_verdict: ReasonVerdict,
) -> QuizResult:
    """Grade a quiz answer. `pick_correct` is computed here, not accepted.

    Pass the learner's answer exactly as given. `pick` is the option id they
    chose; `reason` is their one-line justification verbatim, not your summary
    of it.

    `reason_verdict` is your judgment, and it is the only part of the grade
    this tool takes on trust. Judge the reasoning ON ITS OWN, not by whether
    it matches the pick — the tool already knows the pick:

      "sound"       the reasoning is correct. Note that this is possible
                    alongside a WRONG pick, and saying so is the point: it
                    means the learner understood and mis-selected, which is a
                    slip and not a gap.
      "coherent"    wrong, but a position someone could actually hold — a
                    nameable belief rather than noise.
      "incoherent"  no usable reasoning: noise, a restatement of the option,
                    or a guess admitted as one.

    Do not reach for "incoherent" because the reasoning disagrees with the
    pick. That combination is exactly what "sound" plus a wrong pick encodes,
    and calling it incoherent prescribes backing up a level for what was a
    mis-click.

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

    if reason_verdict not in ("sound", "coherent", "incoherent"):
        raise ToolError(
            f"reason_verdict must be sound, coherent or incoherent, "
            f"not {reason_verdict!r}"
        )

    posed.answered = True
    if posed.dont_know_id and pick == posed.dont_know_id:
        state: str = "unknown"
    elif pick == posed.correct_option_id:
        state = "right"
    else:
        state = "wrong"
    pick_correct = state == "right"
    diagnosis, next_step = _OUTCOMES[(state, reason_verdict)]
    return QuizResult(
        pick_correct=pick_correct,
        pick_state=state,
        reason_verdict=reason_verdict,
        diagnosis=diagnosis,
        next_step=next_step,
        explanation=posed.explanation,
    )


@dataclass
class ExplainPosed:
    """The question, proof that the bar was set before it was asked, and where
    each named concept currently stands in the vocabulary ledger."""

    question_id: str
    question: str
    rubric_sha256: str
    rubric_items: int
    vocabulary: list[dict]


@dataclass
class ExplainResult:
    hit: list[str]
    missed: list[str]
    passed: bool
    rubric: list[str]
    rubric_sha256: str
    next_step: str
    vocabulary: list[dict]


@srv.tool()
def explain(
    question: str,
    rubric: list[str],
    concepts: list[str],
) -> ExplainPosed:
    """Pose a free-response question, committing the rubric first.

    Returns the question and the rubric's hash — never the rubric itself, so
    the payload is safe to show. Grade the answer with `grade_explain`.

    `concepts` names the technical terms this question exercises, and the
    returned `vocabulary` tells you where each one stands across **all
    previous sessions**. Read it before writing the rubric: a concept reported
    as `naming_required` is one where a correct description no longer earns
    the item without the word, and `grade_explain` will refuse a verdict that
    credits it unnamed.

    Required rather than optional on purpose. An empty list is a legitimate
    answer for a question with no vocabulary at stake — but it is then a
    visible choice rather than an omission, which is the difference between
    declining the ledger and quietly bypassing it.

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

    declared = [c for c in (concepts or []) if c.strip()]
    if len(declared) != len(set(declared)):
        raise ToolError(f"duplicate concepts: {declared}")

    question_id = _new_id("explain")
    digest = _rubric_sha256(rubric)
    _EXPLAINS[question_id] = _PosedExplain(
        question=question,
        rubric=list(rubric),
        rubric_sha256=digest,
        concepts=declared,
    )
    return ExplainPosed(
        question_id=question_id,
        question=question,
        rubric_sha256=digest,
        rubric_items=len(rubric),
        vocabulary=ledger.status(declared, VAULT_ROOT),
    )


@srv.tool()
def grade_explain(
    question_id: str,
    answer: str,
    hit: list[str],
    missed: list[str],
    named: list[str] | None = None,
    unnamed: list[str] | None = None,
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

    `named` and `unnamed` split the concepts this question declared: which
    terms the learner actually used, and which they described correctly
    without naming. This is what the ledger counts across sessions, and it is
    why the split is per-concept rather than a single flag.

    A concept the posing call reported as `naming_required` **cannot** appear
    in `unnamed`: that verdict is refused, and the refusal cannot be waived
    from here. Either the learner used the term, or the rubric item it belongs
    to is missed. Naming a concept resets its streak, because the rule is
    about failing to internalize a term *continually*.
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

    told = [c for c in (named or []) if c.strip()]
    untold = [c for c in (unnamed or []) if c.strip()]
    stray = sorted({*told, *untold} - set(posed.concepts))
    if stray:
        raise ToolError(
            f"concepts not declared when the question was posed: {stray}. "
            f"Declared: {posed.concepts or 'none'}"
        )
    both = sorted(set(told) & set(untold))
    if both:
        raise ToolError(f"concepts in both named and unnamed: {both}")

    # Checked BEFORE anything is recorded, so a refusal leaves the ledger
    # exactly as it was and the call can simply be retried.
    blocked = ledger.gated(untold, VAULT_ROOT)
    if blocked:
        raise ToolError(
            f"naming is required for {blocked} and cannot be waived here — "
            "the term has gone unnamed too many times in a row. Either the "
            "learner used the word (put it in `named`), or the rubric item it "
            "belongs to is `missed`. Only a human can lift this, by setting "
            "`gate: off` in the concept's note."
        )

    posed.graded = True
    for name in told:
        ledger.record_named(name, VAULT_ROOT)
    for name in untold:
        ledger.record_unnamed(name, VAULT_ROOT)
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
        vocabulary=ledger.status(posed.concepts, VAULT_ROOT),
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
        print(f"  log          = {LOG.path}")
        return

    srv.run("stdio")


if __name__ == "__main__":
    main()
