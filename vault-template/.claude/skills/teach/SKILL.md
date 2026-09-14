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

## Read the calibration first

**`/vault/objectives.md`, before the first question.** It carries standing
preferences: what to spend questions on, what not to test *even when the source
covers it*, and how to pitch things. `/calibrate` writes to it mid-session, and
that is a correction to apply now rather than a note for next time.

`deemphasis` is the entry that earns this file. A source's prominence is not the
learner's priority — a statistics text built around R will put R everywhere, and
questions about which object `optim()` returns test recall of an API rather than
the statistics it is a vehicle for. When a passage is inseparable from its
implementation, ask about the thing the code computes, not the call that
computes it.

It is distinct from a topic's `relevance`, which judges one topic. This judges
what kind of question is worth asking about any of them.

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

### Posing a question in the conversation

The tool call commits the answer key; the learner only ever sees what you
write in the message. Two things about that message:

**Options go in a markdown list, never bare lines.** A single newline between
`A.` and `B.` is not a line break in markdown — it collapses, and all four
options arrive as one paragraph of prose. Measured, not theorized: the first
live probe rendered exactly that way.

```markdown
- **A.** …
- **B.** …
```

**Ask for the reason the options do not contain.** "Give a one-line reason"
invites restating the option you just read, which grades as `sound` and
measures nothing. Ask instead for what a pick alone cannot show:

- *"In one line: what makes the nearest wrong option wrong?"*
- *"One line: what rule are you applying?"*
- *"One line: what would have to be true for B to be right instead?"*

See `docs/teaching-loop.md` for distractor construction and the eight-outcome
diagnosis table.

## Say the diagnosis out loud

**Every grade is told to the learner, in one line, before you move on.**

Measured, not hypothetical: in the 2026-09-13 session the first probe graded
`lucky_guess` — right pick, hollow reasoning — and the agent silently did the
right thing, re-probing the same idea from another angle. The learner had no
idea. They believed they had got it right and were being advanced; they were
actually being re-tested. `lucky_guess` is the single most valuable signal
these tools produce and it reached nobody.

Say the diagnosis, not the stage direction. `next_step` is instruction for
you — "escalate sharply", "back off" — and reads as being managed. The
diagnosis is information about *them*:

| Grade | Something like |
|---|---|
| `solid` | "Right, and for the right reason. Going up a level." |
| `lucky_guess` | "Right pick — but that reasoning doesn't get you there. Same idea, different angle." |
| `slip` | "Your reasoning was right and the letter wasn't. Reading the two side by side: …" |
| `misconception` | "There's a specific wrong belief here worth naming: …" |
| `gap` | "That one's below where we are. Backing up." |
| `unsure` | "You just described it correctly and then didn't back yourself. That's confidence, not knowledge." |
| `partial` | "The pieces are there, the join isn't." |
| `floor` | "Good — that's the floor, which is what I was looking for. Building up from underneath." |

**A floor is a finding, not a failure.** Probing exists to locate it, so
receiving several in a row means the probe is working. Say so, or a learner
answering "I don't know" five times reasonably concludes they are failing.

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
| `unsure` | treat as `solid` for level, and ask them to commit next time |
| `partial` | sideways, not down — the pieces are there and the join is not |
| `floor` | stop descending this strand. It is located |

**"I don't know" is an option on every quiz**, appended by the tool, always
last. Grade it like any other answer — pass their words as `reason` and judge
them on their own. Three of the eight outcomes exist only for it, and the
difference between them is real: "I don't remember, really" is a floor, while
"I remember only that eigenvectors are the fundamental of the system" is
fragments waiting to be joined.

Never let a declined question go ungraded. An ungraded question is one the
vault has no record of having been asked.

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

### Showing a figure

When the source has a figure the lesson turns on — a likelihood curve, a plate
diagram — show it rather than describing it:

```bash
smrt-curriculum figure ASM/2.5 33    # prints the pdftoppm command and the embed
```

Same rule as `locate`: it resolves the page, so you never convert printed to
PDF pages yourself. The image lands in `attachments/` and embeds as
`![[kery-asm-p33.png]]`, which renders in the markdown log.

**A figure or a page, not a chapter.** Rendering the book into the vault page
by page is reproducing it, and the vault is a git repo that may get a remote.
If you find yourself rendering a third consecutive page, read it with
`pdftotext` and describe it instead.

### A text is not automatically a curriculum

A textbook is ordered for teaching, so its chapter order is a reasonable
starting point for a DAG. **A paper is not.** Its section order is rhetorical
and it assumes a reader who already knows the field, so using it as a lesson
sequence produces a plan shaped like an argument instead of like a dependency
graph. For a paper, treat the sections as things to be quizzed on, and ask what
background it silently assumes — that is where the actual teaching is.

## Rendering

Obsidian renders LaTeX and mermaid natively, and the session log is read there.
Inline `$f(x)$`, display fenced in `$$`. Write math properly rather than in
ASCII approximation.

**A picture when the idea is shaped rather than stated** — geometry, a
dependency, a projection. See the `visualize` skill, and its one hard rule: if
the figure would have numbers on an axis, do not draw it. Nothing here can
compute a figure, so a drawn plot is a guess dressed as a measurement. Say what
it would show instead.

## TODO

- [ ] Rewrite for how you actually learn — do not ship the source calibration
- [x] Probe phase applies to every subject, code included. **Decided
      2026-09-08:** probe unilaterally and relax later if it grates. Skipping
      it for code would mean branching on subject type, which the `/subject`
      constraint forbids — and the cost of a lesson pitched at the wrong level
      is higher than the cost of a few redundant questions.
- [ ] Tune the number of probe questions before it gets tedious
- [ ] Decide whether the rubric is shown before or only after answering
