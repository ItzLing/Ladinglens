# Ladinglens UI: plan and design

Status: **decisions recorded 2026-09-21; phases 0 to 3 built** (see section 9). Based on the owner's hand-drawn
draft of tabs 1 and 2 ("Hackathon design.pdf") and their answers to the open questions. The
**Review** and **Report** tabs are on hold until the owner drafts them. Build order is in
section 9.

## 1. Goal

A reviewer opens the app and sees, within seconds, which emails need them and why. They
compare the SI against the draft BL side by side, look at the evidence for anything the
system would not guess, settle it, and the report updates. That is the brief's "Ask for help"
capability and its reliability requirement, so most of the work is a person-in-the-loop flow,
not a nicer table.

What the brief asks the report to do, and where this design meets it:

| Brief says | Design answer |
|---|---|
| "easy to see which email was checked, whether a mismatch was found, and exactly what needs attention" | Parsing tab with a Need attention list; the case opens on why it needs attention |
| "showing the SI and BL values side by side" | All 7 fields in one table, differing words highlighted |
| "If all seven fields match, report 'No mismatch detected.'" | That exact sentence in the case pane |
| "send the case for review with the source evidence and reason" | Review tab (on hold): evidence panel plus the reason |
| "Let a person confirm or correct it, then update the report" | Review tab (on hold): a form that writes a decision |
| "Handle processing failures visibly and allow retries" | Failed chip, plain-language banner, retry |

## 2. The owner's draft and decisions

### 2.1 What the sketch shows

- **App shell.** A narrow icon rail on the left: **Logo**, **Parsing**, **Review** (open book),
  **Report** (bar chart), **Database**. The main area has the title "Ladinglens".
- **Tab 1, Home.** Title with a `v0.0.1` badge, a divider, **Features**, a divider, then the
  tagline: "Quick, reliable email verification. Classify, extract data and compare. All around
  help, every day, every time."
- **Tab 2, Parsing.** Left: tabs **Need attention** and **All emails**, then a list of emails.
  Right: **Confidence score**, **Summary of email**, **Groups**, a divider, then **Email
  context and detail**.

### 2.2 Decisions (owner's answers, 2026-09-21)

| Topic | Decision |
|---|---|
| Database | **MongoDB.** This reverses the earlier "no persistent DB" scope. Design in section 5 |
| Features on Home | **OCR and LLM only.** "ML" is removed; it is not implemented and will be reconsidered later |
| Summary of email | A **label** saying what the email is, plus a **very short summary** of it |
| Groups | The email **labels** (for example SI request, BL comparison, spam), used to **filter** the list |
| "N emails need attention" line on Home | **Keep** |
| Run and retry in the header | **Keep, but smaller.** The owner will check with a friend what the function should do |
| Earlier open questions | **Accepted as recommended:** review write-back is in scope, reviewer name is optional, reviewers edit only flagged fields, the read-only Vercel demo stays |
| Review tab | **On hold.** The owner will design it and come back |
| Report tab | Built from the owner's old dashboard: four numbers, a category chart, and the emails folded by label |

### 2.3 How the draft maps onto the plan

| Draft | In this plan |
|---|---|
| Icon rail with 5 destinations | The app shell (6.1). Review shows a "design in progress" page for now |
| Home | Tab 1 (6.2) |
| Parsing: list left, detail right | Tab 2 (6.3) |
| Tabs "Need attention / All emails" | The list tabs; group chips filter within them |
| Confidence score | Classification confidence, already in every record |
| Summary of email | Label plus one-sentence summary written by the classifier (B2) |
| Database | Tab 5: a read-only MongoDB explorer (6.4) |

**Parsing is for inspecting, Review is for acting.** Parsing is read-only over any email and
shows what the system did. Review, when designed, is where a person changes something.

## 3. Where we started

`web/index.html` is one file (inline CSS and JS) over a static `report.json`. It shows summary
tiles, category bars, a filterable table and a modal diff. It is read-only.

Gaps against the brief:

1. No write path (a person cannot confirm or correct anything). Deferred with the Review tab.
2. No retry, and processing failures are only a banner sentence.
3. The diff shows only mismatched fields, never all 7, and has no "No mismatch detected" state.
4. `field_issues` (reason and evidence) are not shown, and scan images cannot be seen.
5. It is overview-first, and the draft asks for a navigable app instead.

Backend gaps that block the design:

- **Run records do not keep the accepted SI/BL field values**, only `mismatches` and
  `field_issues`. A side-by-side of all 7 fields needs them.
- There is no email summary, and no per-email endpoints.
- Results live only in `results/*.jsonl`; the "latest record per email" logic exists twice.

