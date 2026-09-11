# Environment

Why the image looks the way it does. Read alongside `docker/Dockerfile`.

## Mounts, and why they are the enforcement mechanism

| Path | Mode | Notes |
|---|---|---|
| `/vault` | **rw** | Obsidian vault. A git repo. Host Obsidian reads the same directory. |
| `/subject` | **ro** | Optional. A repo, a KiCad project, a folder of PDFs, or absent. |

A third case joined the list on 2026-09-11: **the set text for a course the
learner is actually taking.** It needs no new mount and no new feature — a
directory holding a textbook and some lecture notes is just a subject — but it
does change what the skill should do with what it finds there. See
`curriculum.md`, "Grounding".

The read-only flag on `/subject` is the whole point. **An agent that cannot
write cannot run ahead of you**, and that is enforced by a mount flag rather
than by an instruction in a prompt that a model may or may not honour.

This principle recurs at every layer of the wider design: write-scope is the
organizing constraint, not tone or system-prompt discipline.

## The `--subject` constraint

The teach skill **may assume nothing about `/subject` beyond "files exist
there."** Its only guaranteed capability is reading them.

If the subject happens to be the meta repo and the skill finds charters and
tensions, that is a bonus it discovers at runtime, not a precondition. The
moment the skill branches on "if this is a Python repo, do X," it has become
a project-specific tutor wearing a general-purpose name, and KiCad stops
working.

This is also what makes the crossover case work without a crossover feature.
Launch with `--subject ~/code/meta` and the tutor reads charters and open
tensions as raw probe material. No integration — just a directory that
happens to contain useful input.

## Image choices

**Debian trixie slim, not a devcontainer base image.** This layer uses none of
what the devcontainer feature ecosystem provides. A plain base plus four
installs is smaller and easier to reason about than a features stack.

**pixi, not uv.** The fire-recovery repos already carry `pixi.toml` and
`pixi.lock`. One package manager across every layer beats uv here and pixi
there, and Toad is published on conda-forge so pixi handles it directly.

**Toad via `pixi global install batrachian-toad`**, per the Toad README. This
also solves the Python problem for free: Debian trixie doesn't ship 3.14 and
Toad requires it, but pixi brings its own interpreter rather than making us
fight deadsnakes or build from source.

**The tool server and the ACP proxy sit on `PYTHONPATH`, not installed.**
Neither has dependencies, so a locked environment would be ceremony. When
either grows real ones, give it its own `pixi.toml` and `pixi install` it in
the Dockerfile.

The proxy gets a three-line `exec` wrapper on `PATH` rather than a pip install,
for two reasons: pip into a `pixi global` environment invites trouble, and an
installed copy would shadow the `SMRT_PROXY_SRC` live mount that makes editing
the proxy free.

Note that `pixi global install` is not lockfile-managed. That's acceptable for
a layer that runs nothing and is rebuilt freely; if this image ever needs to
be reproducible byte-for-byte, convert it to a project manifest with a
committed `pixi.lock`.

**Node from NodeSource** because Claude Code is an npm package. Global prefix
lives under `$HOME` so no sudo is needed to add agents at runtime.

**ripgrep is load-bearing, not convenience.** The tutor agent must verify
before asserting — reading a large codebase from memory is where confabulated
call graphs come from. `rg` is how it checks.

**poppler-utils for the same reason one step out.** `/subject` is documented
above as possibly "a folder of PDFs", and `rg` cannot read one — so until
2026-09-11 a textbook or paper could be mounted and never searched. `pdftotext`
fixes that, and its `-f/-l` page range is what makes a `locator` in the
curriculum actionable: six pages into context instead of a whole book. See
`curriculum.md`.

**Agent installs in a separate script.** `docker/install-agents.sh` sits at
the bottom of the Dockerfile so editing it doesn't invalidate the layers
above, and each install is non-fatal so one broken upstream doesn't block the
build.

**UID/GID as build args.** Without this, files the container writes into the
bind-mounted vault come out root-owned on the host, and Obsidian can't edit
its own notes. `pixi run build` passes your real UID automatically.

## Terminal

Toad is a Textual TUI. Pass `TERM` through. The Toad README specifically calls
out that macOS Terminal.app gives a much reduced experience and recommends
Ghostty; Kitty, WezTerm, and Alacritty are also fine.

Toad also runs on Linux and macOS but lacks native Windows support — WSL
works.

## State that persists between runs

`bin/smrt` mounts `$SMRT_STATE` (default `~/.local/share/smrt`) for Toad's
settings and session history. Without it you lose scrollback and re-configure
every launch.

**Toad splits that state across both XDG directories, and mounting one is not
enough.** `~/.config/toad/toad.json` holds UI settings; session history is a
SQLite database at `~/.local/state/toad/toad.db` (`toad/db.py:38`). Only the
config dir was mounted until 2026-09-09, so settings persisted and scrollback
did not. Both are mounted now, and the state dir doubles as where the ACP
proxy writes its traces and where Toad writes its `TOAD_LOG` transcript.

`~/.local/state` has to exist in the image before that mount lands, for the
same reason as the other XDG dirs: Docker creates a missing bind-mount parent
as **root**, which would take `.local/bin` and `.local/share` down with it.

Claude Code's credentials live there too, in `$SMRT_STATE/agents`, from a
`/login` run **inside** the container. The host's own `~/.claude` is not read
unless you opt in with `SMRT_HOST_AUTH=1`. See `auth.md`.

State lives outside the repo by default. The devcontainer's copy under
`.devcontainer/.state/` is gitignored. Both contain credentials.

## What is deliberately absent

No language servers, no compilers, no pixi environments, no geospatial stack.
**This layer executes nothing in the projects it reads.** Each sub-repo has
its own devcontainer for that, and L0 never invokes them.

If you find yourself wanting to run a project's tests from here, that's the
signal you're in the wrong layer.
