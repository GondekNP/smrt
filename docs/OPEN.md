# Open decisions

Six decisions, three resolved on 2026-09-08 and recorded in place below.
Decisions 4 and 5 were found while testing the L0 scaffold rather than while
designing it.

Resolve each by editing this file in place: strike the rejected options, keep
the reasoning, and note the date. This file is the record of why the setup
looks the way it does.

---

## 1. Auth — how Claude Code authenticates inside the container

**Status:** unresolved. Scaffold currently assumes the API key path.

| Option | For | Against |
|---|---|---|
| **API key in env** | Clean, explicit, works headless, trivially revocable, same mechanism CI will use in Phase 4 | Separate billing from your subscription; key sits in `.env` and in the process environment |
| **Mount host OAuth config** | Uses your existing subscription; no key management | Puts host credentials inside the container's reach; awkward for the eventual headless/CI path; refresh behaviour across a bind mount is untested |

Consideration that may decide it: Phase 4 runs agents headless in CI, which
requires a key regardless. Choosing the key here means one auth mechanism
across all layers rather than two.

**Decision (2026-09-08): OAuth, but the container's own — not the host's.
Keys retained for headless.**

The options as originally framed were a false choice. They assumed OAuth meant
*mounting the host's* config, so the table traded cost against credential
scope. A third option does both: authenticate **inside** the container with
`/login`, and persist the result in `$SMRT_STATE`.

- Subscription pricing, because tutoring is token-intensive by construction —
  probing, rubric grading, and re-verifying claims all spend tokens to produce
  small outputs. A per-token key is the wrong instrument.
- Container-scoped credentials, because a container is a wider blast radius
  than a laptop. Delete `$SMRT_STATE/agents` and only the container's access is
  gone; the host session was never involved.

Headless keeps the key path, since an OAuth session cannot work unattended:
Phase 4 CI uses a key, and OpenRouter + OpenCode covers the blitz, where
running the adversary on a different model is the point.

`SMRT_HOST_AUTH=1` mounts the host's `~/.claude` instead, for people who would
rather not authenticate twice and accept that the container can then read their
live host token. Offered, not defaulted.

Two implementation notes found while wiring this up:

- Claude Code splits its state. Credentials are in `~/.claude/`, but onboarding
  state and project history are in `~/.claude.json`, which sits *beside* that
  directory. Persist both or you re-onboard every launch.
- The `claude.json` mount source must be pre-created. Bind-mounting a
  nonexistent source makes Docker create a **directory**, and Claude Code then
  fails on a file it cannot parse.

---

## 2. Vault topology — one repo or one per subject

**Status:** unresolved. Scaffold assumes one vault.

| Option | For | Against |
|---|---|---|
| **One vault** | One graph, cross-links between subjects work naturally, one Obsidian window, one git history | Grows without bound; unrelated subjects share a history |
| **Per-subject vaults** | Clean separation, easy to share or archive one subject | Cross-linking breaks, multiple Obsidian instances, the `--subject` crossover case gets awkward |

The design doc's argument for one vault: the crossover case — launching a
learning session with `--subject ~/code/meta` and having notes and design
context land in the same graph — only works if there is one graph. That was
the whole reason not to build a crossover feature.

Counter-consideration: linear algebra notes and OS-internals notes may never
usefully link, in which case the shared graph buys nothing and costs
searchability.

**Decision (2026-09-08): deferred, deliberately.**

Nothing downstream is blocked, and `bin/smrt --vault` already overrides per
run, so this stays cheap to reverse. Deciding now would be guessing; the
question answers itself once two subjects exist and either do or don't link.

---

## 3. Tool server placement — in-container or host socket

**Status:** unresolved. Scaffold assumes in-container.

| Option | For | Against |
|---|---|---|
| **In-container** | Simple, no host dependency, ships with the image, same in CI | Rebuild to iterate on tool code; can't reach host-only resources |
| **Host over socket** | Edit tools without rebuilding; can reach host apps (screenshot, clipboard, camera for `derive` submissions) | Another moving part; breaks the isolation property; needs a socket mount |

Relevant to `submit_artifact`: if you photograph derivations with a phone and
they sync to the vault, in-container is fine — it's just a file read. If you
want the tool to *capture* something from the host, you need the socket.

Worth noting the tool server is the **only component shared between L0 and
L1**, so whatever you decide here you inherit at the design layer.

**Decision (2026-09-08): in-container.**

It is also the only option that survives Phase 4, where a headless CI job has
no host to talk to. The path-escape guard in `submit_artifact` already holds:
`../../etc/passwd`, `/etc/passwd`, and `notes/../../etc/passwd` all raise
before reading.

