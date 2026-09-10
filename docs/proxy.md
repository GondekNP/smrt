# The ACP proxy

**Status: steps 1 and 2 built and verified 2026-09-09.** The proxy forwards
every method unchanged and injects `mcpServers` into `session/new`. **The
blocker from `OPEN.md` decision 5 is removed** — a model has called a tool
through an injected MCP server. Steps 3-5 are L1 and can wait.

Implementation and its constraints: `proxy/README.md`.

## Why it exists, and why it is not optional

The tool server attaches to a session via the `mcpServers` field of ACP
`session/new`. That field is how the same server works behind Claude Code,
OpenCode, or Codex without writing three integrations.

**Toad 0.6.20 cannot populate it.** It hardcodes the field empty:

```python
# toad/acp/agent.py:748-750
session_new_response = api.session_new(
    str(self.project_root_path),
    [],          # <- mcpServers
)
```

`McpServer` exists in `toad/acp/protocol.py` as a protocol type, but grepping
the package for `mcp` outside those declarations returns nothing: no settings
key, no plumbing, no caller.

So the four question types cannot reach a session until something injects that
field. The proxy is that something. This promotes it from a Phase 3 nicety to a
Phase 1 dependency — see `OPEN.md` decision 5.

Toad is an ACP *client*: it spawns agents as subprocesses and speaks JSON-RPC
over stdio. It has no hook API, and forking an AGPL-3.0 codebase to add one is
work that belongs elsewhere. So the code goes in the wire instead:

```
Toad ──stdio──▶ proxy ──stdio──▶ claude-code | opencode | codex
     ◀─────────       ◀─────────
```

Reached with `toad acp`, which takes an arbitrary command:

```bash
smrt -- toad acp 'smrt-acp-proxy --backend claude' /vault
smrt -- toad acp 'smrt-acp-proxy --backend opencode' /vault
```

There is no registration step, and no TOML agent definition to add. `toad acp`
builds its agent record **in memory** and persists nothing
(`toad/cli.py:166-253`); Toad's agent definitions are TOML bundled inside the
wheel, and it never scans a user directory for more. That turns out to be a
feature here: the proxy is opt-in by construction, because plain `smrt` still
opens Toad's own picker and talks to the backend directly. No flag, no fallback
branch, and no way for a broken proxy to lock you out — which is the risk
recorded at the bottom of this page.

## Scope

Handle five methods. Forward everything else blind.

| Method | Behavior |
|---|---|
| `initialize` | Narrow advertised capabilities. Read-only modes don't advertise write. |
| `session/new` | **Inject `mcpServers`.** Advertise own slash commands. |
| `session/prompt` | The gate. Parse marker, validate, rewrite, or reject. |
| `session/update` | Count writes, accumulate transcript, forward. **Also repairs frames Toad refuses — see below.** |
| `session/request_permission` | Auto-deny out-of-scope paths before a dialog appears. |

Forwarding the rest blind is also the version-drift strategy: ACP v1 and the v2
draft diverge (v2 renames `authenticate` → `auth/login`, `session/load` →
`session/resume`, and restructures the prompt lifecycle). Pin a version, handle
five methods, and most breakage passes through harmlessly.

### Build order within the proxy

1. ~~**Pass-through.**~~ **Done 2026-09-09.** Forwards every method
   unchanged. Verified against a real agent and cross-checked two ways — see
   "What the wire showed" below.
2. ~~**`session/new` injection.**~~ **Done 2026-09-09.** `--mcp NAME=CMD`,
   repeatable, applied to `session/new` *and* `session/load` — Toad passes
   `[]` on resume too, so injecting only into the former would give you tools
   in fresh sessions and lose them on resume.
3. **Slash commands.** Advertise `/tutor`, `/design`, `/expand` on
   `session/new`; filter the backend's own out.
4. **The gate.** Deterministic marker parsing on `session/prompt`. No model.
5. **Trailers and provenance.** Written mechanically, because the proxy is the
   only party that knows the session ID and the real backend model.

