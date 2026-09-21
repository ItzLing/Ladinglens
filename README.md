# Ladinglens

AI-powered inbox triage and SI/BL discrepancy checker for shipping operations teams.

Classifies inbox emails into `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`,
or `SPAM`. For `BL_COMPARISON` emails, it extracts 7 shipment fields from the Shipping
Instruction (SI) and draft Bill of Lading (BL) attachments, compares them, and reports
mismatches -- escalating to a human (`needs_review`) whenever it can't complete a step
confidently.

Pipeline: **classify -> extract -> compare**, per [`app/pipeline/`](app/pipeline).

> Commands below are given for **bash** and **PowerShell**. PowerShell has no inline
> `VAR=value cmd` prefix and `curl` is an alias for `Invoke-WebRequest`, so the two
> forms genuinely differ -- use the one for your shell.

## Setup

Requires Python 3.14.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then pick an LLM provider block
```

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then pick an LLM provider block
```

The pipeline talks to any **OpenAI-compatible** endpoint, so the provider is a `.env`
setting (`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`), not a code change.
`.env.example` carries ready-made blocks for Gemini, Ollama and Groq.

Two things that will bite you:

- **`LLM_MAX_TOKENS` must match the model.** Reasoning models (`gemini-3.6-flash`, the
  `gpt-oss` family) spend ~800-1000 *thinking* tokens out of that same budget. Too low
  and replies truncate mid-JSON, which gets logged as `processing_error` and looks like
  a document problem. Non-reasoning models (`gemini-3.1-flash-lite`) are fine at 2048.
- **`--reload` watches `.py`, not `.env`.** After changing a provider, restart uvicorn
  or touch a `.py` file, or the running server keeps the old settings.

A full run over the 520-email dataset is ~724 requests (one classify per email plus two
extracts per `BL_COMPARISON`). Gemini's free tier allows 500 requests/day **per model**,
so a full run does not fit on one model in one day. Ollama is the only uncapped option.

## Running the pipeline

Start the server:

```bash
uvicorn app.main:app --reload
```

Then trigger a run:

```bash
curl -X POST http://localhost:8000/run
```

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/run"
```

Everything a run writes goes into [`results/`](results/README.md):
`output.json` (the submission, keyed by `email_id`), `classify_cache.json` (adds each
email's confidence, for sweeping the threshold offline) and `results.jsonl` (one line
per email, written as it completes). **If every record says `processing_error`, nothing was
checked** -- the model API failed, usually on quota. See `results/README.md`.

### Iterating without spending a full run

```bash
curl -X POST "http://localhost:8000/run?limit=20"
```

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/run?limit=20"
```

Limited runs write `output.sample.json` / `classify_cache.sample.json` / `results.sample.jsonl`
into `results/`, so they can't overwrite a full baseline -- and so the scorer is never pointed at a partial submission.

### Resuming an interrupted run

`results/results.jsonl` is written per email, so a run that dies partway can be continued
instead of restarted. Resuming also **retries `processing_error` emails**, since those
are API failures rather than real verdicts:

```bash
curl -X POST "http://localhost:8000/run?resume=true"
```

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/run?resume=true"
```

Don't resume across a model change -- you'd end up with a dataset judged half by one
model and half by another. `resume` is off by default for that reason.

## Polling the inbox on a schedule

`scripts/poll.py` calls `POST /run?resume=true` on an interval. Because resume skips
emails already in `results.jsonl`, each tick only processes what is new and retries
whatever previously failed on the API -- a tick that finds nothing new costs no calls.

```bash
python scripts/poll.py                 # loop, every 5 minutes
python scripts/poll.py --interval 120  # every 2 minutes
python scripts/poll.py --once          # one tick, for Task Scheduler / cron
```

```powershell
python scripts\poll.py
python scripts\poll.py --interval 120
python scripts\poll.py --once
```

A full run takes far longer than a polling interval, so `POST /run` refuses a second
concurrent run with **HTTP 409** rather than letting two runs append to the same
checkpoint and race on `output.json`. The poller treats 409 as "skip this tick".
`GET /status` reports whether a run is in progress.

To survive reboots, register the `--once` form with Windows Task Scheduler:

```powershell
$py = (Get-Command python).Source
$action  = New-ScheduledTaskAction -Execute $py -Argument "scripts\poll.py --once" -WorkingDirectory $PWD
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "Ladinglens poll" -Action $action -Trigger $trigger
```

Note the dataset is a fixed set of 520 files, so a poller finds no new work after the
first pass. For this to do anything real, `INBOX_SOURCE` needs a source that changes --
the Docker dataset server, or a mailbox. `loader.py`'s `Inbox` is the seam: anything
exposing `emails()` and `read_text()` drops in without pipeline changes.

## Scoring a run

```bash
cd data/server && PYTHONIOENCODING=utf-8 python score_cli.py ../../results/output.json
```

```powershell
$env:PYTHONIOENCODING='utf-8'; python data\server\score_cli.py results\output.json
```

`PYTHONIOENCODING` is needed because the scoreboard draws bar characters the Windows
console can't encode by default. `score_cli.py` locates `ground_truth.json` relative to
its own path, so it works from any directory.

## The web app

Start the server and open <http://localhost:8000>:

```bash
uvicorn app.main:app
```

It is plain JavaScript and CSS with no build step, served by the same FastAPI app. The icon
rail on the left has five tabs:

- **Home**: what the system does, and how many emails need attention.
- **Parsing**: the email list (**Need attention** or **All emails**) with label chips to
  filter by (SI request, BL comparison, invoice query, general, spam). Pick an email to see its
  label, confidence score, a one-line summary, and for a document check all seven fields with
  the SI beside the BL and what differs highlighted. It only reads; nothing here changes a
  verdict.
- **Review** and **Report**: still being designed.
- **Database**: a read-only view of what is stored (MongoDB collections, or the files).

The small control at the top right shows whether a run is in progress, and can retry the
emails that failed on the model API, or run the pipeline. Keys: `j` and `k` move through the
list, `/` searches, `g` then `h`, `p` or `d` jumps to Home, Parsing or Database.

The same page also works **read-only with no server**, from `web/report.json`; that is what
the Vercel demo is. See [`web/README.md`](web/README.md), and [`web/DESIGN.md`](web/DESIGN.md)
for the design.

```bash
python web/build_report.py          # rebuild the demo data from the latest run
python web/build_report.py --sample # ...or from a limited run (?limit=N)
```

```powershell
python web\build_report.py
```

### MongoDB (optional)

Results always go to `results/results.jsonl`, which is what resume reads, so a database
being down never loses a run. Set these in `.env` and every record is also copied into
MongoDB, and the web app reads from there:

```
MONGODB_URI=mongodb+srv://user:password@cluster.example.mongodb.net
MONGODB_DB=ladinglens
```

Collections: `results` (one document per email and scope, `full` or `sample`) and `runs` (one
per run). The Database tab shows both, read-only, and never shows the credentials. Without
`MONGODB_URI` the app simply uses the files. Note: the MongoDB support is tested against an
in-memory fake, and has not yet been run against a real server.

## Exporting to Excel

The operations team works in spreadsheets, so a run can be handed over as one:

```bash
python scripts/export_excel.py              # -> results/ladinglens.xlsx
python scripts/export_excel.py --sample     # the ?limit= run instead
```

```powershell
python scripts\export_excel.py
python scripts\export_excel.py --sample
```

Two sheets, both with frozen headers and autofilters: **Inbox** is one row per email
(sender, subject, classification, result, why escalated), and **Mismatches** is one row
per flagged field with the SI and BL values side by side. Mismatch rows are tinted red
and escalations amber, so the sheet is scanned rather than read.

It reads through the same `app.api.report()` the dashboard uses, so the two can never
disagree, and it makes **no API calls** -- every value was already decided by the run.

## Simulating an inbox

The dataset is a fixed set of files, so a poller finds nothing new after its first pass.
To watch the pipeline react to arrivals, drip emails into a staging folder:

```bash
python scripts/feed_inbox.py --reset               # empty the staging folder
python scripts/feed_inbox.py --batch 3 --every 60  # 3 every 60s until done
```

Point the pipeline at it and run the poller alongside:

```bash
# .env
INBOX_SOURCE=data/live
```

Nothing is faked inside the app: the feeder copies real records into `data/live/`, and
the ordinary `Inbox` loader discovers them the way it would a real mail drop.
Attachments are copied **before** the email JSON, so the pipeline never sees an email
whose documents have not landed and bank `missing_attachment` as a verdict.

Point `INBOX_SOURCE` back at the full dataset before scoring -- `score_cli.py` grades
against all 520 emails, so a partial staging folder reads as a catastrophic regression.

## Deploying

`Dockerfile` builds a container that serves the API and the web UI. It installs
`tesseract-ocr` and `poppler-utils`, because `pytesseract` is only a wrapper and OCR
would otherwise fail in the container while working locally.

```bash
docker build -t ladinglens .
docker run --rm -p 8000:8000 --env-file .env ladinglens
```

The dataset is deliberately **not** in the image -- `.dockerignore` excludes `data/*`
except `loader.py`, so organizer material can never reach a public container. That means
`POST /run` cannot work there. `POST /process` is the deployed path: it takes the email
and both documents in the request body and needs nothing on disk.

On Render: New > Web Service, connect the repo, runtime **Docker**, health check `/`.
Set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` and `LLM_MAX_TOKENS` in their dashboard,
and leave `INBOX_SOURCE` unset. Free instances sleep after ~15 minutes idle and take
~50s to wake, so warm the URL before demoing.

## Plugging in the hackathon dataset

The bundle lives in [`data/`](data) and is gitignored -- it carries `ground_truth.json`
and the scorer, which are organizer-only material. Point the pipeline at it with
`INBOX_SOURCE` in `.env`:

- **Local files** (default): `INBOX_SOURCE=data`. The folder must hold `inbox/` (one
  JSON per email) and `attachments/` -- those two names are fixed by `data/loader.py`.
- **Docker dataset server**: `INBOX_SOURCE=http://localhost:8080`, started with
  `docker compose up --build` from `data/`. Only needed for the `POST /submit`
  endpoint; local scoring via `score_cli.py` needs no server.

## Project layout

```
app/
  schema.py            # EmailCategory, ShipmentFields, ComparisonResult
  llm_client.py         # OpenAI-compatible client for JSON-only structured calls
  main.py                # FastAPI app: POST /run, /api, and the web UI
  api.py                 # the read-only /api routes, and retrying one email
  store.py               # result store: JSONL file always, MongoDB copy when configured
  paths.py               # where inputs and results live
  run_state.py           # is a run in progress
  pipeline/
    classify.py          # stage 1: email -> category, confidence, one-line summary
    read_document.py      # attachment (txt/pdf/docx/xlsx/image) -> text, or page images
    ocr.py                 # Tesseract OCR, per-word confidence, keyword label lookup
    validate.py            # format / range / placeholder checks on extracted values
    extract.py            # stage 2: the fallback ladder -> ShipmentFields + field issues
    compare.py             # stage 3: SI vs BL -> mismatches (deterministic, no LLM)
    run.py                  # orchestrator, checkpointing, decides needs_review
scripts/
  poll.py               # polls /run?resume=true on an interval
  recompare.py           # re-applies stage 3 offline, without spending API quota
  export_excel.py        # a finished run -> .xlsx for the operations team
  feed_inbox.py          # drips emails into data/live/ to simulate arrivals
results/                 # everything a run writes (only its README is tracked)
tests/
  test_*.py               # Python tests, offline (OCR, LLM and MongoDB mocked)
  js/*.test.js            # JavaScript tests for the pure UI modules (node:test)
web/
  index.html             # the app shell
  css/, js/              # plain CSS and ES modules, no build step
  build_report.py       # builds report.json, the data behind the read-only demo
  DESIGN.md              # the UI plan and design
data/
  loader.py             # hackathon dataset loader (Inbox class)
  inbox/                 # one JSON per email
  attachments/           # the SI / BL documents
  sample_submission.json
  server/                 # dataset server + score_cli.py
```

## Reading attachments

Each SI/BL attachment goes through a fallback ladder in
[`app/pipeline/extract.py`](app/pipeline/extract.py). The cheapest, most trustworthy step
runs first, and the API is only used where it has to be:

1. **Read the text** ([`read_document.py`](app/pipeline/read_document.py)): `.txt`, `.docx`
   and `.xlsx` are parsed locally, and a `.pdf` uses its text layer. That text goes to the
   LLM, which maps it onto the 7 fields.
2. **No usable text** (a scanned PDF, or a `.jpg`/`.png`/`.tif` file): OCR with
   [Tesseract](https://github.com/tesseract-ocr/tesseract), which gives a confidence for every
   word. A field's confidence is the **minimum** over its words, so one misread character
   drags the whole field down.
3. **Found by keyword and confident:** accepted, with no LLM call.
4. **Low OCR confidence:** the characters were misread, so re-parsing that text cannot fix
   it. The field goes straight to a **vision LLM** looking at the page image. Only the fields
   that need it are sent, in one call per document.
5. **Confident, but the label is not one we know:** the text is fine and only the wording is
   new, so an LLM parses the clean OCR text.
6. **Validation** on every value from OCR or an LLM (`validate.py`): weight must be a number
   in kilograms within range, container count a whole number in range, names and ports
   real text without stray symbols or placeholders such as `TBA` and `N/A`. For a text
   document the raw line is checked too, so an LLM that tidies `____MT` into `MT` is still
   caught. A value that fails is treated like low confidence.
7. **Still unresolved:** the email is `needs_review` (`missing_value`) and each field is
   recorded as a `field_issues` entry with its reason and evidence, in `results.jsonl` and
   `web/report.json`. Nothing is guessed or dropped. `output.json` keeps the hackathon shape.

A file that cannot be read at all -- corrupt, empty, or an unsupported type -- is
`needs_review` (`unreadable`). If an API call fails, the email is `processing_error`
instead, since that says nothing about the document.

### Installing Tesseract

`pytesseract` is only the Python wrapper. It needs the Tesseract program itself:

```powershell
winget install --id UB-Mannheim.TesseractOCR
```

The default Windows install folder is found automatically; otherwise set `TESSERACT_CMD`
in `.env`. **Without Tesseract nothing breaks:** scans skip steps 2-3 and 5, and every
field goes to the vision LLM. It works, but costs one vision call per scanned document
where Tesseract would usually cost none.

Scans and vision need a **vision-capable model**. Gemini is; a local `llama3.1` is not. Set
`LLM_VISION_MODEL` in `.env` to use a different model for the vision step than for text.
`OCR_MIN_CONFIDENCE` (default 80) is the confidence below which a field goes to vision.

### Tests

Everything is tested offline: OCR, the model calls and MongoDB are all mocked, so no API
quota, Tesseract or database is needed.

```bash
pip install -r requirements-dev.txt     # once: adds mongomock and httpx
python -m unittest discover -s tests    # Python
node --test "tests/js/*.test.js"        # JavaScript (Node 22 or newer, no packages)
```

## Current scope

- `Dockerfile` is not built yet.
- The **Review** and **Report** tabs are waiting on their designs. Until Review exists there
  is no way to confirm or correct a case in the UI.
- MongoDB support has only run against an in-memory fake, not a real server.
- The OCR confidence threshold (`OCR_MIN_CONFIDENCE`) has not been calibrated against degraded
  scans; the dataset's own scans are clean.
- The one-line email summary comes from the same model call as the label. Adding it left the
  category unchanged on all 19 emails compared, but that sample is small.
- See [`HANDOFF.md`](HANDOFF.md) for the running log of decisions and open questions.