The listed cost — "rebuild to iterate on tool code" — is real and is mitigated
rather than accepted: `SMRT_TOOLS=<dir>` live-mounts a checkout over the baked
copy, so implementing the tools does not mean a rebuild per edit. Read-only, so
the container still cannot alter your working tree.

**How the image gets into the vault is a separate question**, settled in
decision 7. Placement here is about where the tool *runs*; no host socket is
wanted, and webcam access specifically is declined.

---

## 4. Container engine — which one `smrt` is allowed to use

**Status: resolved 2026-09-08. Found while testing, not while designing.**

`bin/smrt` called bare `docker run`, so it inherited whichever context happened
to be active. That is not a safe input, because the mount semantics SMRT
depends on are not the same across engines.

**Docker Desktop on Linux breaks the writable half of the model, two ways:**

| Symptom | Detail |
|---|---|
| Ownership squashed | Bind mounts arrive over virtiofs owned by `root:root` regardless of host ownership, so the container user cannot write to `/vault` at all |
| Outright hang | On a host path not already in Desktop's file-sharing set, `docker run` never starts — container stuck in `Created`, surviving `timeout` |

The first symptom also makes the `USER_UID`/`USER_GID` build args a silent
no-op. Their entire stated purpose in `environment.md` is preventing exactly
the ownership mismatch that virtiofs then reintroduces.

Verified in both directions: the identical mount fails under `desktop-linux`
and succeeds under `default` (plain engine), with the host file correctly owned.

| Option | For | Against |
|---|---|---|
| Pin a context | Predictable; one line | Ignores the user's own choice; hardcodes one known-bad product by name |
| Detect and refuse | Explicit, teaches the constraint | Fixes nothing on its own |
| Root entrypoint that `chown`s `/vault` | Engine-agnostic | Needs root in the container, undercutting the non-root design; rewrites ownership of your real vault |

**Decision: pin, and additionally probe what the engine actually does.**

`SMRT_DOCKER_CONTEXT` defaults to `default` and is overridable. A preflight then
tries a real write into the mounted vault from inside a container and fails
loudly with the diagnosis and remedies if it can't.

The probe matters more than the pin. Matching on a context *name* would
hardcode one vendor's current bug; probing behaviour keeps the check
meaningful on podman, rootless docker, or whatever comes next. It is bounded by
`timeout` because the Desktop failure mode is a hang rather than an error, and
`SMRT_SKIP_PREFLIGHT=1` bypasses it.

**Known cost to generality, accepted:** most people who run dev environments
reach for Docker Desktop, and SMRT will refuse to start for them until they
point it at a plain engine. Failing loudly with an explanation is still better
than the alternative, which is cryptic permission errors deep in a session.
Revisit if Docker Desktop's Linux file sharing ever preserves ownership.

---

## 5. MCP attachment — how the tool server reaches a session

**Status: decided 2026-09-08. Found while testing. This one re-orders the build
plan.**

README and the design doc both state the tool server attaches via the
`mcpServers` field of ACP `session/new`, and that this uniformity across
backends is *the reason* to build it as MCP rather than as agent-specific
extensions.

**Toad 0.6.20 cannot do this.** It hardcodes the field empty:

```python
# toad/acp/agent.py:748-750
session_new_response = api.session_new(
    str(self.project_root_path),
    [],          # <- mcpServers
)
```

`McpServer` exists in `toad/acp/protocol.py` as a protocol type, but grepping
the package for `mcp` outside those type declarations returns nothing: no
settings key, no config plumbing, no caller that populates it.

| Option | For | Against |
|---|---|---|
| Claude Code's own MCP config | Works today, zero infrastructure | Agent-specific — the exact thing MCP was chosen to avoid; no OpenCode |
| **Build the proxy now** | Matches design intent; `session/new` injection is row 2 of the §7 proxy table | ~200 lines of ACP work before any question type is validated |
| Upstream a PR to Toad | Fixes it for everyone | Timing outside our control; blocked meanwhile |
| Fork Toad | Full control | AGPL-3.0; the design doc already rejects forking Toad for behaviour that belongs elsewhere |

**Decision: build the proxy now.**

The agent-specific shim is throwaway work, and the proxy has to exist anyway.
Pulling it forward also makes the first end-to-end exercise a real one, through
the same wire that L1 and L2 will use, rather than through a path that gets
deleted.

Consequence worth stating plainly: this promotes the proxy from Phase 3 to a
Phase 1 dependency, and answers the README's own hedge that the proxy might be
"a fun project rather than a necessary one." It is necessary. Scope stays as
designed — simple cascading proxy, no conductor, deterministic gate only, no
model in the loop.

