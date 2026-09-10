"""Client-compatibility repairs. One entry, and it should not be permanent.

===========================================================================
==                                                                       ==
==   FOLLOW UP — THIS MODULE IS A WORKAROUND, NOT A FEATURE.             ==
==                                                                       ==
==   It exists because Toad 0.6.20 rejects valid ACP frames. Before       ==
==   this file grows a second entry, or before anyone builds on it:       ==
==                                                                       ==
==     1. Confirm the defect against a newer Toad. 0.6.20 was the         ==
==        latest release as of 2026-09-10 and `main` was still            ==
==        affected, so there was nothing to upgrade to.                   ==
==     2. File it upstream (deliberately NOT done yet — we wanted more    ==
==        confirmation first). The fix is six annotations.                ==
==     3. DELETE this module once a fixed Toad ships. Leaving a shim in   ==
==        place after upstream heals is how a proxy turns into a second   ==
==        implementation of someone else's protocol.                      ==
==                                                                       ==
==   To check whether it is still needed:  --no-compat, then run a        ==
==   prompt that calls a tool and see whether the call completes in the   ==
==   UI. `compat_repaired` in the trace counts how often it fired.        ==
==                                                                       ==
===========================================================================

The defect
----------

`rawInput` and `rawOutput` are `Option<serde_json::Value>` in the reference
schema — any JSON value. Toad annotates both as `dict` in three classes
(`ToolCall`, `ToolCallUpdate`, `ToolCallUpdatePermissionRequest`), and
validates `session/update` against that typed union *before* dispatch. So a
conformant agent sending a list or a string there has its whole frame refused
with `-32601`-style type errors, and the frame is discarded.

Measured over one 206-frame session against `claude-agent-acp`:

    9x  rawInput   dict     accepted
    2x  rawOutput  list     REJECTED   (ToolSearch, mcp__probe__smrt_probe)
    1x  rawOutput  str      REJECTED   (Read)

Every `tool_call_update` carrying `status: completed` was refused, so tool
calls never visibly finish and their results never render. That is on L0's
critical path, because the whole teaching loop delivers through tool calls.

`rawInput` has not fired yet — all nine were dicts — but it is the same bug
with the same shape, so it is handled here too rather than waiting for it.

Why removal rather than coercion
--------------------------------

Both fields are **optional** in the schema, so a frame without them is still
valid; wrapping a list as `{"value": [...]}` would produce a frame that
validates but lies about the tool's output. Removal is the smaller untruth.

It also costs Toad nothing, which is the part that makes this safe:
`rawOutput` is *never read anywhere* in the Toad package — `grep` finds it
only at those three type declarations. The field is pure validation cost
there. The trace keeps the original frame, so nothing is lost for our own
analysis either.
"""

from __future__ import annotations

import json

# The fields Toad over-narrows. Both are `Option<Value>` upstream.
RAW_FIELDS = ("rawInput", "rawOutput")

# Where a tool call object can appear inside an agent->client frame:
# `session/update` carries one under `params.update`, and
# `session/request_permission` carries one under `params.toolCall`.
TOOL_CALL_LOCATIONS = ("update", "toolCall")


def repair(frame: object) -> tuple[bytes, list[str]] | None:
    """Strip non-dict `rawInput`/`rawOutput` from a frame Toad would refuse.

    Returns `(bytes_to_forward, what_was_removed)`, or `None` to forward the
    original untouched — which is the answer for the overwhelming majority of
    frames, including every frame whose raw fields are already dicts.

    Like the injection, this is fail-safe by contract: callers treat any
    failure as "forward the original".
    """
    if not isinstance(frame, dict):
        return None

    params = frame.get("params")
    if not isinstance(params, dict):
        return None

    removed: list[str] = []
    patched_locations: dict[str, dict] = {}

    for location in TOOL_CALL_LOCATIONS:
        tool_call = params.get(location)
        if not isinstance(tool_call, dict):
            continue
        offenders = [
            field
            for field in RAW_FIELDS
            if field in tool_call and not isinstance(tool_call[field], dict)
        ]
        if not offenders:
            continue
        patched = {k: v for k, v in tool_call.items() if k not in offenders}
        patched_locations[location] = patched
        removed.extend(f"{location}.{field}" for field in offenders)

    if not removed:
        return None

    # Shallow copies throughout, so the frame recorded in the trace stays
    # exactly as it arrived on the wire.
    rewritten = dict(frame)
    rewritten["params"] = {**params, **patched_locations}

    line = json.dumps(rewritten, ensure_ascii=False).encode("utf-8") + b"\n"
    return line, removed
