#!/usr/bin/env bash
# Run the ACP proxy's offline test suite inside the image.
#
# Inside the image, because that is where the proxy actually runs and its
# interpreter (pixi's 3.14) is not the one on most hosts. The suite itself
# needs no container, no agent and no credentials — it drives the proxy against
# a fake backend over pipes — so it also runs directly:
#
#   cd proxy && python3 -m unittest discover -s tests -t .
#
# The source is mounted read-only rather than baked, so editing a test doesn't
# cost a rebuild.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1; pwd)"
cd "$HERE" || exit 1

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/smrt/config"
# shellcheck disable=SC1090  # path is by construction not a literal
[ -f "$CONFIG" ] && set -a && . "$CONFIG" && set +a

IMAGE="${SMRT_IMAGE:-smrt:latest}"
export DOCKER_CONTEXT="${SMRT_DOCKER_CONTEXT:-default}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image ${IMAGE} not found. Run: pixi run build" >&2
    exit 1
fi

exec docker run --rm \
    -v "$HERE/proxy:/workspace/proxy:ro" \
    -w /workspace/proxy \
    "$IMAGE" \
    python3 -m unittest discover -s tests -t . -v
