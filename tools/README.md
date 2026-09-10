# Vault tools

MCP server exposing the question types and the log/artifact plumbing.

**This is the only component shared between L0 and L1.** Whatever shape it
takes here is inherited by the design layer, so it's worth getting the tool
signatures right before building much on top.

> **PLACEHOLDER.** `vault_tools/server.py` defines the interface and every
> handler raises `NotImplementedError`. The signatures are the thing worth
> arguing about before any of it is real.

## Tools

| Tool | Purpose |
|---|---|
| `quiz` | Multiple choice. Requires a pick **and** a one-line justification, graded separately. |
| `explain` | Free response against a rubric committed before the question is shown. |
| `derive` | Write a derivation note. Returns immediately; does not wait. |
| `ask` | Genuine fork, no right answer. Never used for gradable content. |
| `submit_artifact` | Read a submission — a note (resolving its `![[…]]` embeds) or a bare image. |
| `record_grade` | Write grading back into the derivation's own note. |
| `md_log` | Append to the session's markdown log in the vault. |

Seven, not six: `record_grade` was split out once submissions became notes,
because writing structured front matter back is a different job from appending
to a transcript.

## The derive loop

Decided 2026-09-08 — see `docs/OPEN.md` decision 7. **The note is the
submission.**

```
agent  derive(task, rubric, concept)      -> writes notes/…/derive-007.md
                                              front matter carries rubric_sha256
you    attach photo into "## Attempt"        Obsidian desktop or mobile
you    "done"                                in conversation
agent  submit_artifact("notes/…/derive-007.md")
                                           -> resolves embeds, returns images
agent  record_grade(...)                   -> appends "## Grading" callouts,
                                              sets status/score/rubric
```

What that buys, all of it native to Obsidian rather than bolted on:

- **The record is automatic.** Task, attempt and grading in one note, in the
  graph, with backlinks to the concept, and in git history since the vault is a
  repo.
- **It is queryable.** Front matter plus Dataview answers "every derivation I
  got wrong".
- **Grading renders.** `> [!success]` / `> [!warning]` callouts, not plain text.

Two constraints the signatures enforce:

**Nothing blocks.** MCP is request/response. A `derive` that waited minutes for
a photo would wedge the session, so it writes the note and returns. The wait is
conversational.

**Pre-commitment is verifiable.** `rubric_sha256` up front, plaintext `rubric`
only after grading. See `vault-template/templates/README.md`.

## Getting the photo into the vault

The note flow solves the *record*; it does not solve *transport*. The native
answer is Obsidian mobile on the same vault — open the note on your phone,
attach, shoot, done, no file management. That needs the vault synced to the
phone (Obsidian Sync, Syncthing, or self-hosted LiveSync), which touches the
deferred vault-topology decision: one vault means the phone syncs every
subject.

Not wanted: webcam or other host-device access. That was the argument for a
host socket and it is explicitly declined — see `docs/OPEN.md` decision 3.

## Wiring

Attached via the `mcpServers` field of ACP `session/new`.

**Toad 0.6.20 cannot do this** — it hardcodes the field empty. Observed on the
wire, not just read out of its source:

```json
{"jsonrpc": "2.0", "method": "session/new", "params": {"cwd": "/vault", "mcpServers": []}, "id": 2}
```

So the ACP proxy is a prerequisite rather than a Phase 3 nicety. **It is now
built, and this is no longer a blocker** — a model has called a tool through an
injected MCP server:

```bash
smrt -- toad acp 'smrt-acp-proxy --backend claude --mcp vault-tools=vault-tools' /vault
```

Nothing stands between these signatures and a working teaching loop except
implementing them. See `docs/OPEN.md` decision 5, `docs/proxy.md`, and
`proxy/README.md`.

## Placement

In-container. `docs/OPEN.md` decision 3.

## TODO

- [ ] Pick an MCP SDK and implement for real
- [x] Rubric visibility for `explain` — same rule as `derive`: hash committed
      before, plaintext after. Decided 2026-09-08.
- [ ] `md_log` — one file per session, or append to a daily note?
- [ ] Does `quiz` grade the justification with a model, or just record it?
- [ ] Persist quiz outcomes somewhere queryable, so the probe phase can start
      from what you already demonstrated last week. Front matter on derive
      notes is the pattern to copy.
