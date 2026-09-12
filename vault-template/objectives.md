---
emphasis: []
deemphasis: []
register: ""
---

# Objectives

**Standing calibration.** The `teach` skill reads this at the start of every
session. It is yours: edit it directly, or say `/calibrate <what you want>`
and the agent will write it here.

This file exists because the alternative is worse. Without it, a preference
stated in one session dies with that session, and the same wrong question gets
asked again next week. It lives in the vault rather than in the skill because
the skill is a template shared by every vault, and this is about *you* — the
skill stays generic, and the tuning is versioned in your git history beside the
judgments it shaped.

## How the three fields differ

**`emphasis`** — what questions should be spent on. A limited budget: everything
listed here competes with everything else listed here.

**`deemphasis`** — what not to test *even when the source covers it*. This is
the one that needs saying out loud, because a book's prominence is not your
priority. A stats text written around R will put R everywhere; that is the
author's teaching device, not your learning goal.

**`register`** — how to pitch it. Depth, pace, how much scaffolding, whether to
be told when you are wrong or shown.

Distinct from a curriculum topic's `relevance`, which says whether one
*specific* topic is worth covering. This file says what kind of thing matters
across all of them. A topic can be `cover` and still be the wrong thing to
build a question around.

## Log

<!--
Dated entries. What changed and, where you said one, why. A preference with
its reason attached survives being re-read in three months; a bare rule reads
as arbitrary and gets ignored or over-applied.
-->
