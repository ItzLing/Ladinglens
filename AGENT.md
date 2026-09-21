# AGENT.md

Instructions for any coding agent (Claude Code or otherwise) working in this repository.

## Project

Shipping document verification system — classifies inbox emails, extracts fields from
Shipping Instruction (SI) and Bill of Lading (BL) attachments, compares them, and reports
mismatches. See the project brief and `loader.py` for data access details.

## Session handoff protocol

Multiple people and multiple agent sessions touch this repo. `HANDOFF.md` is the shared
memory across all of them — treat updating it as part of finishing the work, not optional.

### At the start of every session

1. `git pull` to get the latest changes.
2. Read `HANDOFF.md` in full to catch up on recent decisions and progress.
   If `HANDOFF-archive.md` exists and you need older context, check that too.
3. Note the `Synced through: <commit hash>` from the most recent entry — if you need the
   full diff behind a summary, run `git diff <hash>..HEAD`.

### At the end of every session

Append a new entry to `HANDOFF.md` — never overwrite or delete prior entries. Do this even
for small or exploratory sessions; a short entry beats a missing one. Append your entry
**before** your final commit so the commit hash you record is accurate, or immediately amend
it after if needed.

Each entry must include:

- **Date and session identifier** — who/what ran this (e.g. "Claude Code — Ling" or
  "Claude Code — Wei")
- **What changed and why** — plain language, not just a commit list
- **Decisions made** — including alternatives considered and rejected, briefly
- **Open questions / what's next** — anything the next session should pick up or be aware of
- **Synced through:** `<commit hash>` — the commit your work is caught up to as of this entry

Use the template at the top of `HANDOFF.md` for exact formatting.

### Keeping HANDOFF.md manageable

If `HANDOFF.md` grows past ~5 entries, move the older ones into `HANDOFF-archive.md`
(append them there in the same format), keeping only the most recent entries inline. Do this
as a small, separate step — don't fold it into an unrelated feature commit.

## General conventions

- (Add language/framework/style conventions here as they're decided.)
- Tests: `python -m unittest discover -s tests` from the repo root. They mock OCR and the
  LLM calls, so they need no API key and no Tesseract.

## Commit message convention

Use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): message`.

- **type** — what kind of change it is:
  - `feat` — a new feature or new file that adds behavior
  - `fix` — a bug fix
  - `docs` — documentation only (README, AGENT.md, HANDOFF.md, comments)
  - `chore` — setup/config work that isn't a feature (dependencies, .gitignore, env templates)
  - `refactor` — code change that doesn't add a feature or fix a bug
  - `test` — adding or fixing tests
- **scope** — the short name of the part of the app the change touches, e.g. `schema`,
  `classify`, `extract`, `compare`, `pipeline`, `api`, `data`, `docs`.
- **message** — one short line, plain language, describing what the commit does.

Examples:

```
feat(parse): "message"
feat(auth): "Add login validation for user emails"
feat(schema): "Add data models for the pipeline"
fix(compare): "Fix mismatch check missing empty values"
docs(agent): "Add commit message rules"
chore(deps): "Add requirements.txt"
```

Prefer one commit per file (or per tightly related pair, like a module and its
`__init__.py`) so the history reads as a clear list of what each file does, rather than
one large commit per session.
