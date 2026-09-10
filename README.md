# SMRT

**Show My Reasoning Toolkit**

![2026 AI-driven Development, in a nutshell](assets/homer.png)

> "I am so smart! I am so smart! S-M-R-T! …I mean, S-M-A-R-T."
> — Homer Simpson

A containerised environment for learning and design work with AI agents,
where the agent's job is to make you reason rather than to reason for you.

The missing letter is **A, for ~~Autonomous~~.** Cuz it's not!

---

## The problem

Modern AI tools have their own approaches to a `PLAN` mode, where in theory,
`claude`, `codex`, etc, will take your loosey-goosey design ideas (whether or not
they are well-formed or they are word salad) and create a very polished looking
and oftentimes overengeered solution to meet your needs. The result is fire-hose
engineering, where the moment a need is articulated, it is met in the codebase with
a 1500-line PR. This is the (now classic) issue that it is far far easier to create 
PRs with AI tools than it is for humans to review them, leading to burnout and/or
rubber-stamping, depending on your temperament. 

This tool (designed primarily with myself in mind and hopefully more generally useful)
is aiming to address that problem by way of a very deliberate split between reasoning 
and implementation, where AI can help to bring some clarity to a large codebase or provide
some basic summarization, but will reject your futile attempts to ask nicely to 'do this
thing plz'. 

## The approach

**Write scope is the enforcement mechanism.** Every constraint here is a
mount flag, not an instruction in a prompt. Subject material is mounted
read-only. An agent that cannot write cannot run ahead of you, and it cannot
be talked out of that.

**Answers have to be earned.** The teaching loop grades free responses
against a rubric committed *before* you see the question, to avoid passing a hand-wavy answer. Multiple choice requires a pick *and* a justification, graded
separately, which distinguishes "correct" from "correct for the right reason." (Further
versions might want to codify actually 'right' answers from MOOC style sources but
for now, out of scope)

**Plan before approval.** Sessions present a dependency graph and stop. A
wrong root is cheap to fix before the work and expensive during it.

**Verify before asserting.** The moment the agent is even slightly unsure of
a fact, it checks rather than recalls. One confidently delivered
hallucination poisons trust in everything else it says.

## Design

