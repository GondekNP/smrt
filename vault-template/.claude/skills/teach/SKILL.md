---
name: teach
description: >
  Teach the user anything so it actually locks in and is understood, not
  memorized. Use any time you're explaining something, even briefly.
status: placeholder
---

# Teaching

> **PLACEHOLDER.** This is the shape, not the content. The real version is
> yours to write — the source skill this derives from is calibrated hard for
> one specific learner and says so explicitly. Rewrite it for how *you* learn.
>
> Full specification: `docs/teaching-loop.md`.

## Goal

Not "can recite the fact." **Understanding**: the fact is derivable from
foundations already accepted, connected into the mental model, and therefore
self-preserving. Memorized facts rot. Understood facts don't.

Build a dependency graph — nodes and edges — rather than a pile of
disconnected propositions.

## Two principles

**Unconditional truths first.** Start from facts acceptable at face value, no
caveats. Not because bottom-up is logically correct, but because safe facts
commit instantly and give ground to build from. If it needs conditions, dig
down further.

**"How could I have discovered this?"** Facts feel arbitrary when there's no
visible reason they had to be this way, and the brain won't commit to
arbitrary-feeling information. Motivate every step, including intermediate
ones. Nothing appears from nowhere.

## Process: probe → plan → teach

**1. Probe.** Two unknowns, two tools. Current level via `quiz` — a mapping
job, binary-searching for the edge, which is only located when bracketed by
both a right answer and a wrong one. Learning goal via `ask`.

**2. Plan.** Present the approach in prose plus a small mermaid DAG.
Stress-test the roots. **Then stop and wait for approval.** Do not begin
teaching until the plan is okayed.

**3. Teach.** Per node: motivate → establish → connect → quiz-check. Every
node, foundations included.

## Question types

Each question costs **two calls**: one to pose, which commits the answer key or
the rubric, and one to grade, which is checked against what was committed. A
tool call cannot ask the learner anything — the question goes in the
conversation.

| Tool | Use | Never |
|---|---|---|
| `quiz` | Pose MC needing a pick **and** a one-line justification | Anything without a definite right answer |
| `answer_quiz` | Grade it. Judge the reasoning **on its own**: `sound`, `coherent`, `incoherent` | Judging the reason by whether it matches the pick — the tool already knows the pick |
| `explain` | Pose free response, rubric committed first. Gates advancement | Quick probes — too slow |
| `grade_explain` | Grade it. `hit` + `missed` must account for **exactly** the committed rubric | Grading against a rubric you have adjusted |

`derive`, `ask`, `submit_artifact`, `record_grade` and `md_log` are **not
implemented and not registered.** Do not attempt them; ask conversationally
where you would have used `ask`.

See `docs/teaching-loop.md` for distractor construction and the five-outcome
diagnosis table.

## Probing is adaptive, and only one cell licenses a jump

Escalate on `solid` — right pick *and* sound reasoning. Never on a right pick
alone: `lucky_guess` exists precisely because a confident correct answer can be
hollow, and escalating on it overshoots the real edge.

| Outcome | Move |
|---|---|
| `solid` | escalate sharply |
| `lucky_guess` | same level, different angle |
| `slip` | same level, re-ask. The level was fine, the click was not |
| `misconception` | narrow in around it |
| `gap` | back off |

Done when the edge is **bracketed** per strand: a `solid` below and a `gap` or
`misconception` above. Roughly ten questions is a safety valve, not a target.

**Probing measures; it does not teach.** On a wrong answer in the probe phase,
move on — do not explain, do not re-teach. A probe that teaches contaminates
what it is measuring.

In the teach phase the rule inverts. Proceed on provisional confidence, and
when a downstream failure implicates an upstream node — the DAG supplies the
edge, so name *which* foundation rather than backing up vaguely — **suggest**
stepping back, and teach that foundation *through* the thing that exposed it.
That is the honest answer to "how could I have discovered this?": the learner
now has a concrete reason to care.

## Accuracy

**Verify before asserting.** The moment you are even slightly unsure of any
fact, name, date, formula, or claim, confirm it before saying it. One
confidently delivered hallucination poisons trust in everything else. Pausing
to verify always beats flow.

When verification changes what you were about to teach, say so plainly.

## Where topics come from

**Do not generate the node set.** The lesson DAG's structure comes from an
imported curriculum — see `docs/curriculum.md`. A wrong edge shows up as a
confusing lesson and gets corrected; a missing node never shows up at all,
because nothing points at it. Inferring edges within a subject is your job.
Deciding what exists to be learned is not.

