"""Injecting `mcpServers` into `session/new` — the reason this proxy exists.

Toad hardcodes the field empty (`toad/acp/agent.py:750`), observed on the wire
rather than merely read out of its source, so the vault tool server cannot
reach a session without something rewriting that frame. This is that something.
See `docs/OPEN.md` decision 5.

Two properties matter more than the rewriting itself.

**Injection is fail-safe.** Every caller treats a `None` return as "forward the
original bytes untouched". A proxy that broke a session because it could not
parse a frame it wanted to modify would be worse than no proxy at all — the
whole point of building the pass-through first was to make the transport
incapable of that, and the injection must not reintroduce it.

**The client's own list wins.** Toad sends `[]` today, but a future Toad, or a
different ACP client, may send real entries. Ours are appended, and any name
the client already declared is left alone rather than overwritten. Silently
replacing a client's MCP server would be a bug that only shows up in someone
else's setup.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil

# The two methods that carry the field. `session/load` matters as much as
# `session/new`: Toad passes `[]` there too when resuming a session
# (`toad/acp/agent.py:795-797`), so injecting only into `session/new` would
# give you tools in fresh sessions and silently lose them on resume.
INJECTABLE = ("session/new", "session/load")


class SpecError(ValueError):
    """A bad --mcp argument. Raised at startup, never mid-session."""


def parse_spec(spec: str) -> dict:
    """Parse `NAME=COMMAND [ARG...]` into an ACP `McpServer` object.

    The command is resolved to an absolute path because the ACP schema asks for
    one, and because resolving it here is what turns a typo into an immediate
    startup failure instead of an MCP server that silently never appears in the
    session. That failure mode is miserable to debug from the inside.
    """
    name, sep, command = spec.partition("=")
    name, command = name.strip(), command.strip()
    if not sep or not name or not command:
        raise SpecError(f"--mcp needs NAME=COMMAND, got {spec!r}")

    try:
        parts = shlex.split(command)
    except ValueError as error:
        raise SpecError(f"--mcp {name}: cannot parse command: {error}") from None
    if not parts:
        raise SpecError(f"--mcp {name}: empty command")

    resolved = shutil.which(parts[0])
    if resolved is None:
        if os.path.isfile(parts[0]) and os.access(parts[0], os.X_OK):
            resolved = os.path.abspath(parts[0])
        else:
            raise SpecError(
                f"--mcp {name}: command not found or not executable: {parts[0]}"
            )

    return {"name": name, "command": resolved, "args": parts[1:], "env": []}


def declared_names(existing: object) -> set[str]:
    """The server names the client actually declared.

    `existing` is whatever was on the wire, which may not be a list at all. An
    unexpected type counts as "declared nothing" rather than as an error,
    because refusing to inject is recoverable and refusing to forward is not.
    """
    if not isinstance(existing, list):
        return set()
    return {s.get("name") for s in existing if isinstance(s, dict)}


def merge(existing: object, servers: list[dict]) -> list[dict] | None:
    """Return the merged server list, or `None` if there is nothing to add."""
    current = existing if isinstance(existing, list) else []
    already = declared_names(existing)
    additions = [s for s in servers if s["name"] not in already]
    if not additions:
        return None
    return [*current, *additions]


def rewrite(frame: object, servers: list[dict]) -> tuple[bytes, list[str]] | None:
    """Rewrite a `session/new` / `session/load` request to carry `servers`.

    Returns `(bytes_to_forward, names_added)`, or `None` to forward the
    original untouched — which covers every frame that is not an injectable
    request, and every frame where there is nothing to add.

    This is the only place in the proxy that serializes JSON onto the wire.
    Everything else forwards the bytes it received, so a method this proxy has
    never heard of cannot be reshaped by passing through it.
    """
    if not servers or not isinstance(frame, dict):
        return None
    if frame.get("method") not in INJECTABLE:
        return None

    params = frame.get("params")
    if not isinstance(params, dict):
        return None

    existing = params.get("mcpServers")
    merged = merge(existing, servers)
    if merged is None:
        return None

    # Compare NAMES, not objects. Comparing by membership in `existing` looked
    # equivalent and was not: when a client sends a non-list `mcpServers`, `x
    # in "some string"` raises TypeError, the fail-safe catches it, and
    # injection silently does not happen. Found by a test; worth stating,
    # because the fail-safe turns bugs in here into missing tools rather than
    # visible errors. `inject_failed` in the trace is the only tell.
    before = declared_names(existing)
    added = [s["name"] for s in servers if s["name"] not in before]

    # Shallow copies, so the traced original stays exactly as it arrived.
    rewritten = dict(frame)
    rewritten["params"] = {**params, "mcpServers": merged}

    line = json.dumps(rewritten, ensure_ascii=False).encode("utf-8") + b"\n"
    return line, added
