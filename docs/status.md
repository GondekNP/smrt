# Status

**Layer: L0 (vault container). Verified working, 2026-09-09.**

What follows is what was actually exercised, not what was intended. Anything
not listed as verified should be assumed untested.

## Verified

| | |
|---|---|
| Build | `scripts/build.sh` exits 0; image ~1.5GB |
| Toad | 0.6.20 — launches, renders, opens `/vault/`, reaches the agent picker |
| Toad → agent | full ACP handshake to `opencode acp` and to `claude-agent-acp`: `initialize`, `session/new`, first `session/update` |
| Claude Code | 2.1.261 — completed a real prompt end-to-end (`6×7` → `42`) |
| Claude Code over ACP | adapter installs and launches; negotiates protocol version 1 |
| OpenCode | 1.18.28 — on `PATH`, runs; `opencode acp` is a real ACP server |
| pixi / Python | 0.79.0 / 3.14.7 |
| `/vault` | read-write; host ownership correct (`nick:nick`) |
| `/subject` | read-only against 10 adversarial writes, including `sudo` and `mount -o remount,rw` |
| Toad state | persists across runs — settings **and**, since 2026-09-09, session history |
| Auth isolation | container sees no host credentials on the default path |
| Container `/login` | done; `.credentials.json` (mode 600) in `$SMRT_STATE/agents`, host `~/.claude` untouched |
| A real session | two prompts through Toad → proxy → `claude-agent-acp`, both `stopReason: end_turn` |
| Path guard | `submit_artifact` rejects `../../etc/passwd`, `/etc/passwd`, `notes/../../etc/passwd` |
| Preflight | catches Docker Desktop, exits 1 with remedies; cached after first run |
| ACP proxy | pass-through verified three ways, including a real session — see below |
| `mcpServers` injection | a model called a tool through an injected MCP server, in Toad's own TUI |
| `session/cancel` | cancelled mid-stream through the proxy; agent answered `stopReason: cancelled` in 7 ms |
| Toad compat shim | A/B/C: Toad rejects the frame direct and with `--no-compat`, accepts it repaired |
| Load | 206 frames / 129 KB / 225 s in one session; largest frame 31 KB |
| `quiz` / `explain` | implemented as pose + grade pairs; refusals verified over stdio |
| Curriculum canon | 4 courses, 100 topics, cited and verified against ocw.mit.edu |
| Canon kinds | a `text` canon loads, seeds and audits without a course number or URL; `pdftotext` extracts by page range in the image |
| The first real text canon | Kéry & Kellner ASM (2024): 177 topics, 21 chapter PDFs, imported from the book's own Contents PDF |
| Page offsets | all 21 verified against the PDFs, not just computed — each chapter's pdf page 2 header matches its declared offset |
| `locate` end to end | `locate ASM/2.5` printed `pdf pp. 17-30`; running exactly that command returned text beginning "2.5 Classical inference by maximum likelihood" on printed page 31 |
| Seeding, at scale | 277 topics across 5 canons into a vault, 0 holes and 0 orphans |
| Overlap scoping | a text sharing a title with 18.05 seeds to `... (DEMO).md`, and the 18.05 note's judgment survives both the `RENAME` report and a re-seed |
| Vocabulary gate | tiers progress across sessions; a gated concept's unnamed credit is refused, and the refusal leaves the ledger untouched so the call can be retried |
| Seeding | 100 notes into a vault through the real `smrt` path; re-seed is a no-op and cannot touch a judgment |
| **A real teaching exchange** | 2026-09-11: a model posed a quiz and an explain question through Toad, graded both, and refused to soften a rubric |
| Tool namespacing | reaches the model as `mcp__vault-tools__quiz`; the hyphen survives |
| Text-anchored crops | 2026-09-15: `snip ASM/3.4 99 --from … --to …` produced a crop carrying all six design-matrix rows, the coefficient block and the matrix notation, with clean edges — the same page an eyeballed box had cut in half twice |
| Shell variables defeat allow rules | measured, not reasoned: the `$SUBJECT_ROOT` form of a `pdftoppm` command was denied and wrote no file; the literal `/subject/…` form ran. Commands now print literal paths |
| The question is written once | the real 427-frame session replayed through the fixed mirror: `### Quiz` 0, `#### Graded` 0, Q4 and Q5 each posed exactly once, grade folded into `<details>` |
| Permission rules | 2026-09-15, under `--permission-prompts none` (which denies anything that would prompt): a `touch` into `/vault` was denied and the file not created, while `pdftotext` on an unapproved page range, `smrt-curriculum locate` and a `pdftoppm` write all ran |
| Snipping a source page | 2026-09-15: `snip ASM/3.4 98 90,405,495,165` emitted the crop that cut Kéry's design matrix out of printed p. 98 — 23 KB, legible, verified against the rendered page. Its motive is measured too: the same table's R output extracts from `pdftotext` with the header/value pairing destroyed |
| Rendering, in Obsidian | 2026-09-13: inline SVG, an embedded `![[fig.svg]]`, and mermaid all render in Reading view. Only the **inline** one follows the theme — the identical file, embedded, stayed black in dark mode, because an embed is a separate document and `currentColor` cannot reach it |
| The answer key | streams to the client in `rawInput` but Toad does not render it — the pre-commitment holds at the display layer |
| `vault-tools` | serves MCP through the wrapper on `PATH`, spawned as a client spawns it |
| Proxy tests | 80/80, in the image (Python 3.14) and on the host (3.10) |
| Tool tests | 174/174, in the image (the MCP SDK is not a host dependency) |
| shellcheck | zero errors across `bin/smrt`, `scripts/`, `docker/` |

