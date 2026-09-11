# L0 — Vault container
#
# Learning layer. Runs Toad + coding agents against an Obsidian vault.
# Deliberately minimal: this layer reads and writes markdown. It does not
# build, test, or execute anything in the projects it reads.
#
# See docs/environment.md for the reasoning behind each choice.

FROM debian:trixie-slim

ARG USERNAME=smrt
ARG USER_UID=1000
ARG USER_GID=1000
ARG NODE_MAJOR=22
ARG PYTHON_VERSION=3.14

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# --- system packages -------------------------------------------------------
# ripgrep is load-bearing: the tutor agent greps rather than recalling.
# poppler-utils for the same reason one step further out. /subject is
# documented as possibly "a folder of PDFs", and rg cannot read one -- so a
# textbook or a paper could be pointed at but never searched. `pdftotext
# -f/-l` also extracts by page, which is what makes a locator in the canon
# worth recording: 18 pages into context instead of 700.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        less \
        poppler-utils \
        ripgrep \
        sudo \
        tini \
        unzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# --- node (for Claude Code / OpenCode) -------------------------------------
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- non-root user ---------------------------------------------------------
# UID/GID are build args so bind-mounted vault files don't end up root-owned
# on the host. scripts/build.sh passes your real UID automatically.
RUN groupadd --gid "${USER_GID}" "${USERNAME}" \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" -m -s /bin/bash "${USERNAME}" \
    && echo "${USERNAME} ALL=(root) NOPASSWD:ALL" > "/etc/sudoers.d/${USERNAME}" \
    && chmod 0440 "/etc/sudoers.d/${USERNAME}" \
    && mkdir -p /vault /subject /workspace \
    && chown "${USER_UID}:${USER_GID}" /vault /workspace

# npm global prefix inside $HOME so the user can install without sudo
ENV NPM_CONFIG_PREFIX=/home/${USERNAME}/.npm-global
# .opencode/bin is here because the OpenCode installer puts the binary there
# and only exports PATH from .bashrc, which non-interactive shells never
# source. Without this the install silently succeeds and stays invisible.
ENV PATH=/home/${USERNAME}/.pixi/bin:/home/${USERNAME}/.npm-global/bin:/home/${USERNAME}/.opencode/bin:/home/${USERNAME}/.local/bin:$PATH

USER ${USERNAME}
WORKDIR /workspace

# Create the XDG dirs up front. When a bind mount targets a subdirectory whose
# parent is missing, Docker creates that parent as ROOT — so mounting state at
# ~/.config/toad would leave ~/.config root-owned and lock the user out of
# writing siblings. OpenCode wants ~/.config/opencode, and fails with EACCES.
#
# .local/state is here for the same reason: bin/smrt mounts it (Toad keeps its
# session history in ~/.local/state/toad/toad.db, and the proxy writes its
# traces alongside), and without ~/.local existing first that mount would make
# ~/.local root-owned, taking .local/bin and .local/share down with it.
RUN mkdir -p /home/${USERNAME}/.config \
             /home/${USERNAME}/.local/share \
             /home/${USERNAME}/.local/state \
             /home/${USERNAME}/.local/bin \
             /home/${USERNAME}/.claude

# --- pixi ------------------------------------------------------------------
# Same toolchain the fire-recovery repos already use. One package manager
# across every layer beats uv here and pixi there.
RUN curl -fsSL https://pixi.sh/install.sh | bash

# --- toad + python ---------------------------------------------------------
# Toad is published on conda-forge, so pixi installs it directly and no
# separate interpreter management is needed. Toad brings its own Python; the
# explicit python install is for the vault tool server.
# `--with mcp` adds the MCP SDK to that python environment without exposing any
# of its executables. This is why the vault tool server can stay on PYTHONPATH
# with no environment of its own: pixi's python has no pip, and the obvious
# alternative -- a separate pixi manifest under tools/ -- would collide with
# the SMRT_TOOLS live mount that makes iterating on the server free.
RUN pixi global install batrachian-toad \
    && pixi global install "python=${PYTHON_VERSION}" --with mcp

# --- agents ----------------------------------------------------------------
# Split into its own script because these move fast, and it sits near the
# bottom so editing it doesn't invalidate the layers above. OpenCode's install
# path in particular should be verified — see docs/verify-installs.md.
COPY --chown=${USER_UID}:${USER_GID} docker/install-agents.sh /tmp/install-agents.sh
RUN bash /tmp/install-agents.sh && rm /tmp/install-agents.sh