**Update 2026-09-09: the premise is now measured, not inferred.** This decision
rested on reading line 750 of Toad's source. The pass-through proxy recorded
the frame as Toad actually sends it:

```json
{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd": "/vault", "mcpServers": []}, "id": 2}
```

Worth having done, because the decision that reorders a build plan is the one
you least want resting on a source read. The other assumption checked at the
same time — that the negotiated protocol version is 1 — also held, against both
backends.

**Resolved in full 2026-09-09.** Both proxy steps this decision depends on are
built and verified: the pass-through, and the injection itself. A model has
called a tool through an MCP server that reached the session only because the
proxy put it in `session/new`. The tool server is no longer blocked by
infrastructure — only by being a placeholder. `docs/proxy.md`.

---

## 6. Probe phase — does it survive for code tutoring

**Status: resolved 2026-09-08.**

`teaching-loop.md` and `skills/teach/SKILL.md` contradicted each other: the
first said to drop the probe phase for code tutoring, warning that the source
skill's calibration would "feel patronizing within a day" pointed at your own
codebase; the second mandated probing unconditionally.

**Decision: probe unilaterally. Relax later if it grates.**

Two reasons. Skipping probing for code would require the skill to branch on
subject type, which the `/subject` constraint forbids outright — that rule is
what keeps a KiCad project and a folder of PDFs working. And the costs are
asymmetric: a few redundant questions are cheaper than a lesson pitched at the
wrong level, which is the failure the probe phase exists to prevent.

Both documents now say this. Revisit from experience, not from theory.

---

## 7. The `derive` loop — how a submission is made and recorded

**Status: resolved 2026-09-08.**

The original flow was `submit_artifact("attachments/hessian-01.jpg")`: a bare
file path, read once, graded in chat. That works and leaves nearly no record —
the image sits orphaned in `attachments/`, and the grading exists only in a
transcript.

An `attachments/`-watcher ("grade the newest image") was considered and
rejected. It shortens typing but makes the record worse, because nothing then
connects an image to the question it answers.

**Decision: the note is the submission.**

`derive` writes a note into the vault; you attach the photo into that note the
way you attach anything in Obsidian; the tool resolves the `![[...]]` embed and
appends grading to the same note.

```
derive()          -> notes/.../derive-007.md, front matter with rubric_sha256
you               -> attach photo under "## Attempt" (desktop or mobile)
you               -> "done", in conversation
submit_artifact() -> resolves the embeds, returns image blocks
record_grade()    -> "## Grading" callouts, sets status / score / rubric
```

Why this and not a shorter path: the record is the point. Task, attempt and
grading end up in one note, in the graph, backlinked to the concept, and in git
history because the vault is a repo. Front matter makes it queryable — Dataview
answers "every derivation I got wrong" — which is what turns a pile of sessions
into a learning record. That was the actual goal; capture convenience was a
proxy for it.

Two constraints that fell out, both now encoded in the signatures:

- **Nothing blocks.** MCP is request/response, so a `derive` that waited for a
  photo would wedge the session. It writes the note and returns; the waiting is
  conversational.
- **Pre-commitment is verifiable.** `rubric_sha256` is written before you see
  the task, the plaintext `rubric` only after grading. Plaintext up front would
  spoil the exercise; plaintext only afterwards would make the pre-commitment
  unfalsifiable. The hash gives both, and since the default failure of LLM
  grading is sycophancy, a bar that is *provably* fixed in advance is doing
  real work. Same rule now applies to `explain`.

**Transport remains separate and is not solved by this.** The note flow fixes
the record; the photo still has to reach the vault. The native answer is
Obsidian mobile on the same vault — open the note on the phone, attach, shoot —
which needs the vault synced there and therefore touches decision 2. Webcam and
other host-device access stay declined.

## Still genuinely open

- **Vault sync to phone**, which is what makes the `derive` loop actually short.
  Obsidian Sync, Syncthing, or self-hosted LiveSync. Interacts with decision 2:
  one vault means the phone carries every subject.
- **Which MCP SDK** the tool server is built on. Unforced so far, on purpose:
  the injection was proven with a hand-rolled probe server, so this gets
  decided when tools that matter get written, against wiring already known
  good.
- **Whether to report Toad's `rawInput`/`rawOutput` annotation upstream.**
  Deferred deliberately on 2026-09-10 — we shimmed it locally rather than
  opening an issue on someone else's tracker without more confirmation. See
  the deferred-follow-ups section of `status.md`; the shim has a retirement
  plan attached.
- **`md_log` granularity**: one file per session, or append to a daily note.
- **Whether `quiz` grades the justification with a model** or just records it.