## 4. Decisions (design)

| Decision | Choice | Why |
|---|---|---|
| Stack | Plain JavaScript ES modules and CSS, **no build step** | Matches the request; nothing to break at demo time. **Supersedes the earlier "Streamlit frontend" line.** |
| Navigation | Hash routes (`#/parsing/email_004`) | Works with no server support, so it also works read-only; a case can be linked |
| Serving | FastAPI serves `index.html`, `css/` and `js/`, and the API under `/api` | One origin, no CORS, one command to run. Nothing else in `web/` is exposed |
| Deploy | The same UI runs **read-only** from `report.json` when there is no API | Keeps the Vercel demo working |
| Storage | **MongoDB** for results and runs. The **JSONL file is always written too**, as the crash-safe checkpoint | Owner's decision. A database being down can never lose a run, and tests, the static demo and machines with no database keep working |
| Recompute | After a review (when built), `compare.py` recomputes the verdict | Comparison stays deterministic Python |
| Auth, websockets | None. The UI polls `/api/status` while a run is active | Matches the stated scope |
| Design language | Keep the current tokens (warm neutrals, blue accent, semantic status colours) | Already light/dark and accessible; refine, do not restart |

## 5. Backend work (do first)

### 5.1 Storage (B1)

`app/store.py` always writes the JSONL checkpoint, and when `MONGODB_URI` is set it also copies
every record into MongoDB. A copy that fails is recorded and the run carries on. Reads prefer
MongoDB and fall back to the file.

| | Always | When `MONGODB_URI` is set |
|---|---|---|
| Results | `results/results.jsonl`, written as each email finishes | Also copied into the `results` collection: one document per email and scope |
| Runs | Not kept | Collection `runs`: one document per run |
| Resume | Reads the JSONL | Unchanged: it still reads the JSONL |
| The web app reads | The JSONL, if MongoDB is not configured, is empty or is unreachable | MongoDB |

Settings in `.env`: `MONGODB_URI` and `MONGODB_DB` (default `ladinglens`).

A `results` document is `{scope, email_id, record, attempts, updated_at}`, where `scope` is
`full` or `sample` (so a `?limit=N` run never overwrites a full one), `record` is exactly what
`results.jsonl` holds today, and a unique index on `(scope, email_id)` makes writes idempotent,
which is what resume needs. A `runs` document is `{run_id, scope, started_at, finished_at,
limit, resume, counts, model, version}`.

`output.json` and `classify_cache.json` are still written to `results/` for scoring and
submission, whichever store is used. The raw dataset (inbox and attachments) stays in files,
read through `data/loader.py`, because that is the hackathon's interface.

**Not yet verified against a real server.** No MongoDB is installed on the dev machine (no
Docker, no `mongod`). The Mongo store is tested with `mongomock` (an in-memory fake) and needs
one real check once a server or an Atlas URI is available. The `pymongo` driver is in
`requirements.txt`.

### 5.2 Email label and summary (B2)

