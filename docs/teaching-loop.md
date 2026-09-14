# Teaching loop

The session shape and the four question types. This is the thing L0 exists to
test — get it right here, cheaply, before the same patterns become
load-bearing at the design layer.

## Session shape: probe → plan → teach

Adapted from the `teach` skill in
[amosblomqvist/learn](https://github.com/GondekNP/learn).

The load-bearing element is that **Phase 2 ends by presenting a plan as a
dependency DAG and stopping to wait for approval.** A wrong root is cheap to
fix before the lesson and expensive during it.

That checkpoint is the same gate that appears at L1 as `/design`. It is the
single most transferable idea in the whole system, and it's worth noticing
that the original skill arrived at it for pedagogical reasons rather than
control reasons.

### Phase 1 — Probe

Two separate unknowns, two separate tools:

- **Current level** → `quiz`. A mapping job, not a spot check. Locate the
  *edge* of understanding along every strand the lesson depends on — and the
  strands are canonical topics, not invented ones. See `curriculum.md`.
- **Learning goal** → asked conversationally. No right answer, so never a
  quiz. (`ask` was specified for this and is not implemented; a tool call
  cannot ask anyone anything here, and a genuine question in conversation is
  just talking.)

The edge is only located when **bracketed**: something at that level answered
right (a floor) *and* something answered wrong (a ceiling). One side alone
tells you almost nothing.

- All-correct means the questions were too easy, not that probing is done.
- Binary-search: jump difficulty sharply up on a hit, narrow in on a miss.
- One wrong answer is one coordinate. Probe around it before concluding
  whether it's a slip, a gap, or a systematic misconception.

### Phase 2 — Plan

**The node set is selected, not invented.** Reason out the approach over the
canonical topics (`curriculum.md`) and present it as prose plus a small mermaid
DAG — unconditional truths at the roots, the goal as the sink. **Stress-test
the roots**: anything treated as foundational that actually derives from
something simpler should be pushed down.

Edges are yours to infer; the node set is not. A wrong edge shows up as a
confusing lesson and gets corrected. A missing node shows up as nothing at
all, which is why coverage is imported rather than generated.

**What gets approved is a diff, not a blank page.** Three things, explicitly:

- which canonical topics are **in scope** for this goal
- which are **out**, and why — "cover, but reframe for n dimensions" is the
  common case, not a plain yes or no
- what you are **adding** beyond the canon, marked `source: agent`

That shape matters. Approving a from-scratch graph means auditing it for
things that are not there, which nobody can do. Approving a diff means
omissions are something declined in the open rather than never seen.

Then stop and wait.

### Phase 3 — Teach

Per node: motivate → establish → connect → quiz-check. Every node, including
foundational ones. An unconfirmed foundation is exactly as dangerous as an
unconfirmed derived step.

## The four question types

Not interchangeable. Each buys something specific.

### `quiz` — multiple choice, pick + justify

Retained despite the obvious objection to plain MC, because requiring a
one-line justification alongside the pick recovers what MC was losing.
**The pick and the reason are graded separately**, giving five outcomes
instead of two. The reason is judged **on its own** — `sound`, `coherent` or
`incoherent` — and never against the pick, because combining the two is the
tool's job and it already knows the pick:

| Pick | Reason | Diagnosis |
|---|---|---|
| right | `sound` | Solid. Advance. |
| right | `coherent` or `incoherent` | Lucky guess or right-for-wrong-reasons. **The most valuable signal here** — invisible under plain MC. |
| wrong | `sound` | **A slip.** The reasoning was right and the pick was not. Show the mismatch; do not re-teach, and do not back up. |
| wrong | `coherent` | A specific, nameable misconception. Dig into its extent. |
| wrong | `incoherent` | Genuine gap, not a misconception. Back up a level. |
| **"I don't know"** | `sound` | **Unsure.** They described it correctly and would not commit. Confidence, not knowledge. |
| **"I don't know"** | `coherent` | **Partial.** Fragments not yet assembled. Probe sideways, not down. |
| **"I don't know"** | `incoherent` | **The floor.** What probing is for. Stop descending, build from underneath. |

**"I don't know" is a third pick state, not a wrong answer**, and the tool
appends it to every quiz rather than trusting the agent to offer it. Added
2026-09-13 after a probe session answered five of ten questions "I don't
remember" and produced **no grading call for any of them** — there was nowhere
to put that answer, so eight posed questions left no record of having been
asked. Finding the floor is what probing is for, so the likeliest answer during
a probe was the one the tool could not represent.

Three rows rather than one because those answers genuinely differ: *"I don't
remember, really"* is a floor, while *"I remember only that the eigenvectors are
the fundamental of the system"* is fragments waiting to be joined, and the next
move is not the same.

**Every grade is said out loud to the learner.** In that same session the first
probe graded `lucky_guess` and the agent silently re-probed from another angle —
correct behaviour, invisible to the learner, who believed they had it right. The
most valuable signal these tools produce reached nobody. Say the diagnosis, not
the `next_step`: the latter is stage direction for the agent and reads as being
managed.

**`slip` was added on 2026-09-11, and the first live session produced it
immediately** — which is the argument for having run one. The learner
described the correct option accurately and then picked a different one. Under
a boolean verdict the agent had to call that reasoning either correct, making
it a "misconception", or incorrect, making it a "gap"; it chose gap, so the
mildest error available collected the harshest prescription. Its own prose told
the learner the reasoning was "internally sound" while the grade it submitted
said the opposite. The table was missing a cell, not the model.

Distractor construction, worth preserving verbatim from the source skill:

1. **Every option is a bare claim — no justification anywhere.** The number
   one giveaway is the correct option carrying its own reasoning while
   distractors are bare, making it longer and more specific. All "why" goes
   in the post-answer explanation.
2. **Write the correct claim first, then mutate it into each distractor.**
   Take a specific misconception and state what someone holding it would
   claim, in the same skeleton, grain size, and register. Parallelism falls
   out by construction rather than being policed afterwards.
3. Each distractor must be a real error you might actually make — tempting,
   not tricky — yet unambiguously wrong on the intended reading.
4. **No asymmetric bolding.** Bold the parallel term in every option or none.

If you can tell which is right while cold on the material, steps 1 or 2 were
skipped. Regenerate, don't patch.

**Rule 1 is enforced, not requested** — `quiz` refuses a set whose options
argue for themselves. The first live probe, 2026-09-12, is why:

> The curvature (second derivative) of the LL near the MLE — a sharper peak
> means the LL drops fast as θ moves away, so the data rule out nearby values
> strongly.

Nothing fired. `so` was matched only as "so that" and `means` only as "which
means", and at 1.38× the mean distractor length it slipped under a 1.5× bar.
The learner's report was the precise diagnosis: *"it wants a one-line reason,
it seems the obvious answer is to just reiterate what the answer is."* Which
makes the second half of the design worthless — a justification that restates
the option grades `sound` and measures nothing.

So the keyword list is wider, a dash followed by six or more words is treated
as an argument, and being the longest option now counts at 1.25×. The style
tells stay warnings; this one refuses. Worth recording that when the length
warning *did* fire on a later question, the agent regenerated unprompted — the
mechanism worked and detection was what failed. It is a refusal anyway,
because "the agent usually notices" is not a guarantee this design accepts
anywhere else.

**Asking for the reason is a separate skill.** "Give a one-line reason" invites
restatement. Ask for what the pick cannot show: what makes the nearest wrong
option wrong, which rule was applied, what would have to change for another
option to win.

**Used heavily in probe**, where twelve cheap signals beat twelve essays.

### `explain` — free response, rubric-graded

The agent commits, **before showing the question**, to the three things a
correct explanation must contain. You answer freely. It grades against that
list and names which of the three you missed.

The pre-commitment is not ceremony. The default failure of LLM free-response
grading is sycophancy — it will call a hand-wavy answer excellent. A rubric
written before it sees the answer is the fix, and it restores the diagnostic
property MC gets by construction.

**This is the gate for advancing.** Passing means you can explain it as if
teaching it.

### `derive` — proof or diagram, attached to a note

Done on paper, photographed, and **attached into the derivation's own note**.
`derive` writes that note and returns immediately; you attach the image under
`## Attempt` in Obsidian; `submit_artifact` resolves the embed; `record_grade`
appends the grading to the same note. Graded on the steps, not the answer.

The note is the submission, and that is the point — see `OPEN.md` decision 7.
Task, attempt and grading end up in one place, in the graph, backlinked to the
concept, and in git history. Front matter makes the whole record queryable
rather than leaving it in a transcript.

The rubric is committed as `rubric_sha256` before you see the task and written
out in plaintext only after grading, so you can verify the bar was not moved
once your answer was seen.

Stats context: derive the Hessian, Fisher information, a likelihood ratio.

Design context: **draw the module dependency DAG from memory** — and this one
has a deterministic answer key, because the import graph is machine-derivable
at L1. A fuzzy submission graded against a hard key is probably the best
single test of whether a `/tutor` session landed.

### `ask` — genuine fork, no right answer

Preferences, direction, what you want next. **Never used for anything
gradable.** The discipline matters: if a question has a right answer it is a
quiz, and misusing `ask` for gradable content is exactly what makes agent
check-ins feel like hand-holding.

## Accuracy

Verify, don't wing it. One confidently delivered hallucination poisons trust
in the whole thing. **The moment you are even slightly unsure of any fact,
name, date, formula, or claim, confirm it before saying it.** Pausing to
verify always beats flow.

When a check changes what you were about to teach, say so plainly rather than
quietly papering over it. A wrong root corrupts every node built on it.

## Rendering

Obsidian renders LaTeX and mermaid natively, so write both properly rather
than in plain-text approximation. Inline `$f(x)$`, display fenced in `$$`.
