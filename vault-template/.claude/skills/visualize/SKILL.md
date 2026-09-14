---
name: visualize
description: >
  Add one correct, minimal visual to a lesson when an idea is genuinely
  clearer as a picture. Renders inline in the Obsidian log.
---

# Visualize

A picture earns its place only when it shows something words can't — shape,
structure, direction, geometry. **When in doubt, don't.** A missing visual is
cheaper than a false one, and a decorative diagram that restates the sentence
beside it adds noise plus a chance to be wrong.

## The rule that decides everything else

**If the figure has numbers on an axis, do not draw it.**

Drawing a plot means drawing what you *believe* the data looks like. A
hand-authored posterior, likelihood curve or MCMC trace is a picture of a
guess wearing the costume of a measurement — and a plot reads as evidence in a
way prose never does, so it is worse than saying nothing. This is the same rule
that forbids recalling a course number instead of looking it up, applied to
pictures.

There is currently **no way to compute a figure here** — no numpy, no R. So
when a lesson wants a real plot, say in words what the plot would show and why,
and move on. That is an honest gap, not a failure.

What is left is everything with no data in it, which is most of what a lesson
actually needs:

| Want to show | Use |
|---|---|
| Dependencies, flows, sequences, state machines, trees, containment | **mermaid** |
| Geometry, vectors, projections, number lines, the shape of an argument | **SVG** |
| Anything measured | **neither — describe it** |

## Brief well

The most common failure is cramming. Prune to the fewest elements that carry
the idea, and for each ask: *if I delete this, is the idea still clear?*

- BAD: "make a diagram about how TCP works"
- GOOD: "graph TD: node 'packet' at top; arrows down to 'ordering' and
  'retransmit on loss'; both into 'reliable stream'. No title. Show that
  reliability is built FROM packets, not alongside them."

More than about 5–7 elements means cut first.

## SVG, and the two ways it silently breaks

Write it inline in your message. It flows into the session log untouched and
renders there.

**1. It fails without erroring.** Overlapping labels, a line off the canvas, an
arrow pointing at nothing — all render happily and all are wrong. Mermaid has
no equivalent problem because Obsidian shows a parse error, so it fails loudly
on its own.

So **look at what you drew** before you send it:

```bash
rsvg-convert -w 700 /tmp/fig.svg -o /tmp/fig.png   # non-zero exit if malformed
```

then read `/tmp/fig.png` and fix what you see. Not optional for anything with
more than two or three elements: you cannot proofread an SVG by reading its
source, any more than you can proofread a sentence by reading its bytes.

**2. It disappears in dark mode.** A `stroke="black"` drawing is invisible on a
dark background, and the theme is the reader's choice, not yours.

- Use `currentColor` for strokes, text and fills, so the drawing inherits the
  note's text colour and inverts with the theme.
- For a filled region, `fill="currentColor"` with `opacity="0.12"`.
- When you need a genuine accent colour, pick one that reads on both — a mid
  orange or teal — and use it for **one** thing.

Three more conventions, all about not breaking the page:

- `viewBox` plus `style="max-width:100%;height:auto"`. No fixed pixel width, or
  it overflows on a phone.
- **Nothing external**: no `<script>`, no web fonts, no `<image href>`. It must
  render from its own bytes.
- Label the parts you name in the prose, with the same words. A diagram whose
  labels disagree with the paragraph beside it is worse than no diagram.

## Mermaid

Fenced as ```mermaid. Renders natively, including in the session log.

Quote every label containing punctuation — `A["Ax = b"]` — and keep `<br/>` for
line breaks. If a diagram fails to render, Obsidian says so, so trust the error
rather than guessing.

## What this is for

The best figure in a lesson is often one no textbook contains, because it shows
the *join* between two sources — the point where a finite-state Markov chain
and a continuous posterior turn out to be the same object. A book draws its own
material; nobody draws the bridge. That is the figure worth making.

## Open

- **Verification is a convention, not a guarantee.** Nothing forces the
  rasterize-and-look step. It is here because the failure it prevents is
  invisible, which is exactly the kind this design does not usually leave to
  discipline.
- **Computed figures** — anything with data — need numpy or R, and neither is
  installed. Deferred deliberately: see `docs/environment.md`. The book's own
  `CompanionR/` scripts are the obvious first thing to run if that changes.