Steps 1 and 2 were everything L0 needed, and both are done. Steps 3-5 are L1
and can wait.

One unplanned addition sits alongside them: repairing frames Toad refuses
(`compat.py`). It is not a step in this order and is not meant to become one —
it is a workaround with a retirement plan, described under the `rawOutput`
finding below.

## What the wire showed

Everything on this page used to rest on reading Toad's source. Step 1 turned
the load-bearing parts into measurements. Captured by running Toad headless
(`TEXTUAL_DRIVER=textual.drivers.headless_driver:HeadlessDriver`) against
`opencode acp`, and again against `claude-agent-acp`.

**`mcpServers` really is empty on the wire.** Not inferred from line 750 —
observed:

```json
{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd": "/vault", "mcpServers": []}, "id": 2}
```

So decision 5's premise holds, and step 2 has something concrete to rewrite.

**The negotiated protocol version is 1**, from both backends. Worth having
measured rather than assumed, because Toad sends `1` and then never checks what
comes back (`InitializeResponse` is parsed for capabilities and auth methods
only).

**The proxy is transparent.** Three independent checks, because "the TUI
still worked" is not evidence:

| Check | Result |
|---|---|
| Toad's transcript vs the proxy's trace, handshake only | 5 frames each, same order, same ids, same byte counts |
| Toad → backend direct vs Toad → proxy → backend | identical frame for frame, once session ids are normalized |
| **A real Claude Code session, two prompts, 35s** | 24 comparable frames identical; 20 agent frames byte-verified across 30,694 bytes |

The third is the one that counts. It streamed a reply in three chunks
(`'cla'`, `'ude-s'`, `'onnet-5'`) and both turns closed with
`stopReason: end_turn`, so `session/prompt` and streaming `session/update`
are exercised, not just the handshake.

**A trap for anyone repeating that diff.** Toad logs the requests it *sends*
and everything it *receives*, but not the responses and errors it sends back —
so its transcript was 24 frames where the proxy's trace had 28. The four extra
were Toad's own replies. That is Toad's logging being incomplete, not the proxy
inventing traffic, and it is worth knowing before concluding otherwise.

**Claude Code is reachable now, and was not before.** See the adapter note
below.

**Three interop warts, recorded because the proxy is where they would get
fixed.** None is ours, and only the second loses information:

- `claude-agent-acp` sends `_auth/status_update`, which Toad does not expose,
  so Toad answers `-32601`. It is a *notification*, so answering it at all is
  out of spec — and Toad's reply carries `"id": null`. Seen three times in one
  35-second session.
- **`claude-agent-acp` sends `session_info_update`, and Toad rejects the whole
  notification.** Toad validates `session/update` against a typed union of the
  nine variants it knows (`toad/acp/protocol.py`), and an unknown
  `sessionUpdate` fails that check *before* dispatch — so it does not degrade
  gracefully, it errors and discards the frame. Anything a newer agent adds to
  `session/update` is therefore invisible to Toad.