The read-only enforcement is the claim the project rests on, and it survived
every attempt made against it — including from a user with passwordless sudo.

### The proxy, specifically

"Toad still launched" is not evidence of transparency, so it was checked two
independent ways:

| Check | Result |
|---|---|
| Toad's transcript vs the proxy's trace, handshake only | 5 frames each, same order, same ids, same byte counts |
| Toad → backend direct vs Toad → proxy → backend | identical frame for frame, once session ids are normalized |
| **A real Claude Code session, two prompts, 35s** | 24 comparable frames identical; 20 agent frames byte-verified across 30,694 bytes |

The first two were captured with Toad running headless under
`TEXTUAL_DRIVER=textual.drivers.headless_driver:HeadlessDriver`, which is worth
knowing: it makes the whole ACP handshake exercisable without a terminal, and
without credentials, since the handshake precedes any model call.

The third is the one that counts — it streamed a reply in three chunks and both
turns closed cleanly, so `session/prompt` and streaming `session/update` are
exercised rather than just the handshake.

**A trap if you repeat that diff:** Toad logs the requests it sends and
everything it receives, but *not* the replies it sends back. Its transcript was
24 frames where the proxy's trace had 28, and the four extra were Toad's own
error replies. Incomplete logging on Toad's side, not invented traffic on the
proxy's.

It also produced the measurement decision 5 was resting on inference for —
`session/new` really does carry `mcpServers: []`. See `docs/proxy.md`.

## Found in the live session, 2026-09-10

Five prompts through Toad → proxy → `claude-agent-acp`, including a mid-stream
cancel and a real tool call. Two defects, one ours:

**Ours, fixed.** The proxy drained the backend's stderr with `read(4096)`, and
on a buffered stream `read(n)` waits for the full n bytes — so the agent's
whole log appeared in the trace in one lump at shutdown. It never deadlocked,
because draining was still happening, but the timestamps were fiction and a
backend that logged something and then hung would have shown nothing, which is
exactly when you would want it. Now `read1`. The regression test was checked
against the old code to confirm it actually fails.

**Toad's, shimmed not fixed.** Toad drops every completed tool call because
`ToolCallUpdate.rawOutput` is annotated `dict` while the reference schema says
`Option<serde_json::Value>` — any JSON value. On L0's critical path, since the
whole teaching loop delivers through tool calls. `proxy/acp_proxy/compat.py`
repairs it locally; the upstream report is deliberately deferred and the
follow-up is a block comment in that file. `docs/proxy.md` has the evidence.

## Corrected here

Two claims on this page were wrong, and both were wrong in the flattering
direction.

