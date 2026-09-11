#!/usr/bin/env bash
# Run the vault tool server's test suite inside the image.
#
# Inside the image and NOT optional, unlike the proxy's suite: importing the
# tool server imports the MCP SDK, which lives in the image's global python
# environment and is not a host dependency. There is no bare-host fallback.
#
# Two suites, both discovered here:
#
#   tests/test_tools.py   direct calls -- the grading logic
#   tests/test_stdio.py   a real client against a real server over stdio
#
# The second one matters more than it sounds. It caught the SDK withholding
# refusal messages from the client, which the direct-call tests could not see
# and which would have made every refusal useless in a live session.
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
    -v "$HERE/tools:/workspace/tools:ro" \
    -v "$HERE/curriculum:/workspace/curriculum:ro" \
    -w /workspace/tools \
    "$IMAGE" \
    python3 -m unittest discover -s tests -t . -v
