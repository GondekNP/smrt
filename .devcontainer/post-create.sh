#!/usr/bin/env bash
# Runs once after the devcontainer is created.
# Seeds an empty vault from vault-template/ and reports what's available.

set -uo pipefail

VAULT="${VAULT_ROOT:-/vault}"
TEMPLATE="/workspace/vault-template"

printf '\n=== L0 vault container\n'

# --- seed the vault --------------------------------------------------------
if [ -d "$VAULT" ] && [ -z "$(ls -A "$VAULT" 2>/dev/null)" ]; then
    echo "Vault at $VAULT is empty — seeding from template."
    cp -r "$TEMPLATE/." "$VAULT/"
    ( cd "$VAULT" && git init -q && git add -A \
      && git commit -q -m "Seed vault from template" ) \
      && echo "Initialised git in $VAULT"
elif [ -d "$VAULT" ]; then
    echo "Vault at $VAULT already has contents — left untouched."
else
    echo "WARN: $VAULT does not exist. Check SMRT_VAULT / initialize.sh."
fi

# --- subject ---------------------------------------------------------------
SUBJECT="${SUBJECT_ROOT:-/subject}"
if [ -d "$SUBJECT" ] && [ -n "$(ls -A "$SUBJECT" 2>/dev/null)" ]; then
    echo "Subject mounted at $SUBJECT ($(find "$SUBJECT" -maxdepth 1 | wc -l) top-level entries, read-only)."
else
    echo "No subject mounted. That's fine — the teach skill works without one."
fi

# --- what's installed ------------------------------------------------------
printf '\n=== Installed\n'
for cmd in toad claude opencode pixi git rg; do
    if command -v "$cmd" >/dev/null 2>&1; then
        printf '  %-10s %s\n' "$cmd" "$(command -v "$cmd")"
    else
        printf '  %-10s MISSING\n' "$cmd"
    fi
done

printf '\n=== Next\n'
echo "  toad /vault          launch against the vault"
echo "  pixi run check       re-run this report (from the host)"
echo "  docs/OPEN.md         three decisions still outstanding"
printf '\n'