**"Toad state persists across runs" was true only of settings.** Toad splits
its state across both XDG dirs: `~/.config/toad/toad.json` holds UI settings,
while session history is a SQLite database at `~/.local/state/toad/toad.db`
(`toad/db.py:38`). Only the config dir was mounted, so scrollback never
survived a launch — the earlier check happened to look at the half that did.
`bin/smrt` now mounts the state dir too, and `toad.db` was observed appearing
in it.

**Toad could not reach Claude Code at all.** Its bundled definition launches
`claude-agent-acp`, which was not installed, and the `claude` CLI has no ACP
mode — so "reaches the agent picker" was the true ceiling of what had been
tested, and picking Claude Code from that picker would have failed. Fixed in
`docker/install-agents.sh`.

One more, found while building and fixed in passing: `scripts/build.sh`,
`check.sh` and `clean.sh` used whichever docker context happened to be active,
while `bin/smrt` pins one. On this machine that meant `pixi run build` wrote
into Docker Desktop while `smrt` read from the plain engine — the image existed
in both, at different digests. All four now pin the same way. This is the exact
failure `OPEN.md` decision 4 is about, one layer up from where it was fixed.

## Not yet verified

- **`fs/*` and `terminal/*`, through the proxy.** Not for lack of trying:
  `claude-agent-acp` reads files with its own `Read` tool rather than calling
  the client's `fs/read_text_file`, so a prompt that reads `/subject` produces
  `tool_call` updates and no `fs/*` traffic at all. That may mean this backend
  never exercises them. It also matters for L1's gate, which `docs/proxy.md`
  describes as counting writes — with this backend, writes will appear as
  `tool_call` updates, not as `fs/write_text_file`.
- **`session/load`.** Injection covers it, but Toad 0.6.20 exposes no resume
  command, so it has not been exercised live.
- **The question types in a live session.** `quiz` and `explain` are
  implemented and tested, but no model has yet posed one. `derive`, `ask`,
  `submit_artifact`, `record_grade` and `md_log` still raise
  `NotImplementedError` and are deliberately unregistered.
- **The teaching loop.** Two of its four question types now work; the loop
  itself needs the `teach` skill, which is still a placeholder.
- **Token refresh across a bind mount.** Unknown. First suspect if a long
  session drops its auth.
- **The `teach` skill itself.** Still a placeholder; the real version is
  unwritten.

Nothing about the *interaction patterns* — the thing L0 exists to test — has
been exercised. The plumbing is done, and now reaches further than it did; the
point is still not started.

## Next, in order

1. ~~**`/login` once in the container.**~~ Done 2026-09-09; a real session ran
   through the proxy on the credentials it created.
2. ~~**The ACP proxy, pass-through first.**~~ Done 2026-09-09.
3. ~~**`session/new` injection.**~~ Done 2026-09-09. The tool server is
   unblocked; nothing about the teaching loop is waiting on infrastructure any
   more.
4. ~~**Pick an MCP SDK; implement `quiz` and `explain`.**~~ Done 2026-09-10.
   Official `mcp` 2.1.1 (`OPEN.md` decision 8); both implemented as pose +
   grade pairs; 39 tests. **Not yet exercised by a model** -- one live session
   through the proxy with `--mcp vault-tools=vault-tools` is the remaining
   check, and the first thing to do next.
   Use `SMRT_TOOLS=./tools smrt` so each edit doesn't cost an image rebuild
   (and `SMRT_PROXY_SRC=./proxy` for the proxy).
4.5 **The vault's memory.** Two halves, both prerequisites for the skill:
   *what there is to demonstrate* (the curriculum layer — **done**: canon,
   seeding and audit across 18.06SC, 18.05, 18.655 and 6.438, 100 topics) and
   *what you have demonstrated* (the concept ledger, with the tiered
   vocabulary rule — **done**: lenient below 2 unnamed credits in a row,
   advisory to 3, refused at 4, naming resets the streak, and only a human
   can set `gate: off`).
5. **Rewrite the `teach` skill** for how you actually learn. Do not ship the
   source calibration.
6. **Then, and only then**, judge whether the four question types are right.
   That judgement is the deliverable of L0.

## Deferred follow-ups, with their triggers

Things parked on purpose, each with the event that should un-park it. Recorded
here because a follow-up that lives only in a code comment is a follow-up
nobody finds.