- **Toad drops every completed tool call, because of one over-narrow type
  annotation.** This is the serious one, and it is on L0's critical path.
  `ToolCallUpdate.rawOutput` is declared `dict` (`toad/acp/protocol.py:215,229,244`)
  while ACP allows any JSON value there. Observed in a 206-frame session:

  | Tool | `rawOutput` sent | Toad |
  |---|---|---|
  | `ToolSearch` | `list` | rejected |
  | `mcp__probe__smrt_probe` | `list` | rejected |
  | `Read` | `str` | rejected |

  Every `tool_call_update` with `status: completed` was refused, so a tool call
  never visibly finishes and its result is never shown. **`rawOutput` is never
  read anywhere in Toad** — `grep` finds it only at those three declarations —
  so the field is pure validation cost, and a proxy that stripped or coerced a
  non-dict `rawOutput` would lose Toad nothing and repair the whole frame.

  It matters here because the teaching loop is entirely tool-driven: `quiz`,
  `explain`, `derive` and `ask` all deliver through tool calls.

  **Shimmed locally 2026-09-10** in `proxy/acp_proxy/compat.py`, which strips a
  non-dict `rawInput`/`rawOutput` on the way to the client. Both fields, in all
  three places they appear — `rawInput` had not fired yet (nine occurrences,
  all dicts) but carries the identical annotation, so it is handled rather than
  left armed.

  Removal rather than coercion because both fields are *optional* in the
  schema: a frame without them is still valid, whereas wrapping a list as
  `{"value": […]}` would validate while lying about the tool's output. And it
  costs Toad nothing, because `rawOutput` is never read anywhere in the
  package.

  Proven by A/B/C against a real Toad and a fake agent
  (`proxy/tests/fake_acp_agent.py`) — no model, no credentials, no terminal:

  | Path | Toad's verdict |
  |---|---|
  | Toad → agent, direct | rejected |
  | Toad → proxy `--no-compat` → agent | rejected |
  | Toad → proxy → agent | **accepted** |

  The middle row is the one that matters: it rules out the proxy being
  incidentally responsible either way.

  **Deliberately not filed upstream yet** — we wanted more confirmation before
  opening an issue on someone else's tracker, and 0.6.20 was the latest release
  with `main` still affected, so there was nothing to wait for. The follow-up
  is recorded as a block comment at the top of `compat.py`: confirm against a
  newer Toad, file it, then **delete the shim**. A workaround left in place
  after upstream heals is how a proxy becomes a second implementation of
  someone else's protocol.
- Toad's `terminal/kill` handler declares its first parameter `sessionID`, not
  `sessionId` (`toad/acp/agent.py:490`), so a spec-conformant agent's
  `terminal/kill` will fail against it.

### Step 2, measured

The injection was verified by the only test that settles it — a real session in
which the model calls a tool that only exists because the proxy put it there:

```
mcp_servers_observed   count=0                    <- what Toad sent
mcp_injected           added=["probe"]  100 -> 191 bytes
```

```
probe log:  spawned -> initialize -> tools/list -> tools_listed -> tool_called
reply    :  'SMRT_PROBE_OK 2026-09-09T19:01:50.486912+00:00'
```

Four separate things had to be true for that token to come back: the frame was
rewritten, the agent accepted the rewrite, it spawned the server as a
subprocess (`cwd: /vault`), and the model chose to call the tool it found
there. `proxy/tests/live_session.py` reproduces it.

That run also brought **`session/request_permission` across the proxy for the
first time** — a tool call triggers it — along with the `tool_call` and
`tool_call_update` update variants. 34 frames in 5 seconds.

### The full TUI session, 2026-09-10

Five prompts through Toad itself: **206 frames, 129 KB, 225 s, largest frame
31 KB.** Two more firsts, and one non-event:

- **`session/cancel` works.** Sent mid-stream at t=34.580, agent answered
  `stopReason: cancelled` at t=34.587 — 7 ms, nothing lost either side. This
  was the likeliest place for a two-thread pump to be wrong, so it is the most
  valuable single result here.
- **The injected tool was called from Toad's own UI**, with a real permission
  dialog rather than a script's auto-approve. The agent named it
  `mcp__probe__smrt_probe`.
- **`fs/read_text_file` never appeared**, even on a prompt that read a file.
  `claude-agent-acp` uses its own `Read` tool instead of delegating to the
  client's fs capability. Later measurement confirmed it never uses `fs/*` at
  all, in either direction, even when the client advertises both capabilities —
  see "Counting writes" below for the design consequence.

  Note that this session's `tool_call` frames appeared to carry no `locations`
  either. That was an artifact of reading only the announcing frame: paths do
  arrive, on the subsequent `tool_call_update`s.

**Still never seen on the wire:** `fs/*`, `terminal/*`, `session/load` (Toad
0.6.20 exposes no resume command), and any frame over 31 KB.

