# HANDOFF.md

Running log of session-to-session progress and decisions. **Append-only** — do not edit or
delete prior entries. See `AGENT.md` for the full protocol.

Older entries live in `HANDOFF-archive.md`, oldest first. Check it if you need context
from before the entries below.

## Entry template

```markdown
## <YYYY-MM-DD> — <session identifier>

**What changed:**
-

**Why:**
-

**Decisions made:**
-

**Open questions / next steps:**
-

**Synced through:** `<commit hash>`
```

---

## 2026-09-21 — Claude Code — Ling (owner's tab 1 and 2 draft merged into the UI plan)

**What changed:**
- `web/DESIGN.md` restructured around the owner's hand-drawn draft ("Hackathon design.pdf",
  one page, two wireframes). No code written.

**What the draft shows:**
- App shell: left icon rail with Logo, Parsing, Review (open book), Report (bar chart), Database.
- Tab 1 Home: "Ladinglens" + `v0.0.1` badge, Features (OCR, LLM, ML), tagline "Quick, reliable
  email verification. Classify, extract data & compare. All around help, every day, every time."
- Tab 2 Parsing: list on the left with tabs "Need attention" / "All emails"; right pane with
  "Confidence score", "Summary of email", "Groups: Shipping Instruction / Bill of Lading", then
  "Email context & detail". Review, Report and Database are icons only, with no drafts yet.
- The PDF is a vector export with no text layer, so it had to be rendered to be read
  (`pypdfium2`, installed into `.venv` for that only; it is **not** in `requirements.txt`).

**Decisions made in the plan:**
- **Parsing is for inspecting, Review is for acting.** Parsing is read-only over any email;
  Review lists only cases awaiting a person and holds the evidence panel and form. This keeps the
  draft's tab structure and the earlier human-review design. The earlier three list tabs became
  the draft's two; "mismatches only" is a filter.
- Home is the landing screen (per the draft). Two additions the sketch does not have, both
  marked as removable: an "N emails need attention" line on Home, and the run status and Retry
  in the header. The Review icon carries a badge count.
- "Confidence score" = classification confidence (already in every record). "Summary of email"
  starts as the subject plus the first lines of the body, since the pipeline produces no summary.
  "Groups" is read as the documents present (SI, BL), with the category as a separate chip.
