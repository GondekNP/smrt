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
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        less \
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
RUN pixi global install batrachian-toad \
    && pixi global install "python=${PYTHON_VERSION}"

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
# On PYTHONPATH rather than installed, because it's a placeholder with no
# dependencies. When it grows real ones, give it its own locked pixi manifest
# and `pixi install` it here instead.
COPY --chown=${USER_UID}:${USER_GID} tools /workspace/tools

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
# smrt-mcp-probe gets one too, so `--mcp probe=smrt-mcp-probe` needs no nested
# shell quoting inside `toad acp '...'`.
RUN printf '#!/bin/sh\nexec python3 -m acp_proxy "$@"\n' \
        > /home/${USERNAME}/.local/bin/smrt-acp-proxy \
    && printf '#!/bin/sh\nexec python3 -m acp_proxy.mcp_probe "$@"\n' \
        > /home/${USERNAME}/.local/bin/smrt-mcp-probe \
    && chmod +x /home/${USERNAME}/.local/bin/smrt-acp-proxy \
                /home/${USERNAME}/.local/bin/smrt-mcp-probe

# Toad is a Textual TUI. A capable terminal matters; the Toad README
# specifically calls out that macOS Terminal.app gives a degraded experience.
ENV TERM=xterm-256color \
    COLORTERM=truecolor

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash"]