- **Report Toad's `rawInput`/`rawOutput` annotation upstream, then delete our
  shim.** Trigger: a Toad release after 0.6.20, or enough confidence to open
  the issue. The shim is `proxy/acp_proxy/compat.py` and carries the same note
  as a block comment; `--no-compat` is how you test whether it is still needed.
  Leaving it in place after upstream heals is the failure mode to avoid.
- **`session_info_update` is still dropped.** Toad's `SessionUpdate` union has
  no such variant, so this is a missing member rather than a wrong annotation
  and stripping a field cannot help it. One lost notification per session,
  nothing depends on it. Not shimmed, deliberately — the shim should stay as
  narrow as its evidence.
- **The L1 gate cannot count writes via `fs/*`.** Measured 2026-09-10, with
  the client advertising both `fs` capabilities and really implementing them:
  the agent used neither, zero times. The portable signal is `update.kind`
  (`edit` covers create and modify) plus `update.locations[].path` — but only
  on `tool_call_update`, since the announcing `tool_call` is a stub, and
  arguments stream in progressively, so a gate must accumulate per
  `toolCallId` and judge at `status: completed`.

  The sharper problem found by the same measurement: **`kind: "execute"` is an
  unbounded hole.** The agent reached for `Bash` unprompted, and a shell
  command can write anything while reporting `execute`, not `edit`. A budget
  must treat one `execute` as unknown-and-possibly-many rather than zero.
  Full detail in `docs/proxy.md`. Trigger: designing the gate.

## The signature hole

Found on 2026-09-10 while starting item 4, and it blocks writing `quiz` and
`explain` as documented.

**`quiz` cannot return what its signature promises.** It takes
`(prompt, options, correct_option_id, explanation, hint)` and returns a
`QuizResult` of `pick_correct` / `reason_correct` / `diagnosis` -- but the
learner's answer is not among its arguments. Nothing in the inputs determines
the outputs. `explain` has the same shape of problem: it takes
`(question, rubric)` and its docstring says it "returns which rubric items were
hit and which were missed", with no answer to grade.

So the tools were specified as though they could block on the learner, and MCP
is request/response. `derive` already faced this and resolved it explicitly --
"Nothing blocks. MCP is request/response, so a `derive` that waited for a photo
would wedge the session" -- but that reasoning was never carried back to `quiz`
and `explain`.