## What reading Toad's source cost us to learn

Four things that are not in Toad's docs and that shape any proxy:

**Toad never drains the agent's stderr.** It reads that pipe exactly once,
after stdout hits EOF, and only on a non-zero exit code
(`toad/acp/agent.py:639-647`). Anything that logs steadily to stderr fills the
pipe buffer and hangs the session. So the proxy's diagnostics go to its trace
file, and it drains the backend's stderr on Toad's behalf. The one exception is
a launch failure, where a bounded line plus a non-zero exit is exactly what
Toad surfaces.

**`TOAD_LOG=<path>` writes a full `[client]`/`[agent]` transcript**
(`toad/acp/agent.py:161-167,247,599`), which `toad replay` consumes. This is
what made the measurements above possible before the proxy existed, and it
remains an independent record to diff a trace against.

**Toad's own frame ceiling is 10 MB** (`limit=10 * 1024 * 1024` on its
`StreamReader`). That is the effective cap on a base64 image block regardless
of what the proxy does.

**Request ids are integers and correlation depends on it** — Toad matches
responses with `isinstance(id, int)` (`toad/jsonrpc.py:439-457`) — and several
calls in one request block go out as a **JSON array on one line**
(`toad/jsonrpc.py:403-417`). Both are handled for free by forwarding raw bytes
rather than re-serializing, which is the transport decision explained in
`proxy/README.md`.

## The Claude Code adapter, which was missing

Toad's bundled definition (`toad/data/agents/claude.com.toml`) launches Claude
Code as `claude-agent-acp`. **That binary was not in the image**, and the
`claude` CLI has no ACP mode of its own — so "Claude Code" in Toad's picker
could never have worked, which is why `docs/status.md` could only ever claim
Toad "reaches the agent picker". `docker/install-agents.sh` now installs
`@agentclientprotocol/claude-agent-acp`.

Toad 0.6.20 is inconsistent here, and following it would not have helped: its
own `install` action fetches `@zed-industries/claude-code-acp`, which provides
a binary named `claude-code-acp` that its `run_command` never invokes.

## Explicitly not building

**No conductor.** The ACP RFD "Agent Extensions via ACP Proxies"
(nikomatsakis) defines a conductor that spawns components and routes
`proxy/successor` messages, so chains can be reordered and swapped through
configuration. Its own stated motivation is an *ecosystem of composable
proxies*.

We have one proxy and will likely always have one. The RFD names the simple
alternative — a proxy that is an ordinary agent managing its own successor —
and criticizes it for requiring each proxy to understand the full chain. With a
chain of one there is no chain to understand, so the criticism does not apply.

Consequences of skipping it, all of them wanted: Python rather than Rust, no
dependency on `proxy/initialize` or `proxy/successor` (which are *proposed*
extensions, not v1 or v2 spec), no tracking of a mid-upstreaming prototype, and
roughly 200 lines against ACP as it exists today. If composability ever becomes
real, migrate once the RFD lands.

Prior art worth knowing regardless: `sacp`, `sacp-proxy`, `sacp-rmcp`,
`sacp-conductor` on crates.io, canonical source `symposium-dev/symposium-acp`,
upstreaming to `agentclientprotocol/rust-sdk`. `acp-go` ships a composable
middleware chain.

Never off the shelf, because it is policy by definition: the gate, marker
parsing, trailer writing, and the discriminator.

## Counting writes: what the wire actually offers

Measured 2026-09-10 with a prompt that created one file and edited another,
against a client advertising **both** `fs` capabilities. The gate's design in
`Scope` above assumed writes would be visible as `fs/write_text_file`; they are
not, and the real signal is different in three ways that matter.

**The `fs` capability is never used.** Zero `fs/write_text_file` and zero
`fs/read_text_file`, even though the client advertised
`{readTextFile: true, writeTextFile: true}` and really implemented both.
`claude-agent-acp` uses its own tools throughout. So a gate keyed on `fs/*`
would read **structurally zero**, not intermittently wrong — reporting "no
writes, within budget" while the agent wrote every file it liked. A gate that
silently passes is worse than no gate.