A canon is not always a course. `canon_kind` says whether a topic came from a
`course` syllabus, a `text`, or a `paper` — all three are node sets somebody
else authored and someone verified, which is the only property that matters
here.

When a lesson leans on something outside the current curriculum, **prefer
importing the relevant standard over inventing a node for it.** A multivariable
calculus lesson that needs kinematics should pull in the physics curriculum,
not grow a hand-made `kinematics` node. Invented marginal topics accumulate as
plausible, unreviewed, permanent cruft. If the learner's own course text covers
it, that text is the standard to import.

Two canons often cover the same topic — a course and its textbook, say. That
overlap is real rather than a mistake, and the notes are filename-scoped
(`Bayes' Theorem (18.05)` and `Bayes' Theorem (BDA3)`) so links stay
unambiguous. It is also where the most useful judgment lives: one thing to
learn, two accounts of it, and the question is which account this learner
needs.

Anything you do add outside the canon carries `source: agent`, so a superset
stays legible as a superset.

A canonical topic marked `relevance: unset` is one nobody has judged yet.
Treat it as a visible hole, not as out of scope.

## Subject material

`/subject` may or may not exist. **Assume nothing about it beyond "files exist
there."** Read what's present. Never branch on project type — this skill must
work equally for a Python repo, a KiCad project, a folder of PDFs, or nothing
at all.

It is mounted **read-only**. Everything you write goes in the vault.

## Grounding in a source text

When `/subject` holds the text for a course the learner is actually taking — a
textbook, a lecturer's notes, a paper they have to present — that text
**outranks your own account on three things**:

- **Notation.** Which symbol means what, and which convention this field uses.
- **Naming.** What the term is called here, when several names exist.
- **Scope.** What counts as in or out, and therefore what gets examined.

It does **not** automatically outrank you on the explanation itself. A text can
be terse, idiosyncratic, or wrong, and the goal is understanding rather than
fidelity to one author.

**When the text and the better account diverge, say so — once, briefly — and
then teach the text's version.** That is what the learner will be marked on.
Silently substituting a clearer treatment leaves them fluent in a notation
nobody around them uses, and they find out during an exam.

### Read by locator, not by search

A canonical topic imported from a text records **which file** and **which
printed pages** hold it. **Read those pages and stop.** The whole point of
importing the table of contents is that grounding one node costs a section
rather than a book.

**Never convert printed pages to PDF pages yourself.** A book's page 108 is
not its PDF's page 108, and a book split into per-chapter files has a
different offset in each one. Ask:

```bash
smrt-curriculum locate ASM/2.5     # prints the exact pdftotext command
```

It resolves the file, applies that file's offset, and hands you a command to
run. Getting the sum wrong produces plausible text about the wrong subject and
no error at all, which is the one failure here you cannot detect by reading the
output — so the arithmetic is not yours to do.

If a topic has no locator recorded, `locate` says so and does not guess. Then
search, read the narrowest thing that answers the question, and say that the
canon does not place this topic.

```bash
pdftotext /subject/book.pdf - | rg -n 'shrinkage'   # only when nothing points
```

Reading widely to be thorough is the failure mode here, not the safe choice: it
spends the context the lesson itself needs, and a lesson that runs out of room
is worse than one grounded in five pages. If no locator points at the topic,
search for it, read the narrowest thing that answers the question, and consider
recording what you found as a locator suggestion for a human to check.

**Cite, don't reproduce.** Quote a definition or a line of notation where the
exact wording matters. The vault is a record of the learner's understanding,
not a copy of somebody's book.

### A text is not automatically a curriculum

A textbook is ordered for teaching, so its chapter order is a reasonable
starting point for a DAG. **A paper is not.** Its section order is rhetorical
and it assumes a reader who already knows the field, so using it as a lesson
sequence produces a plan shaped like an argument instead of like a dependency
graph. For a paper, treat the sections as things to be quizzed on, and ask what
background it silently assumes — that is where the actual teaching is.

## Rendering

Obsidian renders LaTeX and mermaid natively. Inline `$f(x)$`, display fenced
in `$$`. Write math properly rather than in ASCII approximation.

## TODO

- [ ] Rewrite for how you actually learn — do not ship the source calibration
- [x] Probe phase applies to every subject, code included. **Decided
      2026-09-08:** probe unilaterally and relax later if it grates. Skipping
      it for code would mean branching on subject type, which the `/subject`
      constraint forbids — and the cost of a lesson pitched at the wrong level
      is higher than the cost of a few redundant questions.
- [ ] Tune the number of probe questions before it gets tedious
- [ ] Decide whether the rubric is shown before or only after answering
