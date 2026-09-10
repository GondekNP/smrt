---
name: visualize
description: >
  Add one correct, minimal visual to a lesson when an idea is genuinely
  clearer as a picture. Renders inline in the Obsidian log.
status: placeholder
---

# Visualize

> **PLACEHOLDER.** Lower priority than `teach`. Build after the question
> types feel right.

A picture earns its place only when it shows something words can't — shape,
structure, direction, geometry. **When in doubt, don't.** A missing visual is
cheaper than a false one, and a decorative diagram that restates the sentence
beside it adds noise plus a chance to be wrong.

## When

- **Structure or relationship**: dependencies, flows, sequences, state
  machines, trees, containment. → mermaid
- **Spatial or geometric**: coordinate geometry, number lines, vectors,
  function shapes. → SVG

## Brief well

The most common failure is cramming. Prune to the fewest elements that carry
the idea, and for each ask: *if I delete this, is the idea still clear?*

- BAD: "make a diagram about how TCP works"
- GOOD: "graph TD: node 'packet' at top; arrows down to 'ordering' and
  'retransmit on loss'; both into 'reliable stream'. No title. Show that
  reliability is built FROM packets, not alongside them."

More than about 5–7 elements in the brief means cut first.

## TODO

- [ ] Decide: subagent, or inline mermaid in the log?
- [ ] Verification — the source system renders and *looks at* the image
      before returning. Worth replicating?