- New backend items: a `confirm` review action (agree with the system's verdict), a report CSV
  export, and one `__version__` (0.0.1) surfaced in `/api/status` and `report.json`.
- Hash routes (`#/parsing/{id}`) so it works read-only and cases are linkable.

**Conflicts with earlier scope, flagged and NOT decided:**
- The earlier scope said no persistent DB and no analytics dashboard, but the draft has
  **Database** and **Report** tabs. Proposed: Database = read-only explorer over the existing
  files (no database); Report = the brief's discrepancy report with export, no charts.
- "ML" is listed as a feature, but nothing in the system is a trained model (LLM, OCR + vision
  LLM, fixed rules). Rename or keep is the owner's call.

**Open questions / next steps:**
- The 11 numbered decisions at the end of `web/DESIGN.md` (items 1 to 4 from the first version,
  5 to 11 new). The plan's Review, Report and Database sections are labelled "proposed" and
  should be replaced when the owner drafts those tabs.
- Phase 0 (backend: keep `extracted`, reviews, API, serve UI, version) is still the first job.

**Synced through:** `1493339` (plan left uncommitted for review)


---

## 2026-09-21 — Claude Code — Ling (new UI: backend, Home, Parsing and Database tabs built)

**What changed:**
- **Backend:**
  - `classify_email` now also returns a one-line `summary` (same model call, no extra request);
    `classify_email` returns a 3-tuple and its callers were updated.
  - `ComparisonResult` gains `summary` and `extracted` (every value read from the SI and BL, with
    its source), both written to the record and never to `output.json`.
  - New `app/store.py`: the JSONL checkpoint is **always** written; when `MONGODB_URI` is set
    every record is also copied into MongoDB (`results` and `runs` collections). New
    `app/api.py` (read-only `/api`, plus retrying one email), `app/run_state.py`, and
    `app/__init__.py` holds `__version__ = "0.0.1"`. `main.py` serves `index.html`, `css/` and
    `js/` only, with `Cache-Control: no-cache`.
  - `run.py` takes a `checkpoint` object instead of a path (`checkpoint_path` is gone).
- **UI** (`web/`): replaced the old single-file dashboard with plain JS ES modules and CSS, no
  build step. Icon rail, Home, Parsing, Database, "design in progress" pages for Review and
  Report, a compact run control, light and dark, keyboard (`j` `k` `/` `g h p d`), a narrow-screen
  layout, and the same page running read-only from `report.json`.
- **Tests:** 97 Python (`test_store`, `test_api`, and the extended ladder tests) and 37 JavaScript
  (`tests/js/*.test.js`, Node's built-in runner). `requirements-dev.txt` adds `mongomock` and
  `httpx`; `requirements.txt` adds `pymongo`.
- `web/build_report.py` rewritten: it calls the API's own functions and emits the new format
  (`{version, summary, emails, cases}`). `web/report.json` was **converted** from the old
  520-email snapshot (no summaries; only differing fields), so the Vercel demo keeps working.
- Docs: `web/DESIGN.md` (decisions recorded, storage and phases updated), `README.md`,
  `web/README.md`, `results/README.md`, `.env.example` (MongoDB settings), `AGENT.md` (tests).

**Decisions made (owner's answers):**
- Database is **MongoDB** (reverses the earlier "no DB" scope). "ML" is removed from Home.
  "Summary of email" = a label plus a very short summary. "Groups" = the email labels, used to
  filter the list. Keep the "N emails need attention" line. Keep the run/retry control but make
  it small (owner will check with a friend what it should do). Earlier open questions accepted as
  recommended. Review and Report tabs on hold until the owner drafts them.

**Decisions made (mine, not asked):**
- **The JSONL file stays the source resume reads, and MongoDB is a copy**, not the reverse. A
  database outage then cannot lose a run; a failed copy is recorded in `store.error` and the run
  carries on. The API reads MongoDB when it is configured and non-empty, else the file.
- The Database tab is read-only and never shows credentials (only scheme, host and port).
- Old-run records (no `extracted`) render as "only the differing fields were kept", not as an
  error, so `report.json` from before this change still works.
- A "read by ..." note is shown once per document, and only fields read differently are tagged.

**Verification:**
- Real 12-email run through the new pipeline (`gemini-3.1-flash-lite`): 12/12 have a summary, 4
  kept `extracted`, 0 API failures.
- **Prompt change check:** classify prompt with vs without the summary, 30 emails: 19 comparable
  (11 hit the model rate limit), **all 19 kept the same category**; summaries 12 to 18 words.
  Small sample; re-check when quota allows.
- Browser (built-in pane): Home, Parsing (mismatch, review with evidence, unreadable, failed,
  non-comparison), tab and label filtering, search, `j`/`k`, Database, both placeholder tabs,
  the 375 px layout (fixed an overflow and stacked the field table), and static mode served by
  `python -m http.server` with no API. To see review and failed cases I temporarily appended four
  hand-made records to `results/results.sample.jsonl`, then **restored the original** 12 records.
- Mutation-checked the store (a real verdict overwritten, credentials leaking, a failing mirror
  not contained): each is caught by a specific test.
- **Bugs found by testing in the browser:** native `append(null)` wrote the word "null" into the
  header (added a null-safe `add()`); the mobile list stretched to 681 px; a stale browser cache
  served old JS (added `no-cache` revalidation).

**NOT verified:**
- **MongoDB against a real server.** None is installed (no Docker, no `mongod`); everything ran
  against `mongomock`. **One real check is still needed** with an Atlas URI or a local install.
- **The header's Run and Retry buttons were rendered but never clicked**: they spend model quota,
  and Run asks for confirmation. `POST /api/emails/{id}/retry` and the run state are tested with
  mocks only. `run()` blocks until the run finishes, so the UI polls `/api/status` meanwhile.
- Dark mode was seen on Home only (system theme); the toggle and dark Parsing were not screenshot.
- 800 px (the breakpoint) was not checked, and no full 520-email run has used the new format.

**Open questions / next steps:**
- **MongoDB:** where does it run (Atlas free tier or a local install)? Needed for the one real
  check. Should it stay optional? Recommended: yes.
- **Run and retry:** the owner will confirm with a friend what the control should do.
- **Review and Report drafts** are still to come; `web/DESIGN.md` sections 5.6 and 6.5 are
  placeholders until then. Reviews (write-back, recompute, undo) are not built.
- `ML`: not implemented; reconsider later.
- Rebuild `web/report.json` from a real full run when quota allows, so the demo has summaries and
  all 7 fields.
- `.claude/launch.json` (local preview config) is gitignored, not committed.
- Working notes for the next session: the shell heredoc collapses backslashes (`\b`, `\n`,
  `\x`), so files with regexes or escapes should be written with the Write/Edit tools; and the
  browser pane's screenshots only work after `tabs_select` fronts the tab.

**Synced through:** `334053b` (committed by task: `8c059b5`, `66b54fc`, `4fb134e`, `34176bb`, `334053b`, then docs)

---

## 2026-09-21 — Codex — Brendan (Task 4 reliability)

**What changed:**
- Ported bounded OpenAI-compatible provider retries onto the current multimodal client:
  exactly three application attempts with 0.5s and 1.0s delays for timeouts, connection
  errors, HTTP 408/429, and every 5xx response. SDK retries remain disabled.
- Added metadata-only request/stage logging and failure-stage correlation without logging
  prompts, document contents, provider response bodies, credentials, or exception messages.
- Hardened classification, SI extraction, BL extraction, comparison, worker, and batch
  boundaries so one malformed or failed email produces `NEEDS_REVIEW` without ending the run.
- Added 31 `unittest` cases using the installed OpenAI SDK's real exception classes, including
  vision-mode preservation, concurrent email isolation, checkpoint resume, and exact evaluator
  output keys.

**Why:**
- Task 4 requires transient provider failures to retry predictably while permanent failures
  fail fast, and no individual email failure may terminate or corrupt the batch.

**Decisions made:**
- Did not apply the older `e822ada` patch because `git apply --check` failed against `9986162`.
  The old patch targeted the pre-OCR `_generate` signature and text-only attachment path, so
  forcing it would have replaced newer PDF/DOCX/XLSX/vision work.
- Kept `failure_stage` internal to checkpoint/review records. Evaluator output and the official
  seven comparison fields remain unchanged.
- Kept malformed model JSON and document validation failures non-retryable. Provider failures
  are `processing_error`; unreadable/unsupported documents remain `unreadable`.

**Verification:**
- Installed `requirements.txt` into the existing ignored Python 3.14 virtual environment.
  OpenAI SDK 3.16.2 imports successfully and `pip check` reports no broken requirements.
- `python -m unittest -v`: 31/31 passed with the real SDK; syntax compilation passed.
- Uvicorn started cleanly; `GET /docs` and `GET /openapi.json` returned HTTP 200 and `/run`
  remains present.

**Open questions / next steps:**
- No official dataset is present and `.env` has no `LLM_API_KEY`, so the requested one-email
  real-provider check remains blocked. Do not fabricate either prerequisite.
- Review the uncommitted Task 4 diff before committing. No push, merge, or PR was made.

**Synced through:** `99861622c301b83bf5e5dd687d662a91ff32dda8` (Task 4 changes uncommitted)


---

## 2026-09-21 — Claude Code — Ling (fix after merging brendan-task4)

**What changed:**
- `app/pipeline/run.py` rewritten by hand to combine both branches. The merge commit `62f827b`
  had **left it unable to compile** (a missing comma, stale variable names, and the batch runner
  still using `_load_checkpoint`, `_failed`, `_better_failure` and `checkpoint_path`, which no
  longer exist). Even the parts that parsed were wrong: `_extract_document` still called the
  old `extract_fields(read_document(...))`, which `run.py` no longer imports, so every document
  check would have failed with a `NameError` that Brendan's broad `except Exception` turns into a
  quiet `processing_error`.
- `app/llm_client.py`: `call_vision_json` now follows Brendan's convention for a non-JSON reply
  (log the error type, raise `ValueError("model did not return valid JSON")`) instead of putting
  the raw reply, which can hold document text, in the message.
- `tests/test_pipeline_reliability.py` (Brendan's) adapted to the merged interfaces. Only the
  plumbing changed; every test's intent and assertions are as he wrote them: `classify_email`
  returns `(category, confidence, summary)`, extraction is patched at `run.extract_document`,
  and the checkpoint is a `store.Checkpoint`-shaped object instead of a path.
- New `RealLadderThroughRunTests` in `tests/test_extract_ladder.py`: `process_email` with the
  real extraction ladder and only the model mocked. The other run tests patch
  `run.extract_document`, and Brendan's patched `extract_fields`, so nothing exercised the seam
  that had broken. Simulating the merge bug makes 3 of these 4 tests fail.
- `HANDOFF.md`, `schema.py` and the rest of `llm_client.py` were merged correctly and needed no
  change: no line from either parent is missing from `HANDOFF.md`, and there are no duplicate
  entries.

**What the merged `run.py` now does (both sides kept):**
- From Brendan: per-stage failure isolation with `failure_stage`, metadata-only logging (email
  ID, stage, error type; never document text), invalid or duplicate email IDs contained,
  worker and batch boundaries, and the scheduled ID being authoritative.
- From this branch: the email `summary`, every value read (`extracted`), `field_issues`, the
  extraction ladder via `extract_document`, and the `checkpoint` object (file, plus MongoDB).
- Failures keep what was already known: category, confidence and summary survive a later-stage
  failure. `failure_stage` and `summary` are in the stored record, never in `output.json`.

**Verification:**
- 132 Python tests and 37 JavaScript tests pass (31 of the Python ones are Brendan's).
- A real run of the merged pipeline on 6 emails (`gemini-3.1-flash-lite`, temp results folder):
  5 `OK`, 1 `MISMATCH`, no failures, 6 of 6 with a summary, 3 with extracted values, and the
  submission keys unchanged.
- **Not verified:** Brendan's own open item (a one-email real-provider check with his retry
  settings) is covered only by that 6-email run, and I did not exercise a real 429 to see the
  new 3-attempt backoff.

**Open questions / next steps:**
- **The pushed merge commit `62f827b` is broken.** Commit this fix before pushing, or before the
  PR is merged, so `main` never holds a `run.py` that does not compile.
- Brendan reduced retries from 5 to 3 attempts (0.5 s and 1.0 s) and stopped retrying HTTP 409.
  With the free tier's per-minute limits that is a much shorter wait than before; if 429s become
  common in a full run, revisit the delay.

**Synced through:** `a6f0a5d` (the merge `62f827b`, then the fixes `be619b2` and `a6f0a5d`)


---

## 2026-09-21 — Claude Code — Ling (Report tab, dashboard, Review, run controls, three merges)

**What changed:**
- **Report tab built** (`web/js/views/report.js`), from the owner's old single-page dashboard: four
  headline numbers, the escalation note, an Inbox mix card (three insights and one bar per label),
  and the emails **folded by label** (closed by default, 25 rows at a time, "Show more") so 520
  emails do not make a 520-row page. Full width. Each row has a priority and a one-line next step
  and opens the email in Parsing. Result pills with counts, search, **Copy summary** and **Export
  CSV** (exports what is currently shown). The logic is pure and unit-tested in `web/js/store.js`
  (`reportTiles`, `reportInsights`, `escalationNote`, `priorityOf`, `nextStep`, `sortByPriority`,
  `rowsToCsv`, `reportGroups`, `statusCounts`, `summaryText`, `runPlan`).
- **Home is now ZuYenn's dashboard** (hero, five tiles, Inbox mix, searchable review queue); on
  top of it, the queue got a **Priority** and a **Next step** column and is ordered by priority.
  A saved theme is applied by an inline script in `web/index.html` before first paint, so a dark
  page no longer flashes light.
- **Review tab** (ZuYenn's UI, corrections kept in `localStorage`): added a **demo delegation**
  box that Colt asked for. Type a name, press Send, and the case moves to a **Delegated** tab with
  a "Delegated to {name}" chip; Take back returns it. Nothing is sent anywhere; it is kept in the
  browser (`ladinglens-review-delegations-v1`). Also a Retry button for failed cases, and an
  empty pane that says failures on the model API are usually a quota problem.
- **Parsing and Review share one scaffold**, `web/js/components/casepane.js` (the two panes,
  opening an email, loading its case, `j`/`k`, the original email and documents, Retry). Each view
  keeps only its own part. They link to each other for the same email. "Needs a person" is one
  rule, `needsPerson` in `store.js`, used by Review's queue, the Parsing link and the Home queue.
- **Run controls.** `POST /api/run/stop` and a **Stop** button: emails in flight finish and are
  saved, the rest are left alone, and a stopped run does **not** rewrite `output.json` (a partial
  run must never replace a full one). `/api/status` reports `stopping`. `POST /run?new_only=true`
  (**Run N new**) processes only emails with no saved result and leaves every saved one, failed
  ones included, alone, so adding emails to the inbox does not re-run the old ones. **Retry N**
  is `resume=true` (retries failures, does new emails). **Start over** is a fresh run.
- **Backup before a fresh run.** A fresh run replaces `results.jsonl`, so it now first copies it
  to `results.jsonl.<timestamp>.bak`, but only if it holds at least one real verdict, so a run of
  failures never pushes a good backup out. The Start over confirmation now says it replaces the
  saved results and that a backup is kept; the run bar reports where the backup went.
- **Merges** (all into `ling-2`/`Ling`): `feat/colt` (compare tuning: a party field also matches
  when one side is the other plus an address, `scripts/recompare.py`); `ZuYenn` (the dashboard
  redesign and the Review tab, above); `main` (Dockerfile, `.dockerignore`, the dataset-free
  `POST /process`, `ocr_cache/` ignored).
- Tests: 144 Python and 54 JavaScript, all passing. `DESIGN.md`, `README.md` and
  `results/README.md` updated to match.

**Why:**
- The owner wanted the dashboard as the main page, the Report tab filled in, and a way to stop a
  run. Colt asked for delegation on emails that need a person. The backup and new-only mode came
  from a real risk: the Run button used to delete saved results before spending any quota.

**Findings:**
- **Every run currently fails, and it is the model quota, not the code.** A direct call returned
  Gemini **HTTP 429, "exceeded your current quota"** (free tier, limit 20 requests for
  the configured Gemini model). All 268 records in `results/results.jsonl` are `processing_error` at
  classification, so nothing has actually been checked. `output.json` was never written because
  no run completed.
- Viewing (Home, Parsing, Review, Report, Database) only reads the saved records. Only Run, Run N
  new, Retry and the per-email Retry call the model.

**Decisions made:**
- **`web/report.json` conflicted in every merge.** Colt regenerates it in the old flat format; the
  app reads the new format. For his merge I converted his newer data to the new shape with a
  throwaway script after proving it reproduces the existing file exactly from the old base; in
  the other merges this branch's file was already the newer one and was kept. The script is not
  committed. Alternative rejected: taking either side, which loses data or breaks the UI.
- **ZuYenn's `web/index.html` conflict:** kept the modular app. His single-file page is a redesign
  of the old dashboard; taking it would have replaced the app shell. It stays in `origin/ZuYenn`.
  His `home.js` (the same design, built in the modular app) replaced my simpler Home.
- **Parsing/Review duplication:** shared component, both tabs kept (over merging them into one
  tab), to keep the owner's five-tab design.
- **Stop is cooperative**, not thread-killing, so nothing is left half-written.
- **`new_only` is separate from `resume`** because resume retries failures and the owner wanted
  previous emails left alone.
- Priority order (mismatch, then review, then clean) on Home and Report; Parsing and Review keep
  the older order (failed, review, mismatch).

**Open questions / next steps:**
- **Fix the model quota** (wait for reset, change `LLM_MODEL`, or use another key), then use
  **Run N new** or **Retry N**. Avoid **Start over** until then; it would replace the saved
  results with more failures (a backup is kept only if they hold a real verdict).
- Restart uvicorn after pulling; it picks up backend changes only with `--reload`.
- `scripts/poll.py` still calls `resume=true`, so it retries failed emails every tick and spends
  quota. Consider `new_only=true`.
- The Home queue shows only the first 12 rows while its counter reads "520 of 520 emails"
  (ZuYenn's design). Needs "Show more" and a correct counter.
- `DESIGN.md` section 6.2 still describes the old Home.
- `web/report.json` is the converted older 520-email snapshot (no summaries). Rebuild it with
  `python web/build_report.py` after a real run; if someone regenerates it in the old format the
  conflict will return.
- Review corrections and delegations live only in the browser. Delegation is a demo; a real one
  needs a backend and a notification.
- A fresh run replaces the MongoDB copy too; the `.bak` file is the copy to restore from.
- `HANDOFF.md` is well past the ~5-entry limit in `AGENT.md`; older entries should move to
  `HANDOFF-archive.md` as a separate small commit.
- An untracked `results.jsonl` sits at the repo root. It is not from this session; check it.

**Synced through:** `543e006` (this entry is committed after it)

---

## 2026-09-21 — Claude Code + Colt (0.9594, deployability, Excel, inbox simulation)

**Score: 0.8515 -> 0.9594.** End-to-end 38/46 -> **46/46**; defect precision 0.793 ->
0.979; field-level F1 0.791 -> 0.993.

**What changed:**
- `app/pipeline/compare.py`: a party field now matches when one side is the other plus
  extra text. Restricted to `shipper`, `consignee`, `notify_party`.
- `scripts/recompare.py`: re-applies stage 3 to a finished run **offline**.
- `scripts/export_excel.py`: a run -> `results/ladinglens.xlsx`, two sheets.
- `scripts/feed_inbox.py`: drips dataset emails into `data/live/` so a poller has real
  arrivals to find.
- `POST /process` + `Dockerfile` + `.dockerignore`: deployable without the dataset.
- `.gitignore`: `ocr_cache/`, `data/live/`, and every `.env.*` variant.
- `README.md`: new sections for Excel, inbox simulation and deploying; bash **and**
  PowerShell for every command.

**Why the comparison fix mattered most:**
- All 8 end-to-end failures were routed *and* flagged correctly -- they failed only on
  the exact field set. Every spurious field was a party where one document carried the
  address and the other did not (`KTP CO., LTD` vs `KTP CO., LTD, KTP BLDG, 36 ...`).
  Same party, two levels of detail, counted as a discrepancy.
- **This corrected an earlier wrong diagnosis in this log.** The `SI_REQUEST` /
  `BL_COMPARISON` confusion was assumed to be the remaining gap; it is not. All 46 gold
  defect emails were already classified correctly. That confusion costs stage 1
  (weight 0.3) only -- worth fixing, but it was never the end-to-end blocker.

**Decisions made:**
- The prefix rule is **not** applied to non-party fields: on `container_count` it would
  let "3" match "30" and hide a real defect. Verified against ground truth: fixes all 8,
  breaks none of the 38 already passing.
- `recompare.py` exists because stage 3 is deterministic and the per-field values are
  already in `results.jsonl` -- a comparison change can be re-scored for free. It is
  only valid when a change *relaxes* comparison; fields equal at run time are not
  recorded. The docstring says so.
- Excel is generated **deterministically, with no LLM call**. A model was proposed for
  it; every value is already captured, so asking one to restate it would spend quota and
  let hallucinated values into a file that looks authoritative.
- The inbox feeder copies real files into a folder the ordinary loader reads, rather
  than adding a fake `Inbox` class -- no demo-only code path in the pipeline.
  Attachments land before the email JSON, or the pipeline banks `missing_attachment`.
- The image ships `web/` (the app serves the UI at `/`, and Render health-checks `/`)
  but never the dataset.

**Traps worth remembering:**
- **`mongomock` reads the `MONGODB` env var as a version string.** The MongoDB installer
  sets it to a bin path, so `int()` fails on `'C:\Program Files\MongoDB\Server\8'`.
  8 tests fail on any machine with MongoDB installed; CI is unaffected. Forcing
  `MONGODB=5.0.5` before import gives **132 passed, 0 failed**. Fix belongs in a
  `conftest.py` pinning `mongomock.SERVER_VERSION`.
- **`web/report.json` is a committed generated file.** It resolves to whoever's snapshot
  git picks in a merge, and goes stale after every run -- it showed 64 escalations
  instead of 35 for exactly this reason. Run `python web/build_report.py` after any run
  or merge. It only matters in static mode; a served instance reads `/api/report` live.
- Git Bash cannot unset Windows-level environment variables for a child Python process
  (`env -u` and inline assignment both fail); set them inside Python instead.

**Open questions / next steps:**
- `BL_COMPARISON` recall 0.67 / `SI_REQUEST` precision 0.64 -- 68 of 83 classification
  errors are that one confusion. All 68 missed emails say "draft BL" *and* "for
  checking"; none say "shipping instruction" or "please find". The classify prompt's
  "usually with SI + draft BL attached" is what rejects the 94 attachment-less ones.
  Stage 1 is weight 0.3, so the ceiling here is roughly 0.99.
- The Docker image has **never been built** -- the daemon was down throughout. Render
  may be its first real build.
- `HANDOFF.md` is now 20 entries against `AGENT.md`'s ~5. Archiving is overdue.

**Synced through:** `fb16662`
