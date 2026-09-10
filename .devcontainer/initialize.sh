#!/usr/bin/env bash
# Runs on the HOST, before the container is created.
#
# Its whole job is making sure every bind source in docker-compose.yml exists.
# Docker will happily create a *directory* where you meant a file, but an
# empty or missing bind source at create time is a hard failure — which is the
# error you get from an unset ${localEnv:VAULT_PATH}.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$HERE/.scratch-vault" "$HERE/.state/agents" "$HERE/.state/toad"

# Seed the scratch vault once so the container opens onto something real.
if [ -z "$(ls -A "$HERE/.scratch-vault" 2>/dev/null)" ]; then
    cp -r "$HERE/../vault-template/." "$HERE/.scratch-vault/"
    echo "Seeded scratch vault from vault-template/"
fi

# Compose reads .env from the directory containing docker-compose.yml.
# UID/GID keep bind-mounted files from coming out root-owned on the host.
{
    echo "UID=$(id -u)"
    echo "GID=$(id -g)"
} > "$HERE/.env"

# Carry through anything already set in your shell, without overwriting an
# existing value.
for var in SMRT_VAULT SMRT_SUBJECT ANTHROPIC_API_KEY OPENROUTER_API_KEY; do
    [ -n "${!var:-}" ] && echo "$var=${!var}" >> "$HERE/.env"
done

echo "Devcontainer prepared."
echo "  vault   ${SMRT_VAULT:-$HERE/.scratch-vault}"
echo "  subject ${SMRT_SUBJECT:-$(cd "$HERE/.." && pwd)} (read-only)"
