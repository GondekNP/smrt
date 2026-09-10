"""Command line for the proxy: `python3 -m acp_proxy`, or `smrt-acp-proxy`.

Argument parsing is by hand rather than through `argparse` for one reason: the
backend command after `--` must reach the backend exactly as written, and
`argparse`'s handling of `--` and of unknown leading dashes is not something to
bet a transparent proxy on.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .inject import SpecError, parse_spec
from .proxy import run
from .trace import Trace, _warn, default_trace_path

# Sugar over the two adapter commands that exist in the image. `--` stays the
# primary form: the adapter is the part of this stack most likely to be renamed
# or replaced, and a name table that quietly went stale would be worse than
# typing the command. Verified against Toad's own bundled definitions
# (`toad/data/agents/claude.com.toml`, `opencode.ai.toml`), so these match what
# Toad would have run directly.
BACKENDS = {
    "claude": ["claude-agent-acp"],
    "opencode": ["opencode", "acp"],
}

USAGE = """\
smrt-acp-proxy — a transparent ACP proxy for the SMRT vault container

  smrt-acp-proxy [options] -- <backend command...>
  smrt-acp-proxy [options] --backend {claude|opencode}

Forwards newline-delimited JSON-RPC between an ACP client on stdio and an ACP
agent it spawns, unchanged, and records every frame to a JSONL trace.

Options:
  --backend NAME    shorthand for a known adapter: claude | opencode
  --mcp NAME=CMD    inject an MCP server into session/new. Repeatable.
                    Quote the whole spec if CMD takes arguments:
                      --mcp 'probe=python3 -m acp_proxy.mcp_probe'
  --trace PATH      write the trace here
  --no-trace        do not write a trace
  --no-compat       do not repair tool-call frames Toad would refuse.
                    See compat.py — that repair is a workaround for a Toad
                    defect, and this flag is how you check if it is still
                    needed.
  -h, --help        this text

Launch it from Toad, which accepts an arbitrary command:

  toad acp 'smrt-acp-proxy --backend opencode' /vault

With an MCP server attached — the reason this proxy exists, since Toad
hardcodes mcpServers to []:

  toad acp 'smrt-acp-proxy --backend claude --mcp probe=smrt-mcp-probe' /vault

Traces default to $XDG_STATE_HOME/smrt/acp/, or $SMRT_ACP_TRACE if set. A
trace contains full prompt and response content.
"""


class UsageError(Exception):
    pass


def parse_args(
    argv: list[str],
) -> tuple[list[str] | None, Path | None, list[dict], bool]:
    """Return `(backend_command, trace_path, mcp_servers, compat_repairs)`.

    A `None` backend command means help was asked for. A `None` trace path
    means tracing is off.
    """
    backend_cmd: list[str] | None = None
    trace_path: Path | None = None
    mcp_servers: list[dict] = []
    trace_off = False
    compat_repairs = True
    rest = list(argv)

    while rest:
        arg = rest.pop(0)
        if arg == "--":
            backend_cmd = rest
            rest = []
        elif arg in ("-h", "--help"):
            return None, None, [], True
        elif arg == "--backend":
            name = _value(rest, "--backend")
            if name not in BACKENDS:
                known = ", ".join(sorted(BACKENDS))
                raise UsageError(f"unknown backend {name!r} (known: {known})")
            backend_cmd = list(BACKENDS[name])
        elif arg.startswith("--backend="):
            rest.insert(0, arg.split("=", 1)[1])
            rest.insert(0, "--backend")
        elif arg == "--mcp":
            mcp_servers.append(parse_spec(_value(rest, "--mcp")))
        elif arg.startswith("--mcp="):
            mcp_servers.append(parse_spec(arg.split("=", 1)[1]))
        elif arg == "--trace":
            trace_path = Path(_value(rest, "--trace"))
        elif arg.startswith("--trace="):
            trace_path = Path(arg.split("=", 1)[1])
        elif arg == "--no-trace":
            trace_off = True
        elif arg == "--no-compat":
            compat_repairs = False
        else:
            raise UsageError(f"unexpected argument {arg!r}")

    if not backend_cmd:
        raise UsageError("no backend command; pass --backend NAME or -- <command>")

    names = [s["name"] for s in mcp_servers]
    if len(names) != len(set(names)):
        raise SpecError(f"duplicate --mcp names: {names}")

    if trace_off:
        return backend_cmd, None, mcp_servers, compat_repairs
    return (backend_cmd, trace_path or default_trace_path(), mcp_servers,
            compat_repairs)


def _value(rest: list[str], flag: str) -> str:
    if not rest:
        raise UsageError(f"{flag} needs a value")
    return rest.pop(0)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        backend_cmd, trace_path, mcp_servers, compat_repairs = parse_args(args)
    except (UsageError, SpecError) as error:
        # stderr, and a non-zero exit — the combination Toad actually surfaces.
        _warn(str(error))
        _warn("try --help")
        return 2

    if backend_cmd is None:
        sys.stdout.write(USAGE)
        return 0

    trace = Trace(trace_path)
    try:
        return run(backend_cmd, trace, mcp_servers, compat_repairs)
    finally:
        trace.close()


if __name__ == "__main__":
    sys.exit(main())
