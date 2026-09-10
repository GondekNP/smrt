"""The SMRT ACP proxy.

Sits between an ACP client (Toad) and an ACP agent, on stdio:

    Toad ──stdio──▶ proxy ──stdio──▶ claude-agent-acp | opencode acp
         ◀─────────       ◀─────────

Step 1 of the build order in `docs/proxy.md`: forwards every method unchanged.
It exists so that the behaviour added later — injecting `mcpServers` into
`session/new`, which is the only reason this component is needed at all — lands
on a transport already proven to be transparent.

See `proxy/README.md` for the constraints the implementation is shaped by. Two
of them are not obvious and are easy to reintroduce:

  * Frames are forwarded as the ORIGINAL BYTES. Nothing re-serializes JSON it
    did not deliberately change.
  * Sustained output on stderr deadlocks the proxy, because Toad pipes it and
    does not read it. Diagnostics go to the trace file.
"""

__all__ = ["PROTOCOL_VERSION", "__version__"]

__version__ = "0.1.0"

# The ACP version this proxy is written against, and the one Toad 0.6.20 sends
# (toad/acp/agent.py:32). Pinning a version is the documented drift strategy:
# handle a few methods, let the rest pass through untouched. The proxy does not
# enforce this — it records the negotiated version in the trace so a mismatch is
# visible after the fact rather than fatal during a session.
PROTOCOL_VERSION = 1
