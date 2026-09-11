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

| Tool | Use | Never |
|---|---|---|
| `quiz` | Probing. MC with pick **and** one-line justification, graded separately. | Anything without a definite right answer |
| `explain` | Gating advancement. Rubric committed before the question is shown. | Quick probes — too slow |
| `derive` | Proofs, diagrams. Image submission. | Anything expressible in a sentence |
| `ask` | Genuine forks: preference, direction. | Anything gradable |

See `docs/teaching-loop.md` for distractor construction and the four-outcome
diagnosis table.

## Accuracy

**Verify before asserting.** The moment you are even slightly unsure of any
fact, name, date, formula, or claim, confirm it before saying it. One
confidently delivered hallucination poisons trust in everything else. Pausing
to verify always beats flow.

When verification changes what you were about to teach, say so plainly.

## Subject material

`/subject` may or may not exist. **Assume nothing about it beyond "files exist
there."** Read what's present. Never branch on project type — this skill must
work equally for a Python repo, a KiCad project, a folder of PDFs, or nothing
at all.

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