**The usable signal is `kind` + `locations`, and both are spec-defined**, so
this is portable rather than a Claude-specific hack:

| Field | Value observed |
|---|---|
| `update.kind` | `edit` for both create and modify; also `read`, `execute` |
| `update.locations[].path` | absolute, e.g. `/vault/notes/created.md` |
| `update.rawInput.file_path` | same path, but agent-specific |

**But the detail is not on the frame that announces the tool.** The initial
`tool_call` is a stub — `locations: []`, `rawInput: {}`, and a placeholder
title like `Preparing file…`. Arguments then stream in across successive
`tool_call_update`s, growing one key at a time:

```
tool_call         kind=edit  title='Preparing file…'  locations=[]  rawInput={}
tool_call_update  kind=edit  title='Write notes/created.md'
                  locations=[{path: /vault/notes/created.md}]  rawInput=[file_path]
tool_call_update  ...                                          rawInput=[content, file_path]
tool_call_update  status=completed
```

So a gate must **accumulate per `toolCallId` and judge at `status: completed`**.
Deciding on the announcing frame would decide on nothing at all.

### The hole: `kind: "execute"`

The agent reached for `Bash` unprompted — `ls notes/; cat notes/existing.md` —
to orient itself before writing. Harmless there, and it is the first thing a
write budget has to reckon with, because **a shell command can write anything
and reports `kind: "execute"`, not `edit`.** `echo x > f`, `sed -i`, `tee`,
a script: all invisible to a counter keyed on `edit`.

A budget must therefore treat one `execute` as *unknown and possibly
unbounded*, not as zero. Any other reading makes the count a false assurance,
which is the specific failure this project exists to avoid.

This is survivable only because **the gate was never the enforcement
mechanism.** `/subject` is mounted `:ro`, and that is what actually stops a
write; the gate is advisory plan-discipline layered on top. Worth restating
here, since a reader arriving at this section could reasonably conclude the
safety model had a hole in it. It does not — the mount does not care what an
agent reports.

## The gate, when we get to it

Deterministic first. Almost none of it needs a model.

- Bare prompt, no marker → bounced with "which mode?"
- `/implement` → plan exists, under N lines, declares a file list and budget,
  cites a merged design doc. Four greps.

**When it refuses, it emits two or three specific questions and stops.** It must
not draft the answer, or the word-vomit problem has been recreated one level up
with a nicer interface.

Build `/force` deliberately and **log every use**. Bypassing 80% of the time
means the gate is miscalibrated; 5% means it is working. Without the log you
will never know which, and you will either suffer it or delete it.

## Risks

**It sits in front of everything.** A broken proxy means no agent access at
all, including the working auth path. So `bin/smrt` must keep launching Toad
against Claude Code directly, and that fallback should stay the default until
the proxy has earned promotion. Do not make the proxy the only route.

> Resolved by construction, not by discipline. Toad reaches the proxy only
> through `toad acp '<command>'`, which persists nothing, so plain `smrt` is
> untouched and still goes direct. There is no flag to forget and no default to
> regret.

**It is a second process to authenticate.** The container-scoped OAuth session
lives in `$SMRT_STATE/agents`; the proxy spawns the backend and must not
disturb that.

> Handled by inheriting the environment and cwd unchanged, so the backend finds
> credentials via `$HOME` exactly as it would if Toad had spawned it. Confirmed
> negatively as well: run against an empty `~/.claude` and the adapter reports
> `{"kind": "none", "label": "Not logged in"}` rather than picking anything up
> from elsewhere.

**ACP version drift.** Pin a version. See above.

> The proxy pins 1 as documentation, not as enforcement: it records the
> negotiated version in the trace instead of refusing a mismatch. Refusing
> would make the proxy a new way for a session to fail, which is the one thing
> it must not become.
