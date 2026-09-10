# Verify installs

Agent install paths change often. This file records what was assumed when the
scaffold was written and how to check each one. Update it when something moves.

## What is installed

| Component | Command | Verified 2026-09-09 |
|---|---|---|
| Toad | `pixi global install batrachian-toad` | 0.6.20 |
| Claude Code | `npm install -g @anthropic-ai/claude-code` | 2.1.261 |
| Claude Code ACP adapter | `npm install -g @agentclientprotocol/claude-agent-acp` | launches, negotiates v1 |
| OpenCode | `curl -fsSL https://opencode.ai/install \| bash` | 1.18.28 |
| pixi | `curl -fsSL https://pixi.sh/install.sh \| bash` | 0.79.0 |
| Python | `pixi global install python=3.14` | 3.14.7 |

All six land. Three traps found while confirming it, all now fixed:

**`check.sh` used `bash -lc`.** A login shell sources `/etc/profile`, which
resets `PATH` and discards the image's `ENV PATH`, so everything installed under
`$HOME` reported `MISSING` while being installed and working. It uses `bash -c`
now. If a component ever reports `MISSING`, check `PATH` before believing it.

**OpenCode installs off `PATH`.** The installer succeeds — so the build shows no
warning — but drops the binary in `~/.opencode/bin` and exports `PATH` only from
`.bashrc`, which non-interactive shells never source. `~/.opencode/bin` is now
in the image's `ENV PATH`. The install being non-fatal made this look like a
failed install when it was a visibility problem.

**Claude Code was installed and still unreachable from Toad.** Installing
`@anthropic-ai/claude-code` gets you the `claude` CLI, which does **not** speak
ACP — no `--acp` flag, no stdio server mode. Toad's bundled definition launches
Claude Code as `claude-agent-acp`, a separate adapter package that nothing
installed, so selecting "Claude Code" in Toad's picker could only ever fail.
`check.sh` now reports the adapter as its own row, because "the agent is
installed" and "Toad can drive the agent" turned out to be different claims.

Following Toad's own install action would not have helped: it fetches
`@zed-industries/claude-code-acp`, whose binary is named `claude-code-acp`,
which its own `run_command` never invokes. Install
`@agentclientprotocol/claude-agent-acp` to match what Toad actually runs.

Claude Code's Linux binary is named `claude.exe`. That is upstream's naming, not
a broken install; it runs.

## How to check

```bash
pixi run build
pixi run check
```

`pixi run check` prints the resolved path for each binary or `MISSING`. Installs
in `docker/install-agents.sh` are deliberately non-fatal, so a broken upstream
produces a warning at build time and a `MISSING` here rather than a failed
build.

## If OpenCode is wrong

Fix `docker/install-agents.sh` and rebuild. It sits at the bottom of the
Dockerfile specifically so this doesn't invalidate the layers above it.

## Adding agents at runtime instead

Toad supports 18+ agents through TOML definitions in its agent store, and you
can find, install, and launch them from the Toad UI without touching the
image. Prefer that while you're still deciding what you use.

Ad-hoc agents work too:

```bash
toad acp "some-agent-command"
```

That escape hatch is also how the Phase 3 proxy will be registered.

## ACP version drift

ACP v1 and the v2 draft are diverging. v2 renames `authenticate` to
`auth/login` and `session/load` to `session/resume`, and restructures the
prompt lifecycle so the agent responds once the prompt is *accepted* and then
streams updates.

Nothing in L0 depends on this — Toad handles the protocol. It matters at
Phase 3. Noted here so the surprise is cheap when it arrives.