The classify reply gains a `summary`: one sentence, at most 20 words, in the same call, so it
costs no extra request. The category instructions are left unchanged. Because the classifier is
scored, the change is checked by running the old and new prompt on a sample and comparing the
categories before it is accepted. **Checked:** 30 emails were sampled across the inbox; 19 could be
compared (11 hit the model's rate limit) and all 19 kept the same category, with summaries of 12
to 18 words. The sample is small, so re-check it when quota allows. The summary is internal: it is stored in the record and
never added to `output.json`. If it is missing, the UI shows the subject instead.

The **label** is the category (`BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`,
`SPAM`), shown with a friendly name.

### 5.3 Keep the extracted values (B3)

`ComparisonResult` gains `extracted`: for each of SI and BL, the 7 accepted values (empty where
unresolved), where each came from (`text`, `ocr`, `ocr_llm`, `vision`) and the file. Written
to the record. `output.json` is unchanged. Records from older runs have no `extracted`, and the
UI falls back to showing only the differing fields for them.

### 5.4 API (B4, read-only)

| Endpoint | Purpose |
|---|---|
| `GET /api/report` | Summary plus one light row per email (no document text) |
| `GET /api/emails/{id}` | Full case: body, document text, `extracted`, `field_issues` |
| `GET /api/emails/{id}/documents/{SI\|BL}/pages/{n}.png` | Page image for a scan |
| `POST /api/emails/{id}/retry` | Re-run one email; fails visibly if the model API is still down |
| `GET /api/status` | Running or idle, progress, failed count, app version, storage backend |
| `GET /api/db/status` | Backend, connected or not, database name, collection counts (credentials never shown) |
| `GET /api/db/collections/{name}` | Read-only page of documents, filterable by `email_id`, limit capped |
| `POST /run` | Existing. "Retry failed" and "Continue" call it with `resume=true` |
| `POST /api/run/stop` | Stop the run in progress after the emails already being processed; 409 when nothing is running. What finished is kept, so `resume=true` carries on. `/api/status` shows `stopping` meanwhile |

The existing `/run` and `/status` stay, since `scripts/poll.py` uses them. Collection names are
checked against a whitelist. Nothing writes through the database endpoints.

### 5.5 Serve the UI, and the version (B5, B6)

FastAPI serves `index.html` at `/` and `css/`, `js/` as static folders, so
`uvicorn app.main:app` is the only command a reviewer runs. One `__version__` (`0.0.1`, as
drawn) is returned by `/api/status` and written into `report.json`, so the header badge works
read-only too.

### 5.6 On hold with the Review tab

Reviews (`set_value`, `unresolvable`, `confirm`, `dismiss`, undo), the recompute step, and the
report exports. When the Review draft arrives they use a `reviews` collection in the same store,
append-only, overlaid on the model output.

## 6. App design

### 6.1 Shell (every tab)

- **Icon rail** on the left, as drawn: Logo (goes Home), Parsing, Review, Report, Database.
  Icons only, so each has an accessible name and a tooltip. The current tab is highlighted.
  Review opens a short "Design in progress" page for now.
- **Header:** "Ladinglens" as the title. On the right, a **small** run control: a status dot
  with "Idle" or "212 of 520", a **Stop** button while a run is going (it says "Stopping…" until
  the emails in flight finish), **Continue (n)** for the emails a stopped run has not reached,
  **Retry failed (n)** once everything has been reached, and a **Run** button (which asks for
  confirmation because it spends model quota). It is deliberately compact: the
  owner will confirm with a friend what it should do.
- Under 800 px the rail becomes a bottom bar and the two panes stack, with a Back control.
- Routes: `#/` Home, `#/parsing`, `#/parsing/{id}`, `#/review`, `#/report`, `#/data`.

### 6.2 Tab 1: Home

As drawn: title with the `v0.0.1` badge, a divider, **Features**, a divider, the three tagline
lines.

| Tile | One-line description |
|---|---|
| OCR | Reads scanned pages and reports how sure it is about every word |
| LLM | Classifies emails and maps differently labelled fields |

Below the tagline, one line: "72 emails need attention. Open the list", from `/api/status`. In
read-only mode it shows when the report was generated instead.

### 6.3 Tab 2: Parsing

Left pane (the list):

- Tabs **Need attention** (review, mismatch and failed) and **All emails**, as drawn.
- **Group chips** above the list filter by label, each with a count: SI request, BL comparison,
  Invoice query, General, Spam. Choosing one narrows whichever tab is open. A search box covers
  subject, sender and ID.
- Each row: email ID, subject, its label, and one status chip.

| Status chip | Colour | Icon | Text |
|---|---|---|---|
| Review | amber | triangle | "2 to review" or the reason ("Unreadable") |
| Mismatch | red | x | "2 mismatches" |
| No mismatch | green | check | "No mismatch" |
| Failed | grey with amber ring | refresh | "Failed. Retry" |
| Not a comparison | grey | none | No status; the label is enough |

Right pane (the detail), top to bottom, matching the sketch:

1. **Label and confidence score.** The email's label as a chip, and the classifier's confidence
   in it (0 to 1), for example `0.98`. It shows a dash for a failed email. OCR confidence per
   field lives with the evidence, not here.
2. **Summary of email.** The one-sentence summary; the subject if there is none.
3. **Groups.** The label, as the chip that also filters the list.
4. A divider, then **Email context and detail**:
   - **Status banner** saying why the case is here, in plain words. For example "2 fields on the
     SI could not be trusted", or "Processing failed. This is not a verdict on the documents."
   - **Field table** with all 7 fields: Field, SI (reference), BL (draft), Result. Words that
     differ are highlighted. If everything matches, the sentence "No mismatch detected."
     appears. Unsettled fields are amber, and a small tag shows how each value was read (text,
     OCR, vision).
   - **Email body** (collapsible) and the **documents** (text, or the page image for a scan).

Parsing never writes anything.

### 6.4 Tab 5: Database (MongoDB)

A read-only explorer of what the system has stored. Never edits.

- **Connection card:** backend (MongoDB or files), connected or not, database name. Credentials
  are never shown. When no URI is configured it says "MongoDB is not configured. Using files in
  results/." and shows the two settings to add.
- **Collections:** a list with document counts (`results`, `runs`).
- **Documents:** a paged table for the chosen collection, filterable by email ID, with a
  document opening as formatted JSON.

### 6.5 Tab 3: Review (on hold)

The rail shows it and it opens a "Design in progress" page. Nothing further is built until the
owner's draft arrives. The earlier idea (a Review workspace with an evidence panel and form) is
kept only as a suggestion for that draft.

Parsing and Review share one scaffold, `components/casepane.js`: the two panes, opening an email,
loading its case, `j` / `k`, the original email and documents, and the Retry button. Each view keeps
only its own part (Parsing its filters and field table, Review its queue rules, corrections and
delegation) and links to the other tab for the same email. What counts as "needs a person" is one
rule, `needsPerson` in `store.js`, used by Review's queue, the Parsing link and the Home queue.

**Delegation (demo).** Every case in the queue has a "Delegate this case" box: type a name,
press **Send to {name}**, and the case moves to a **Delegated** tab with a "Delegated to {name}"
chip. **Take back** returns it. Nothing is sent anywhere; the hand-over is kept in the browser
(`localStorage`, key `ladinglens-review-delegations-v1`). It is a stand-in until a real
notification exists. It was asked for by Colt.

### 6.6 Tab 4: Report

The old single-page dashboard, moved into the app and widened to fill the screen, with the ideas
from ZuYenn's redesign added. From the top:

- **Four numbers:** emails processed, comparison requests, mismatches found, escalated to a
  human. **Copy summary** puts them on the clipboard as text; **Export CSV** downloads the
  emails currently shown (priority, email, subject, sender, label, result, confidence, next
  step, fields flagged).
- **A note** when many emails were escalated for one reason (a failed model API, or attachments
  that could not be read), so a big number is never unexplained.
- **Inbox mix:** three reading aids (automation ready %, action required, document checks) above
  one bar per label.
- **Emails, folded by label.** Every label is a closed fold showing its count and how many
  mismatches and reviews are inside, so the page stays short. A fold shows 25 rows at a time
  with "Show more". A row opens the email in Parsing. Each row carries a **priority** (High for
  a mismatch, Medium for a review, Low for a clean check), its result chip, and a one-line **next
  step**; rows are ordered by priority. Result pills (All, Mismatch, Needs review, No mismatch,
  each with its count) and a search sit above the folds; while either is set the matching folds
  open by themselves, and they fold again when it is cleared.

It reads the same report as Home and Parsing, so it works in the live app and in the demo.

Home is ZuYenn's dashboard ("Shipping operations console"): the hero with the four-step route
(Classify, Extract, Compare, Review), five headline tiles, the Inbox mix, and a searchable
review queue. A queue row opens the email in Parsing, or in Review when it needs a person.

### 6.7 Theme

Light and dark share one set of tokens (`tokens.css`); nothing in the views sets its own colours.
The button at the bottom of the rail switches between them, follows the system theme until the
reader chooses, and remembers the choice (`localStorage`, key `ladinglens-theme`). A small inline
script in `index.html` applies the saved theme before the first paint, so a dark page never
flashes light.

## 7. Shared design

### 7.1 Principles

1. **Say what needs a person first.** Home links to it, the Need attention tab lists it.
2. **Evidence next to the decision.** Nobody has to hunt for the source.
3. **Never colour alone.** Every status has an icon and a word.
4. **Keyboard first.** A reviewer works through a list.
5. **Honest about failure.** An API failure never looks like a verdict on a document.

### 7.2 Visual system

- Tokens in `css/tokens.css`, lifted from the current page: surfaces `#f4f4f2` / `#fcfcfb` /
  `#eceae5`, blue accent, good / warning / critical with matching text colours, and the dark
  set. Add a spacing scale (4 px steps) and a type scale (12, 13, 14, 16, 20).
- Radius 8 px for controls, 12 px for panels. Hairline borders, no shadows except focus rings.
  The sketch's ruled dividers become hairlines.
- Monospace for IDs, values and evidence. One accent-filled button per view.
- Respects `prefers-color-scheme`, keeps a manual theme toggle, and honours
  `prefers-reduced-motion`.
- Copy is sentence case and plain. Buttons start with a verb. Errors say what happened and what
  to do, with no raw exception text.

### 7.3 Keyboard

`g` then `h`, `p`, `d` jump to Home, Parsing, Database. In a list, `j` and `k` move, `Enter`
opens, and `/` focuses search.

### 7.4 Accessibility

Landmarks (nav for the rail, header, main). Rail icons have text names and a visible focus
ring. Lists are listboxes with `aria-selected`. Status changes are announced. Contrast meets
WCAG AA in both themes.

### 7.5 States

| State | What the user sees |
|---|---|
| Loading | Skeleton rows |
| API unreachable, `report.json` present | Read-only "Demo" badge; run and retry hidden; Database says it needs the API |
| Neither available | "Could not load results" with what to run |
| Empty list | "Nothing needs attention." with a link to All emails |
| Every record is a failure | Full-width banner: the API failed, nothing was checked |
| MongoDB configured but unreachable | Database tab shows the error in plain words; the app keeps working from files |

## 8. Files

```
app/
  store.py              result store interface, MongoDB and file implementations
  api.py                the /api router
  __init__.py           __version__
web/
  index.html            shell only
  css/tokens.css        colours, spacing, type, radius (light and dark)
  css/base.css          reset, typography, focus, utilities
  css/layout.css        rail, header, two-pane layout, responsive rules
  css/components.css    chips, buttons, table, banner, forms
  js/package.json       {"type": "module"}, so Node can test the pure modules
  js/main.js            start-up, hash router, keyboard
  js/api.js             live adapter and static adapter, same interface
  js/store.js           state, selectors (filter, group counts, sort)
  js/views/home.js      tab 1
  js/views/parsing.js   tab 2
  js/views/data.js      tab 5
  js/views/report.js    the Report tab: numbers, chart, emails folded by label
  js/views/soon.js      "Design in progress" for Review
  js/components/        rail.js, runbar.js, fields.js, chips.js, casepane.js
  js/util/              diff.js (word diff), format.js, dom.js
  report.json           static demo data (kept, tracked)
  DESIGN.md             this file
tests/js/               node:test for the pure modules
```

## 9. Build order

| Phase | Deliver | Done when |
|---|---|---|
| 0 Backend | Store (Mongo + files), summary, `extracted`, version, read-only API, serve UI | **Built.** A run records label, summary and all 7 fields; the API answers; the file and mock-Mongo stores pass the same tests |
| 1 Shell and Home | Tokens, rail, router, header, adapters, **tab 1** | **Built.** Rail navigates, version shows, Home matches the sketch |
| 2 Parsing | **Tab 2**: list, tabs, group chips, detail, all-7 table, word diff | **Built.** A mismatch, an OK, a review and a failed email each render correctly |
| 3 Database | **Tab 5**: connection card, collections, documents | **Built** and checked on the file backend; the Mongo path is tested only against the in-memory fake |
| 4 Run and retry | Compact header control, status polling, retry one and all | **Built** (compact), waiting for the owner to confirm what it should do. Not yet exercised with a live full run |
| 5 Polish | Keyboard, dark, responsive, states in 7.5 | Mostly built: keyboard, light and dark, 375 px stacking, the read-only demo. Not yet done: a check at 800 px, and the loading skeleton on slow connections |
| Later | Review tab, and its backend (5.6) | After the owner's draft |

## 10. Testing

- **JavaScript:** `node:test` (Node 24 is installed, no dependencies) for the pure code: word
  diff, list filtering and sorting, group counts, the router.
- **Python:** both stores against the same test suite (`mongomock` stands in for MongoDB),
  and the API routes.
- **Browser:** drive the real app with the built-in browser: open a mismatch, filter by group,
  force a failure and retry, switch themes, resize to 375 px.
- **Real MongoDB:** one manual check when a server or Atlas URI exists.

## 11. Risks

- **MongoDB is unverified here.** Only the in-memory fake has run. Mitigated by keeping the
  store interface tiny and the file fallback.
- **A summary in the classify reply could change classification.** Mitigated by comparing old
  and new categories on a sample before accepting the change.
- **Scans need Tesseract and the vision model.** The page image and OCR text still show when the
  model API is down.
- **Vercel is read-only.** Anything that needs the API or MongoDB is local or hosted-backend.
- **`report.json` embeds dataset content.** The note in `web/README.md` still applies.
- **Quota.** A live demo needs a model with quota. The UI shows failure plainly.
- **Scope.** MongoDB is now in scope, so it must stay small: results and runs only.

## 12. Still open

1. **Where does MongoDB run?** An Atlas free-tier URI, or a local install? Needed for the one
   real check. Until then everything runs on the file fallback.
2. **Should MongoDB be required or optional?** Recommended: optional, falling back to files.
3. **What should the run and retry control do?** Kept small until the owner has checked with a
   friend.
4. **Review draft.** Send it when ready; sections 5.6 and 6.5 then become real.