# --- vault tool server -----------------------------------------------------
# quiz / explain / derive / ask / submit_artifact / record_grade / md_log.
# The only component shared between L0 and L1.
#
# On PYTHONPATH rather than installed. Its one dependency, the MCP SDK, is in
# the global python environment above -- so this stays a plain source copy that
# SMRT_TOOLS can shadow, and editing a tool costs no rebuild.
COPY --chown=${USER_UID}:${USER_GID} tools /workspace/tools

# --- curriculum canon ------------------------------------------------------
# The imported node set for the lesson DAG: reviewed, cited, and NOT generated.
# See docs/curriculum.md.
#
# It lives here rather than in the vault on purpose. That is what makes "never
# edited by the agent" structural rather than a promise -- the agent works in
# /vault, and the canon is not there. Topic notes in the vault are generated
# from it, and seeding only ever creates.
COPY --chown=${USER_UID}:${USER_GID} curriculum /workspace/curriculum

# --- ACP proxy -------------------------------------------------------------
# Sits between Toad and the backend agent so that `mcpServers` can be injected
# into session/new, which Toad hardcodes empty. See docs/proxy.md.
#
# Nothing routes through it unless you ask: Toad reaches it only via
# `toad acp '<command>'`, so plain `smrt` still talks to the backend directly.
COPY --chown=${USER_UID}:${USER_GID} proxy /workspace/proxy
ENV PYTHONPATH=/workspace/tools:/workspace/proxy

# A wrapper rather than a pip install, for two reasons: pip into a
# `pixi global` environment is asking for trouble, and an installed copy would
# shadow the SMRT_PROXY_SRC live mount that makes iterating on the proxy free.
# ~/.local/bin is already on PATH.
#
# Each wrapper names an ABSOLUTE interpreter and sets its own PYTHONPATH,
# rather than relying on the ENV above. An MCP server is spawned by a client
# that decides its environment, and neither `python3` nor `PYTHONPATH` survives
# that reliably:
#
#   - The Python SDK's stdio client passes only HOME, PATH and TERM.
#   - There are three python3 binaries in this image and only ONE has the MCP
#     SDK: the pixi `python` environment. Toad brings its own interpreter and
#     Debian supplies a third, so whichever `python3` a client's PATH happens
#     to resolve is a coin flip.
#
# Measured, not guessed: launched from Toad, the tool server died with
# `ModuleNotFoundError: No module named 'mcp'` and the client reported only
# "Connection failed (CONNECTION_CLOSED)". It worked from a different client in
# the same image, which is what made it look like a code problem. The proxy and
# the probe are stdlib-only, so they had been surviving the same coin flip --
# that is why this surfaced with the first tool server that had a dependency.
#
# The build fails if that interpreter cannot import mcp, because the runtime
# symptom is this uninformative.
# smrt-mcp-probe gets one too, so `--mcp probe=smrt-mcp-probe` needs no nested
# shell quoting inside `toad acp '...'`.
# vault-tools gets one for the same reason, and it is the command the proxy is
# meant to inject:
#   --mcp vault-tools=vault-tools
RUN PY="/home/${USERNAME}/.pixi/envs/python/bin/python3" \
    && "$PY" -c "import mcp" \
    && printf '#!/bin/sh\nexec env PYTHONPATH=/workspace/proxy %s -m acp_proxy "$@"\n' "$PY" \
        > /home/${USERNAME}/.local/bin/smrt-acp-proxy \
    && printf '#!/bin/sh\nexec env PYTHONPATH=/workspace/proxy %s -m acp_proxy.mcp_probe "$@"\n' "$PY" \
        > /home/${USERNAME}/.local/bin/smrt-mcp-probe \
    && printf '#!/bin/sh\nexec env PYTHONPATH=/workspace/tools %s -m vault_tools.server "$@"\n' "$PY" \
        > /home/${USERNAME}/.local/bin/vault-tools \
    && printf '#!/bin/sh\nexec env PYTHONPATH=/workspace/tools %s -m vault_tools.curriculum "$@"\n' "$PY" \
        > /home/${USERNAME}/.local/bin/smrt-curriculum \
    && printf '#!/bin/sh\nexec env PYTHONPATH=/workspace/tools %s -m vault_tools.ledger "$@"\n' "$PY" \
        > /home/${USERNAME}/.local/bin/smrt-ledger \
    && chmod +x /home/${USERNAME}/.local/bin/smrt-acp-proxy \
                /home/${USERNAME}/.local/bin/smrt-mcp-probe \
                /home/${USERNAME}/.local/bin/vault-tools \
                /home/${USERNAME}/.local/bin/smrt-curriculum \
                /home/${USERNAME}/.local/bin/smrt-ledger

# Toad is a Textual TUI. A capable terminal matters; the Toad README
# specifically calls out that macOS Terminal.app gives a degraded experience.
ENV TERM=xterm-256color \
    COLORTERM=truecolor

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