A Debian container with [Toad](https://github.com/batrachianai/toad) — a
terminal UI that fronts any ACP-compatible agent — plus Claude Code and
OpenCode, over a markdown vault you can open in Obsidian.

| | |
|---|---|
| **Writes** | `/vault` |
| **Reads** | `/vault`, plus an optional read-only `/subject` |
| **Runs** | Nothing. It reads and writes markdown. |

The subject can be anything: a code repository, a KiCad project, a folder of
PDFs, a directory of papers, or nothing at all. **The teaching skill assumes
nothing about it beyond "files exist there."** The moment it branches on "if
this is a Python repo, do X," it has stopped being general purpose.

---

## Install

```bash
git clone <this-repo> smrt && cd smrt
pixi run build
ln -s "$PWD/bin/smrt" ~/.local/bin/smrt
```

Then point it at a vault:

```bash
mkdir -p ~/vault && cp -r vault-template/. ~/vault/
mkdir -p ~/.config/smrt && echo "SMRT_VAULT=$HOME/vault" > ~/.config/smrt/config
```

## Use

The subject defaults to your current directory, so the common case is just:

```bash
cd ~/code/some-project
smrt
```

Everything else:

```bash
smrt ~/code/thing          # explicit subject
smrt --no-subject          # vault only, e.g. learning linear algebra
smrt --vault ~/other       # different vault this run
smrt --shell               # bash instead of toad
smrt -- python -m vault_tools.server
```

Environment knobs:

```bash
SMRT_DOCKER_CONTEXT=default   # which engine. pinned, not ambient.
SMRT_HOST_AUTH=1              # reuse the host's Claude Code session
SMRT_TOOLS=./tools            # live-mount the tool server, no rebuild
SMRT_PROXY_SRC=./proxy        # live-mount the ACP proxy, no rebuild
SMRT_REPROBE=1                # re-run the cached engine preflight
SMRT_SKIP_PREFLIGHT=1         # skip it entirely
```

To go through the ACP proxy instead of straight to the agent, which is what
attaches an MCP tool server — Toad cannot do it alone:

```bash
smrt -- toad acp 'smrt-acp-proxy --backend claude --mcp probe=smrt-mcp-probe' /vault
```

Nothing routes through the proxy unless you ask for it that way. Drop the
`--mcp` and it is a transparent pass-through.

## Invoking it directly

`bin/smrt` is a thin wrapper over `docker run`. Nothing is hidden, and you can
skip it entirely:

```bash
docker run --rm -it \
  -v "$HOME/vault:/vault" \
  -v "$PWD:/subject:ro" \
  -v "$HOME/.local/share/smrt/agents:/home/smrt/.claude" \
  -v "$HOME/.local/share/smrt/claude.json:/home/smrt/.claude.json" \
  -v "$HOME/.local/share/smrt/toad:/home/smrt/.config/toad" \
  -v "$HOME/.local/share/smrt/state:/home/smrt/.local/state" \
  -e TERM -e COLORTERM=truecolor \
  -e VAULT_ROOT=/vault -e SUBJECT_ROOT=/subject \
  -w /vault \
  smrt:latest toad /vault
```

Four things in there matter, and they're the only four:

1. **`/vault` is read-write.** Your notes. Obsidian reads the same directory
   from the host, so the container never renders anything.
2. **`/subject` is `:ro`.** This is the entire safety model. Drop the flag and
   you've deleted the point of the project.
3. **The state mounts give the container its own OAuth session.** You run
   `/login` inside it once; the credentials persist in `$SMRT_STATE` and never
   touch your host's Claude Code config. Interactive tutoring is
   token-intensive enough that subscription pricing decides this, and
   container-scoped credentials are revocable on their own. Both `.claude/`
   and `.claude.json` are needed — Claude Code splits its state across them.
4. **`TERM` passthrough.** Toad is a Textual TUI and needs a capable
   terminal. Its README specifically warns that macOS Terminal.app degrades
   badly; Ghostty, Kitty, WezTerm and Alacritty are all fine.

Omit the `/subject` line for a vault-only session. Nothing depends on the
subject existing, the assumption is that /subject is a read-only mount dir
that contains some useful context for the problem (for eg, a repo, a series
of pdfs, etc).

## The devcontainer

`.devcontainer/` is optional scaffolding and uses the **same Dockerfile** as
`bin/smrt`, so switching between them changes nothing about the environment.

It goes through Compose rather than devcontainer mounts for a specific
reason: `devcontainer.json`'s `${localEnv:VAR}` has **no default syntax**, so
an unset path becomes an empty bind source and container creation fails
outright. Compose supports `${VAR:-default}`, and `initialize.sh` runs on the
host beforehand to guarantee every bind source exists.

Consequence: a fresh clone opens with **no configuration at all**. The vault
defaults to a scratch copy of `vault-template/`, and the subject defaults to
the repo itself, so SMRT becomes its own first subject. Override with
`SMRT_VAULT` and `SMRT_SUBJECT` in your shell and `initialize.sh` picks them
up.

---

## Layout

```
bin/smrt                   the launcher. thin wrapper over docker run.
pixi.toml                  task names. substance lives in scripts/.
scripts/                   build, check, clean
docker/Dockerfile          the image. one source of truth.
docker/install-agents.sh   agent installs, split out because they churn
.devcontainer/             optional. same Dockerfile, via compose.
tools/                     MCP tool server — signatures only, placeholder
proxy/                     ACP proxy — pass-through + mcpServers injection
vault-template/            seed contents for a fresh vault
  templates/               note schemas the tool server reads and writes
docs/                      reasoning, decisions, status
```

Tasks:

```
pixi run build | rebuild | check | test-proxy | lint | clean
```

pixi holds the names, bash holds the substance — every task is a call into
`scripts/`, runnable directly if you'd rather skip pixi.

## The tool server

`tools/` defines the interaction surface: `quiz`, `explain`, `derive`, `ask`,
`submit_artifact`, `record_grade`, `md_log`. It attaches via the `mcpServers`
field of ACP `session/new`, so it works identically regardless of which agent
is behind Toad.

**Currently a placeholder.** Signatures and docstrings, every handler raising
`NotImplementedError`. That's deliberate — the signatures are the thing worth
arguing about before any of it is real.

Attaching it needed infrastructure, because **Toad hardcodes `mcpServers` to
`[]`** — verified on the wire, not assumed. `proxy/` injects it, and that now
works end to end: a model has called a tool through an injected MCP server. So
the only thing left between these signatures and a working teaching loop is
implementing them. See [`docs/proxy.md`](docs/proxy.md).

## Before you rely on this

**Docker Desktop does not work** — it serves bind mounts root-owned, so the
vault is unwritable. `bin/smrt` pins a plain engine and refuses to start
otherwise, with instructions. See [`docs/OPEN.md`](docs/OPEN.md) decision 4.

[`docs/status.md`](docs/status.md) is the honest account of what is verified,
what isn't, and what happens next. The tool server is still a placeholder, so
the teaching loop does not run yet.

Agent install paths churn; [`docs/verify-installs.md`](docs/verify-installs.md)
records what was assumed and how to check each one. `pixi run check` prints
what actually landed in the image — including `claude-agent-acp`, the adapter
Toad needs to reach Claude Code and which was silently absent until
2026-09-09.

## Docs

- [`docs/status.md`](docs/status.md) — what is verified, what isn't, what's next
- [`docs/teaching-loop.md`](docs/teaching-loop.md) — probe → plan → teach, and
  the four question types
- [`docs/environment.md`](docs/environment.md) — why each image choice
- [`docs/auth.md`](docs/auth.md) — container-scoped OAuth, and the opt-out
- [`docs/proxy.md`](docs/proxy.md) — the ACP proxy, and why it's a prerequisite
- [`proxy/README.md`](proxy/README.md) — how the proxy works, and the three
  constraints that shape it
- [`docs/OPEN.md`](docs/OPEN.md) — every decision, with reasoning

## Credit

The teaching philosophy derives from
[amosblomqvist/learn](https://github.com/amosblomqvist/learn), which is
calibrated for `@amosblomqvist` themself and served as inspiration for this repo, and will
almost certainly change as my usage increases. Also inspired somewhat by recent LLM usage
policies put forth by the Rust team 
(see [Rust's LLM Usage Policy](https://blog.rust-lang.org/inside-rust/2026/08/05/rust-langrust-is-adopting-an-llm-policy/))
