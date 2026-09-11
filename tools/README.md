# Vault tools

MCP server exposing the question types and the log/artifact plumbing.

**This is the only component shared between L0 and L1.** Whatever shape it
takes here is inherited by the design layer, so it's worth getting the tool
signatures right before building much on top.

> **`quiz` and `explain` are implemented; the other five are not.** Built on
> the official MCP SDK (`mcp` 2.x) — `docs/OPEN.md` decision 8. Only the
> implemented tools are registered: a stub in `tools/list` reads to the model
> as a capability, and a tool that is visible and always raises costs a turn
> to discover.

## Tools

| Tool | Purpose |
|---|---|
| `quiz` | Pose multiple choice. Commits the answer key; returns only what the learner may see. |
| `answer_quiz` | Grade it. Computes `pick_correct` itself; takes the agent's judgment only on the reason. |
| `explain` | Pose free response, committing the rubric by hash first. |
| `grade_explain` | Grade it, refusing any verdict that does not account for exactly the committed rubric. |
| `derive` | Write a derivation note. Returns immediately; does not wait. |
| `ask` | Genuine fork, no right answer. Never used for gradable content. |
| `submit_artifact` | Read a submission — a note (resolving its `![[…]]` embeds) or a bare image. |
| `record_grade` | Write grading back into the derivation's own note. |
| `md_log` | Append to the session's markdown log in the vault. |

Seven names, nine calls: `record_grade` was split out once submissions became
notes, because writing structured front matter back is a different job from
appending to a transcript — and `quiz` and `explain` each became two calls, for
the reason below.

## Why a question costs two calls

**A tool call cannot ask the learner anything.** MCP is request/response, and
the one mechanism that would change that — `elicitation` — is unreachable here:
Toad 0.6.20 implements no handler for it, and `session/request_permission`, the
only inbound method that asks the user something, offers a choice among options
and so cannot carry a free-text justification.

So the question is asked in the conversation, and these tools are **notaries
and recorders**. One call poses and commits; a second grades and is checked
against what was committed. `derive` reached this conclusion first — "nothing
blocks" — and the reasoning simply had not been carried back to the other two.
See `docs/status.md`, "The signature hole".

## What is checked rather than trusted

The documented failure mode of LLM grading is sycophancy, so the grade is split
into the part that can be computed and the part that needs a model:

| Checked by the tool | Trusted to the agent |
|---|---|
| `pick_correct` — a string comparison against the committed key. `answer_quiz` takes no such argument, so it cannot be reported wrongly. | `reason_verdict` — `sound`, `coherent` or `incoherent`, judging the reasoning **on its own** rather than against the pick. The tool already knows the pick; combining the two is its job. |
| That `hit` and `missed` together account for **exactly** the committed rubric — nothing invented, nothing dropped. Without it, an agent looking at a weak answer could grade against a rubric it had quietly softened, and the published hash would still match. | Which rubric items the prose actually hit. |

### Five outcomes, not four

The verdict is three-valued because a boolean could not express the first thing
the first live session produced. The learner described the correct option
accurately and then picked a different one — a **slip**. With a boolean the
agent had to call that reasoning either correct, making it a "misconception",
or incorrect, making it a "gap"; it chose gap, so the mildest error available
collected the harshest prescription, *back up a level*. Its own prose said the
reasoning was "internally sound" while the grade it submitted said otherwise.

| Pick | Reason | Outcome |
|---|---|---|
| right | `sound` | solid — advance |
| right | `coherent` / `incoherent` | lucky guess — right for the wrong reasons |
| wrong | `sound` | **slip** — show the mismatch, do not re-teach |
| wrong | `coherent` | misconception — name it, probe its extent |
| wrong | `incoherent` | gap — back up a level |

Two smaller ones: a question cannot be answered twice (re-answering lets a
learner converge by elimination, destroying the signal), and the posing call's
return withholds the key — tool results are rendered in the client's UI, so
anything returned should be assumed immediately visible.

`quiz` also lints its options against the tells in `docs/teaching-loop.md` —
justification words inside an option, the correct option running longer than
the mean distractor, asymmetric bolding — and returns them as `warnings`.
Warnings rather than refusals: a false positive must never cost a lesson, and
the documented fix is "regenerate, don't patch", which is the agent's call.

## The call log

A tool server is spawned by the agent, several processes down, and its stdout
is protocol — so a file is the only place to see what it was actually asked.
One JSONL record per inbound call, flushed, under the XDG state dir that
`bin/smrt` mounts out of the container:

```bash
jq -r '[.outcome, .tool // .method, .error // ""] | @tsv' \
  ~/.local/share/smrt/state/smrt/tools/tools-*.jsonl
```

