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
| Proxy tests | 47/47, in the image (Python 3.14) and on the host (3.10) |
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
- **Every question type.** All seven handlers raise `NotImplementedError`.
- **The teaching loop.** Cannot run until the tool server does.
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
4. **Implement `quiz` and `explain`.** The two that gate everything else.
   `derive` needs the note plumbing, `ask` is trivial. The SDK is settled --
   official `mcp` 2.1.1, `OPEN.md` decision 8, in the image and verified --
   so what remains is the tool surface, and the documented signatures cannot
   be implemented as written. See "The signature hole" below.
   Use `SMRT_TOOLS=./tools smrt` so each edit doesn't cost an image rebuild
   (and `SMRT_PROXY_SRC=./proxy` for the proxy).
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

## Known constraints, accepted

- **Docker Desktop does not work**, and SMRT refuses to start on it rather than
  failing obscurely later. Most people reach for Desktop first, so this costs
  real generality. `OPEN.md` decision 4.
- **The proxy is a prerequisite**, not a Phase 3 nicety, because Toad cannot
  populate `mcpServers`. `OPEN.md` decision 5. Now measured rather than
  inferred: the empty field was observed on the wire.
- **`derive` needs the vault on your phone** to be quick. Unresolved.

## Decisions

Eight, all recorded in `OPEN.md` with reasoning. Four resolved on 2026-09-08
(auth, engine, MCP attachment, probe phase, derive loop), one deferred
deliberately (vault topology), one settled earlier (tool placement), and the
MCP SDK settled on 2026-09-10 by measuring the candidates in the image.

`.devcontainer/` is deliberately untouched and lags the launcher — the real
entry point is `bin/smrt`. Its `post-create.sh` seeds from a path not present
in the image and does not work; fix or delete it when it matters.
