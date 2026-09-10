# The ACP proxy

A transparent proxy on stdio between an ACP client and an ACP agent.

```
Toad ──stdio──▶ smrt-acp-proxy ──stdio──▶ claude-agent-acp | opencode acp
     ◀─────────                ◀─────────
```

**Steps 1 and 2 of the build order in `docs/proxy.md`:** it forwards every
method unchanged, and injects `mcpServers` into `session/new`. The second is
the only reason this component exists — Toad hardcodes that field empty, so
without it the vault tool server cannot reach a session at all. See
`docs/OPEN.md` decision 5.

The order was deliberate. Pass-through first, proven transparent, *then* the
one frame that gets rewritten — so a failure in the rewriting could never be
confused with a failure in the transport.

## Running it

```bash
smrt-acp-proxy --backend opencode
smrt-acp-proxy --backend claude
smrt-acp-proxy -- <any ACP agent command...>
```

`--` is the primary form; `--backend` is shorthand for the two adapters present
in the image. Through Toad, which takes an arbitrary command:

```bash
smrt -- toad acp 'smrt-acp-proxy --backend opencode' /vault
```

Nothing routes through the proxy unless you launch it this way. Plain `smrt`
still opens Toad's own agent picker and talks to the backend directly, which is
the fallback `docs/proxy.md` insists on keeping:

> A broken proxy means no agent access at all… Do not make the proxy the only
> route.

## Injecting MCP servers

`--mcp NAME=COMMAND`, repeatable:

```bash
smrt -- toad acp 'smrt-acp-proxy --backend claude --mcp probe=smrt-mcp-probe' /vault
```

Quote the whole spec if the command takes arguments —
`--mcp 'probe=python3 -m acp_proxy.mcp_probe'` — which is why the things worth
injecting get their own wrapper on `PATH`: nested quoting inside
`toad acp '...'` is unpleasant.

Three behaviours worth knowing:

- **`session/load` is injected too**, not just `session/new`. Toad passes `[]`
  on resume as well, so doing only the latter would give you tools in fresh
  sessions and silently lose them when you resumed one.
- **The client's own entries win.** Ours are appended, and a name the client
  already declared is left alone. Toad sends `[]` today; a future Toad, or a
  different client, may not.
- **The command is resolved to an absolute path at startup, and a missing one
  is a hard failure.** The ACP schema asks for an absolute path, and failing
  here turns a typo into an immediate error rather than an MCP server that
  silently never appears in the session — which is miserable to debug from the
  inside.

Injection is **fail-safe**: anything unexpected about the frame, up to and
including an exception, forwards the original bytes untouched and records
`inject_failed` in the trace. Losing the tool server is recoverable; losing the
session is not. The corollary is that a bug in the injection shows up as
*missing tools*, not as an error — that trace note is the only tell, and it is
how a real name-comparison bug was caught during development.

## Proving it works: `smrt-mcp-probe`

A deliberately pointless MCP server (`acp_proxy/mcp_probe.py`) exposing one
tool and logging everything that happens to it. It answers a question the unit
tests cannot: not "was the frame rewritten" but "did the agent spawn the server
and did the model call the tool".

```bash
smrt -- python3 /workspace/proxy/tests/live_session.py
```

That drives one real session as an ACP client — no TUI needed — and prints the
probe's log beside the model's reply. It costs a model call and needs a
logged-in backend, which is why it is not in the unit suite. Being a client
rather than a TUI also exercises the inbound half of the protocol, including
`session/request_permission`, which a tool call triggers.

Replaced by `tools/vault_tools/server.py` once that stops raising
`NotImplementedError`.

## Repairing frames Toad refuses

**`compat.py` is a workaround with a follow-up attached, not a feature.** Read
the block comment at the top of it before building on it.

Toad annotates `rawInput`/`rawOutput` as `dict` where the reference schema says
`Option<serde_json::Value>`, and validates `session/update` against that type
*before* dispatch — so a conformant agent sending a list or string there has
its whole frame discarded. In practice that meant **every completed tool call
was dropped**, which matters because the teaching loop delivers entirely
through tool calls.

