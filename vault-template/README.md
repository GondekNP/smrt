# Vault

> Seeded from `vault-template/`. Edit freely — this is yours now.

Open this directory as an Obsidian vault on the host. The container mounts it
at `/vault` read-write; Obsidian reads the same files from outside.

## Layout

```
.claude/skills/  agent skills. teach/ is the one that matters.
concepts/        the vocabulary ledger. one note per concept, counters
                 written by the tools. `gate: off` is yours.
curriculum/      GENERATED. one note per canonical topic, seeded from the
                 canon in the repo — a course syllabus, a textbook, or a
                 paper. Your relevance judgments live here.
notes/           subject matter. one directory per subject. Yours.
attachments/     images. derive submissions land here.
logs/            session transcripts written by md_log.
```

`curriculum/` is generated and `notes/` is authored — the split is deliberate,
so seeded material never reads as something you wrote. Seeding only ever
creates; it will not modify a note you have judged, even when the canon moves.
See `docs/curriculum.md`.

```bash
smrt -- smrt-curriculum seed     # create missing topic notes
smrt -- smrt-curriculum audit    # holes, orphans, and what is still unjudged
smrt -- smrt-ledger list         # which terms you keep not naming
```

**`.claude/skills/` is not a style choice, it is the only path that works.**
Skills were at `skills/` until 2026-09-11, where the agent never found them --
so `teach` had never once been loaded. Measured rather than reasoned: the agent
advertises its commands during session setup, and a probe skill placed at each
location showed up from `.claude/skills/` and not from `skills/`. The dot
folder is also invisible to Obsidian, which is a small bonus.

Verify it after any change, for free -- no prompt, no model call:

```bash
smrt -- python3 /workspace/proxy/tests/spawn_session.py vault-tools=vault-tools
```

`teach` should appear in the advertised command list.

## Conventions

- **LaTeX and mermaid** render natively. Use them rather than ASCII.
- **Attachments** go in `attachments/`. Set this in Obsidian:
  Settings → Files & Links → Default location for new attachments.
- **Commit often.** This is a git repo; the history is your learning record.

## Notes on `/subject`

Sessions may be launched with a read-only subject directory mounted. The
teach skill assumes nothing about it beyond "files exist there." If you find
yourself wanting the skill to know it's a Python repo, that's a smell — see
`docs/environment.md`.

**Taking a class?** Mount its material as the subject and import the text as a
canon:

```bash
smrt ~/class/bayes-hierarchical     # the book, lecture notes, problem sets
```

The text then sets the notation, the naming and the scope — the things you are
actually graded on — while the explanation stays free to be better than the
book's. `pdftotext -f 108 -l 113 book.pdf -` is how a lesson reads six pages
instead of seven hundred, and a `locator` in the canon is what says which six.
