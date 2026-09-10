# Auth

**Status: decided 2026-09-08.** See `OPEN.md` decision 1.

**The container gets its own OAuth session.** You run `/login` once inside it,
and the credentials live in SMRT's state directory — never in your host's
Claude Code config, and never read from it.

Two properties are wanted at once and they are not in conflict:

- **Subscription pricing.** Tutoring is token-intensive by construction —
  probing, rubric grading, and re-verifying claims all spend tokens to produce
  small outputs. An API key billed per token is the wrong instrument.
- **Container-scoped credentials.** A container is a wider blast radius than a
  laptop. The session it holds should be revocable on its own, and should not
  be the same session your host uses.

OAuth inside the container gives both.

## Default — container-scoped

```bash
-v "$SMRT_STATE/agents:/home/smrt/.claude"
-v "$SMRT_STATE/claude.json:/home/smrt/.claude.json"
```

Two mounts, because Claude Code splits its state: credentials go in
`~/.claude/`, but onboarding state and project history go in `~/.claude.json`,
which sits *beside* that directory. Persist only the directory and you
re-onboard on every launch.

`bin/smrt` pre-creates the `claude.json` file, because bind-mounting a source
that does not exist makes Docker create a **directory** there and Claude Code
then fails on a file it cannot parse.

**First run:** launch `claude` in the container and use `/login`. The session
persists in `$SMRT_STATE/agents` from then on. `bin/smrt` says so when it
notices no credentials yet.

To revoke just the container's access, delete `$SMRT_STATE/agents` and log in
again. Your host session is unaffected because it was never involved.

## Opt-in — reuse the host session

```bash
SMRT_HOST_AUTH=1 smrt
```

Mounts the host's `~/.claude` and `~/.claude.json` instead. Convenient if you
are already logged in on that machine and would rather not authenticate twice.

**The cost is real:** the container can then read your live host token, and a
revocation affects both. Offered because some people will prefer it, not
because it is the better default.

Untested either way: token refresh across a bind mount. If a long session drops
its auth, look here first.

## Headless (Phase 4) and OpenCode

`bin/smrt` forwards `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, and
`OPENAI_API_KEY` when set. An OAuth session cannot work unattended, so CI keeps
the key path. OpenRouter matters for the blitz, where running the adversary on
a different model than the implementer is the point.

## Either way

`.state/` holds credentials and is gitignored. Confirm before your first push:

```bash
git check-ignore -v .state && echo "ignored"
```
