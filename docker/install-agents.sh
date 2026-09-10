#!/usr/bin/env bash
# Install the coding agents Toad will front.
#
# This is a separate script on purpose: agent install paths change often, and
# you will want to edit this without invalidating the whole Docker layer cache
# above it. Each install is non-fatal so a single broken upstream doesn't
# block the image build — check `toad` on first run to see what actually
# landed.
#
# VERIFY BEFORE TRUSTING: see docs/verify-installs.md. The Claude Code package
# name is stable; the OpenCode install path is the one most likely to be wrong.

set -uo pipefail

log() { printf '\n=== %s\n' "$*"; }

# --- Claude Code -----------------------------------------------------------
log "Installing Claude Code"
npm install -g @anthropic-ai/claude-code || echo "WARN: Claude Code install failed"

# --- Claude Code ACP adapter -----------------------------------------------
# The `claude` CLI does not speak ACP — no --acp flag, no stdio server mode —
# so Toad cannot drive it without an adapter. Toad's bundled definition
# (toad/data/agents/claude.com.toml) sets run_command to the bare string
# `claude-agent-acp`, so THIS package is the one that matches. Without it,
# picking "Claude Code" in Toad fails at launch.
#
# Note Toad 0.6.20 is internally inconsistent here: its own `install` action
# still fetches @zed-industries/claude-code-acp, which provides a differently
# named binary (`claude-code-acp`) that its run_command will never invoke.
log "Installing the Claude Code ACP adapter"
npm install -g @agentclientprotocol/claude-agent-acp \
    || echo "WARN: claude-agent-acp install failed — Toad cannot reach Claude Code"

# --- OpenCode --------------------------------------------------------------
# Two documented paths. Try the official installer, fall back to npm.
log "Installing OpenCode"
if curl -fsSL https://opencode.ai/install | bash; then
    echo "OpenCode installed via installer script"
else
    npm install -g opencode-ai || echo "WARN: OpenCode install failed (both paths)"
fi

# --- Optional: Codex, Gemini CLI, OpenHands --------------------------------
# Toad supports 18+ agents via TOML definitions in its agent store, and you
# can browse/install them from the Toad UI at runtime rather than baking them
# in here. Uncomment only what you actually use — every agent added here is
# image weight you carry on every rebuild.
#
# npm install -g @openai/codex
# npm install -g @google/gemini-cli
# uv tool install openhands-ai

log "Agent install pass complete"
echo "Run 'toad' and check the agent picker to confirm what is available."