On by default; `--no-compat` turns it off, which is also how you check whether
it is still needed after a Toad upgrade. Every repair is recorded as
`compat_repaired`, so the shim is never silent — a shim you cannot see is a
shim you cannot retire.

## Traces

Every frame is recorded as JSONL, by default under
`$XDG_STATE_HOME/smrt/acp/` — which `bin/smrt` mounts out of the container, so
traces are readable on the host. `--trace PATH` to redirect, `--no-trace` to
turn it off, `$SMRT_ACP_TRACE` to set a path by environment.

```bash
jq -r '[.dir, .kind, .method // .event // "-"] | @tsv' \
  ~/.local/share/smrt/state/smrt/acp/acp-*.jsonl
```

Alongside the frames, the proxy emits notes for the things worth knowing
without a `jq` incantation:

| Event | Answers |
|---|---|
| `mcp_servers_observed` | what the client really sent, before any rewriting |
| `mcp_injected` | what we added, and the frame as forwarded |
| `compat_repaired` | which unusable field was stripped, and how often |
| `inject_failed` / `compat_failed` | a rewrite gave up and forwarded the original — the only tell |
| `protocol_version_negotiated` | what version did the agent actually agree to? |

The first and last were previously inferred from reading Toad's source; both
are now measured. Toad also writes its own `[client]`/`[agent]` transcript when
`TOAD_LOG` is set, which makes it an independent record to diff a trace
against — though note it logs the requests it *sends* and everything it
*receives*, but not the replies it sends back, so its frame count runs lower
than a trace's.

**A trace contains full prompt and response content.** It is a debugging
artifact, not something to paste into an issue.

## Three constraints the implementation is shaped by

These are not stylistic. Each one was found by reading Toad 0.6.20, and each is
easy to reintroduce by accident.

**1. Frames are forwarded as the original bytes.** Only a frame the proxy
deliberately changes gets re-serialized. A parse-and-re-serialize pass-through
tests identically and then quietly becomes a second source of failure: unknown
fields from a newer ACP version, number formatting, unicode escaping, integer
request ids (Toad correlates responses with `isinstance(id, int)`), and batch
arrays sent as one line. The documented drift strategy is "handle a few
methods, let the rest through untouched", so the transport must be *incapable*
of mangling a method it does not understand.

**2. Sustained output on stderr deadlocks the session.** Toad pipes the agent's
stderr and reads it exactly once — after stdout hits EOF, and only on a
non-zero exit (`toad/acp/agent.py:639-647`). Steady logging there fills the
pipe buffer and blocks forever. So diagnostics go to the trace, and the
backend's own stderr is drained by the proxy and filed there too, never
relayed. The single exception is a launch failure: one bounded line plus a
non-zero exit is the one case Toad surfaces.

**3. Threads, not asyncio.** `asyncio.StreamReader` caps a line at 64 KiB by
default and raises above it. ACP prompts carry base64 image blocks — exactly
what `submit_artifact` will return — so real frames exceed that. Toad raised
its own limit to 10 MB, which is also the effective ceiling on a frame no
matter what the proxy does. `io.BufferedReader.readline()` has no cap.

## Development

The source is live-mountable, so editing it costs no rebuild — the same
mitigation `SMRT_TOOLS` provides for the tool server:

```bash
SMRT_PROXY_SRC=./proxy smrt -- toad acp 'smrt-acp-proxy --backend opencode' /vault
```

Tests are stdlib-only and need no Docker, no agent, and no credentials:

```bash
pixi run test-proxy          # inside the image, against its real interpreter
cd proxy && python3 -m unittest discover -s tests -t .
```

They assert transparency, including the cases a re-serializing proxy would fail
while looking correct: odd whitespace, a float's trailing zero, a one-line
batch array, an integer id, a frame over 64 KiB, and a backend flooding stderr.
`test_inject.py` adds the injection, and most of it is about what did *not*
change — the arrival of the first rewritten frame is exactly the moment the
byte-faithful property could quietly be lost.