**Blocking is not available through this stack.** Worth checking rather than
assuming, because MCP does have a mechanism for exactly this: `elicitation`, a
server-initiated request for user input. It is in the ACP schema too
(`elicitation/create` appears in the adapter's bundled SDK). But **Toad 0.6.20
implements no elicitation handler** -- its inbound surface is the nine methods
already measured (`session/update`, `session/request_permission`, `fs/*`,
`terminal/*`) and `grep -ri elicit` over its source returns nothing. So even a
perfect adapter has nowhere to send one. And `session/request_permission`,
the one inbound method that does ask the user something, offers a choice among
options -- it cannot carry a free-text justification.

That rules out the shape where a tool call renders a question and returns the
answer. What remains is the tool as **notary and recorder**: the question is
asked in the conversation, and the tools exist to make the pre-commitment
verifiable and the record durable.

**Resolved 2026-09-10: two calls, and the tool grades what can be computed.**
`quiz` poses and commits the key; `answer_quiz` computes `pick_correct` itself
and takes the agent's judgment only on the reason. `explain` commits the rubric
by hash; `grade_explain` refuses any verdict that does not account for exactly
the committed rubric -- nothing invented, nothing dropped. So the four-outcome
table has a leg the agent cannot move, and a rubric cannot be softened once the
answer is in view.

### Two things that only showed up on the wire

Both would have shipped silently, and both were caught by the stdio suite
rather than the direct-call one -- which is the argument for having two.

**The SDK withholds refusal text.** It reports the message of an anticipated
failure (`ToolError`) to the client and suppresses anything else as a crash
whose internals should not leak. A good default, and it made every refusal
useless: "grade against the rubric as committed, quoting items verbatim"
reached the model as `Error executing tool grade_explain`. Refusals are
`ToolError` now. In these tools the message *is* the mechanism, so this was not
cosmetic.

**An MCP server does not inherit the environment.** The Python SDK's stdio
client passes only `HOME`, `PATH` and `TERM`, so the image's `PYTHONPATH` was
gone and `python3 -m vault_tools.server` could not find its own package -- the
client saw `Connection closed` and nothing more. Each wrapper in
`.local/bin` now sets its own `PYTHONPATH`. Claude Code's client does pass it
through today, which is why `smrt-mcp-probe` worked live, but depending on that
is depending on someone else's allowlist.

**And the environment problem had a second half, found only under Toad.** The
wrapper still said `python3`, and this image has three of them: the pixi
`python` environment (the only one carrying the MCP SDK), Toad's own
interpreter, and Debian's. Which one a client's PATH resolves is a coin flip --
so the tool server worked from a scripted ACP client and died under Toad with
`ModuleNotFoundError: No module named 'mcp'`, while the model reported only
that the server "failed to connect (connection closed)". The proxy and the
probe are stdlib-only, so they had been winning the same coin flip unnoticed;
this surfaced with the first component that had a dependency. The wrappers now
name an absolute interpreter, and the build fails if it cannot import `mcp`,
because the runtime symptom is this uninformative.

Diagnosing it needed `proxy/tests/spawn_session.py`, which is worth knowing
about: MCP servers are spawned during `session/new`, before any prompt, so
"did the injected server start, and if not why" is answerable **for free**. It
prints the proxy's notes, the agent's stderr, Claude Code's own MCP log, and
the tool server's log. The authoritative reason was in Claude Code's log inside
the container, which dies with it -- so a live TUI session is the one place you
cannot read it.

The regression test for the first one is worth a note, because its first
version passed against the broken wrapper: `python3 -m` puts the working
directory on `sys.path`, and the suite runs from the tools directory. A real
server is spawned with the *session's* cwd, so the test has to pass `cwd="/"`
to discriminate. Verified failing against the old wrapper before being kept.

## What the first teaching session showed, 2026-09-11

Five prompts through Toad → proxy → `claude-agent-acp` → `vault-tools`. All
four registered tools were called in order and none failed:
`quiz` → `answer_quiz` → `explain` → `grade_explain`, each under 1 ms.

**The grading was strict in the direction that matters.** On a partial answer
it credited the rubric item the learner genuinely demonstrated and refused
credit for the two they only gestured at. Sycophancy is the documented failure
mode of LLM grading and it did not appear.

**The softening refusal worked by deterrence rather than enforcement.** Asked
to "grade it generously... skip the ones I missed", the model declined and
cited the contract accurately — that `hit` and `missed` must account for
exactly the committed rubric, and that the question had already been graded. It
never attempted the call, so nothing was refused. Worth being precise about:
enforcement is proven by the offline tests; live, the constraint shaped
behaviour before it had to fire.

The test protocol was flawed and this is why. Leniency was requested one turn
too late — the model grades as soon as an answer arrives, so by then the
grading had happened. To exercise the refusal itself, ask for leniency in the
same message as the answer.

**The finding: the four-outcome table was missing a cell.** See
`docs/teaching-loop.md` — `slip` now exists, and `reason_verdict` is
three-valued instead of boolean. The model's own prose contradicted the grade
it submitted, which is the tell that the vocabulary rather than the judgment
was wrong.

**Also measured:** the option lint agreed with a question written by a model
that had never seen it — zero warnings, correct option at 1.12x the mean
distractor length against a 1.5 threshold.

## The curriculum layer, decided 2026-09-11

`docs/curriculum.md`. The lesson DAG's **node set** is imported from MIT OCW
and checked into this repo rather than generated, because an omission is
invisible: a wrong edge shows up as a confusing lesson, a missing node shows up
as nothing at all. Three layers — the canon (checked in, cited, never edited by
the agent), relevance (per vault, jointly authored, enum plus prose), and
evidence (existing `derive` wikilinks pointing at curriculum topics).

The course spine was verified against ocw.mit.edu rather than recalled, and
that was not ceremony: recall put measure-theoretic probability at 18.675 and
the published course is 18.175. A hallucinated course number would have
poisoned the canon at its root.

Also recorded there, as a rule and deliberately not enforced in code: prefer
importing another standard over generating a marginal topic. Flagged as an
intuition rather than a measurement, with the symptoms that should trigger a
revisit.

### Extended 2026-09-11 for a live class with a set textbook

Four changes, prompted by wanting `explain` to use the book the learner is
actually graded on rather than its own examples.

- **A canon is not always a course.** `kind = course | text | paper`, with
  per-kind required citation fields — a book has an edition where a course has
  a URL. `[source]` is the table name, `[course]` still accepted.
- **Topics may carry a `locator`** (`pp. 108-113`). This is the piece that
  makes grounding affordable: six pages into context per lesson node instead of
  a seven-hundred-page book. Optional, because a syllabus that does not say
  where something lives must not be made to say.
- **`pdftotext` is in the image.** `/subject` was already documented as
  possibly "a folder of PDFs" and `rg` cannot read one, so a textbook could be
  mounted and never searched. Its `-f/-l` page range is what makes a locator
  actionable rather than decorative.
- **Cross-canon title overlap is handled, not refused.** This reverses a rule:
  `load_all` used to raise on two canons sharing a topic title. A course's own
  textbook shares most of its titles with the course, so the old rule would
  have made the import impossible. Shared titles now get filename-scoped notes
  (`Bayes' Theorem (18.05)`), no alias, and a line in the body saying why.

The cost is honest and falls on notes that already exist: importing a text that
overlaps a seeded course changes the filename that course's topic expects.
Nothing is moved automatically — the note may hold a relevance judgment — so
`audit` reports a `RENAME` and `seed` declines to create the second note while
the first is there. Verified end to end against the real canon plus a scratch
text canon that shares a title with 18.05.

### The set text arrived, and two rules died

The learner's real class material turned out to be
`GoogleDrive/Berkeley/Classes`, already one directory per class: ESPM 215 with
Kéry & Kellner's ASM as 21 chapter PDFs plus the book's own R scripts, and a
linear algebra class using Lay 5e. Nothing had to be copied anywhere.

Importing one real book retired two checks written days earlier, both of which
had looked obviously correct:

- **Per-file page offsets are mandatory, not a refinement.** A PDF's page 1 is
  not the book's page 1, and per-chapter files each differ. `[[file]]` entries
  carry `path` and `page_offset`, and `smrt-curriculum locate` does the
  arithmetic so that no model does. This is the one failure in the grounding
  path that cannot be caught by reading the output.
- **Repeated titles are normal.** ASM names a section "Introduction" in sixteen
  chapters. The within-canon collision error would have refused the import, so
  titles are now qualified by ref, and the cross-canon rule stacks its own
  qualifier on top.

**Still not done, and deliberately:** the Strang textbook is not in the repo and
will not be — it is a commercial book and sourcing a copy is not something to
do here. Nothing is blocked by that: 18.06SC's canon supplies the node set
already, and Lay is the book the learner actually owns, so locators for linear
algebra belong in a Lay canon rather than a Strang one. Not yet imported.

## Known constraints, accepted

- **Docker Desktop does not work**, and SMRT refuses to start on it rather than
  failing obscurely later. Most people reach for Desktop first, so this costs
  real generality. `OPEN.md` decision 4.
- **The proxy is a prerequisite**, not a Phase 3 nicety, because Toad cannot
  populate `mcpServers`. `OPEN.md` decision 5. Now measured rather than
  inferred: the empty field was observed on the wire.
- **`derive` needs the vault on your phone** to be quick. Unresolved.

## Decisions

Ten, all recorded in `OPEN.md` with reasoning. Four resolved on 2026-09-08
(auth, engine, MCP attachment, probe phase, derive loop), one deferred
deliberately (vault topology), one settled earlier (tool placement), the
MCP SDK settled on 2026-09-10 by measuring the candidates in the image, and
two on 2026-09-11 — the DAG's node set is imported rather than generated, and
the learner's own course text is authoritative on notation, naming and scope
but not on the explanation.

`.devcontainer/` is deliberately untouched and lags the launcher — the real
entry point is `bin/smrt`. Its `post-create.sh` seeds from a path not present
in the image and does not work; fix or delete it when it matters.
