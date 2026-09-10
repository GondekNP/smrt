#!/usr/bin/env bash
# Build the L0 vault image.
#
#   bash scripts/build.sh              # cached
#   bash scripts/build.sh --no-cache   # from scratch
#
# UID/GID are passed as build args so files the container writes into the
# bind-mounted vault don't come out root-owned on the host.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

# shellcheck disable=SC1090,SC1091
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/smrt/config"
[ -f "$CONFIG" ] && set -a && . "$CONFIG" && set +a
[ -f .env ] && set -a && . ./.env && set +a

IMAGE="${SMRT_IMAGE:-smrt:latest}"

# Pinned, not ambient — the same reason bin/smrt pins it (OPEN.md decision 4).
# Without this, a build lands in whichever context happens to be active while
# bin/smrt reads from "default", and you get a stale image with no warning.
export DOCKER_CONTEXT="${SMRT_DOCKER_CONTEXT:-default}"

command -v docker >/dev/null 2>&1 || {
    echo "docker not found on PATH." >&2
    exit 1
}

echo "Building ${IMAGE} (uid=$(id -u) gid=$(id -g))"

docker build "$@" \
    --build-arg "USER_UID=$(id -u)" \
    --build-arg "USER_GID=$(id -g)" \
    -f docker/Dockerfile \
    -t "$IMAGE" \
    .

echo
echo "Built ${IMAGE}. Verify with: pixi run check"
