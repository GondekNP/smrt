# Vault

> Seeded from `vault-template/`. Edit freely — this is yours now.

Open this directory as an Obsidian vault on the host. The container mounts it
at `/vault` read-write; Obsidian reads the same files from outside.

## Layout

```
skills/        agent skills. teach/ is the one that matters.
notes/         subject matter. one directory per subject.
attachments/   images. derive submissions land here.
logs/          session transcripts written by md_log.
```

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