`$SMRT_TOOLS_LOG` redirects it; `SMRT_TOOLS_LOG=off` turns it off. Note that a
client decides its server's environment and hands over only `HOME`, `PATH` and
`TERM` by default, so that variable has to be set deliberately rather than
inherited.

**The refusals are the records worth reading.** A refusal is the server telling
the model it got the contract wrong; whether the model then corrects itself is
the question this file exists to answer. They are logged as `refused` rather
than `ok`, which took a fix: MCP reports a tool's own failure as a *successful*
response carrying `isError`, so only protocol faults raise and every refusal
initially logged as fine.

**A log contains full question, rubric and answer-key content** — a debugging
artifact, and not something to read mid-lesson if you mean to answer honestly.

## Tests

```bash
pixi run test-tools
```

Two suites. `tests/test_tools.py` calls the functions directly and covers the
grading; `tests/test_stdio.py` drives a real client against a real server over
stdio. The second earned its place immediately — it caught the SDK withholding
refusal text from the client, so every carefully worded refusal reached the
model as `Error executing tool grade_explain`. Refusals are `ToolError` now,
which the SDK relays; the direct-call tests could never have seen it.

## The derive loop

Decided 2026-09-08 — see `docs/OPEN.md` decision 7. **The note is the
submission.**

```
agent  derive(task, rubric, concept)      -> writes notes/…/derive-007.md
                                              front matter carries rubric_sha256
you    attach photo into "## Attempt"        Obsidian desktop or mobile
you    "done"                                in conversation
agent  submit_artifact("notes/…/derive-007.md")
                                           -> resolves embeds, returns images
agent  record_grade(...)                   -> appends "## Grading" callouts,
                                              sets status/score/rubric
```

What that buys, all of it native to Obsidian rather than bolted on:

- **The record is automatic.** Task, attempt and grading in one note, in the
  graph, with backlinks to the concept, and in git history since the vault is a
  repo.
- **It is queryable.** Front matter plus Dataview answers "every derivation I
  got wrong".
- **Grading renders.** `> [!success]` / `> [!warning]` callouts, not plain text.

Two constraints the signatures enforce:

**Nothing blocks.** MCP is request/response. A `derive` that waited minutes for
a photo would wedge the session, so it writes the note and returns. The wait is
conversational.

**Pre-commitment is verifiable.** `rubric_sha256` up front, plaintext `rubric`
only after grading. See `vault-template/templates/README.md`.

## Getting the photo into the vault

The note flow solves the *record*; it does not solve *transport*. The native
answer is Obsidian mobile on the same vault — open the note on your phone,
attach, shoot, done, no file management. That needs the vault synced to the
phone (Obsidian Sync, Syncthing, or self-hosted LiveSync), which touches the
deferred vault-topology decision: one vault means the phone syncs every
subject.

Not wanted: webcam or other host-device access. That was the argument for a
host socket and it is explicitly declined — see `docs/OPEN.md` decision 3.

## Wiring

Attached via the `mcpServers` field of ACP `session/new`.

**Toad 0.6.20 cannot do this** — it hardcodes the field empty. Observed on the
wire, not just read out of its source:

```json
{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd": "/vault", "mcpServers": []}, "id": 2}
```

So the ACP proxy is a prerequisite rather than a Phase 3 nicety. **It is now
built, and this is no longer a blocker** — a model has called a tool through an
injected MCP server:

```bash
smrt -- toad acp 'smrt-acp-proxy --backend claude --mcp vault-tools=vault-tools' /vault
```

Nothing stands between these signatures and a working teaching loop except
implementing them. See `docs/OPEN.md` decision 5, `docs/proxy.md`, and
`proxy/README.md`.

## Placement

In-container. `docs/OPEN.md` decision 3.

## TODO

- [x] Pick an MCP SDK — official `mcp` 2.x, decided 2026-09-10, decision 8
- [x] Implement `quiz` and `explain`, both as pose + grade pairs
- [ ] `derive`, and the note plumbing it needs
- [ ] Does `ask` need to exist at all? It was specified to *return* the
      learner's choice, which is not possible here; as a recorder it may be
      indistinguishable from the agent simply asking
- [x] Rubric visibility for `explain` — same rule as `derive`: hash committed
      before, plaintext after. Decided 2026-09-08.
- [ ] `md_log` — one file per session, or append to a daily note?
- [ ] Does `quiz` grade the justification with a model, or just record it?
- [ ] Persist quiz outcomes somewhere queryable, so the probe phase can start
      from what you already demonstrated last week. Front matter on derive
      notes is the pattern to copy.
