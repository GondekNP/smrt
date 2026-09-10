#!/usr/bin/env bash
# Remove the image. Leaves .state/ alone — that holds credentials and Toad's
# session history, and blowing it away means re-authenticating.

set -uo pipefail

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

docker rmi "$IMAGE" 2>/dev/null && echo "Removed ${IMAGE}" || echo "No such image: ${IMAGE}"
echo "Left .state/ in place. Remove it manually if you want to reset agent auth."
