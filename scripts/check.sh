#!/usr/bin/env bash
# Report what actually landed in the image.
#
# Agent installs in docker/install-agents.sh are deliberately non-fatal, so a
# broken upstream shows up here as MISSING rather than as a failed build.
# See docs/verify-installs.md.

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

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Image ${IMAGE} not found. Run: pixi run build" >&2
    exit 1
fi

echo "=== ${IMAGE}"
# bash -c, NOT -lc: a login shell sources /etc/profile, which resets PATH
# and discards the image's ENV PATH — every $HOME-installed binary then
# reports MISSING even though it is installed and working.
docker run --rm "$IMAGE" bash -c '
# claude-agent-acp is the adapter that Toad bundled claude.com definition
# actually invokes. The claude CLI has no ACP mode of its own, so without the
# adapter Toad cannot reach Claude Code at all.
for c in toad claude claude-agent-acp opencode \
         smrt-acp-proxy smrt-mcp-probe vault-tools \
         smrt-curriculum smrt-ledger \
         pixi git rg python3; do
    if command -v "$c" >/dev/null 2>&1; then
        printf "  %-17s %s\n" "$c" "$(command -v "$c")"
    else
        printf "  %-17s MISSING\n" "$c"
    fi
done

echo
echo "=== Python components on PYTHONPATH"
# Not piped into head: a pipeline would report the exit status of head and
# every broken import would come back looking fine.
if out=$(python3 -m acp_proxy --help 2>&1); then
    printf "  %-17s ok, %s\n" "acp_proxy" "$(printf "%s" "$out" | head -1)"
else
    printf "  %-17s BROKEN\n" "acp_proxy"
fi
# Registered and placeholder are reported separately on purpose: counting them
# together read as "7/7 tools" while five of them raised NotImplementedError.
python3 -c "
import vault_tools.server as s
print(\"  %-17s %d registered: %s\" % (\"vault_tools\", len(s.IMPLEMENTED),
                                      \", \".join(s.IMPLEMENTED)))
print(\"  %-17s %d placeholder: %s\" % (\"\", len(s.PLACEHOLDERS),
                                       \", \".join(s.PLACEHOLDERS)))
" || printf "  %-17s BROKEN\n" "vault_tools"
# The canon is baked in, so a malformed one should fail here rather than in a
# lesson. load_all also refuses two courses that share a topic filename.
python3 -c "
from vault_tools.curriculum import load_all
canons = load_all(\"/workspace/curriculum\")
print(\"  %-17s %d courses, %d topics\" % (\"curriculum\", len(canons),
                                          sum(len(c.topics) for c in canons)))
" || printf "  %-17s BROKEN\n" "curriculum"
'

echo
echo "=== Host config"
[ -f .env ] && echo "  .env present" || echo "  .env MISSING (optional — see README)"

if [ -n "${SMRT_VAULT:-}" ]; then
    if [ -d "$SMRT_VAULT" ]; then
        echo "  SMRT_VAULT  $SMRT_VAULT"
    else
        echo "  SMRT_VAULT  $SMRT_VAULT (NOT A DIRECTORY)"
    fi
else
    echo "  SMRT_VAULT  unset"
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  auth        ANTHROPIC_API_KEY set"
else
    echo "  auth        unset — see docs/auth.md, decision 1 in docs/OPEN.md"
fi
