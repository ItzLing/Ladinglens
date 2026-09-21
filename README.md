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

This writes `output.json` (the submission, keyed by `email_id`), `classify_cache.json`
(adds each email's confidence, for sweeping the threshold offline) and `results.jsonl`
(one line per email, written as it completes).

### Iterating without spending a full run

```bash
curl -X POST "http://localhost:8000/run?limit=20"
```

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/run?limit=20"
```

Limited runs write to `output.sample.json` / `classify_cache.sample.json`, so they can't
overwrite a full baseline -- and so the scorer is never pointed at a partial submission.

### Resuming an interrupted run

`results.jsonl` is written per email, so a run that dies partway can be continued
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
cd data/server && PYTHONIOENCODING=utf-8 python score_cli.py ../../output.json
```

```powershell
$env:PYTHONIOENCODING='utf-8'; python data\server\score_cli.py output.json
```

`PYTHONIOENCODING` is needed because the scoreboard draws bar characters the Windows
console can't encode by default. `score_cli.py` locates `ground_truth.json` relative to
its own path, so it works from any directory.

## Review dashboard

A static page over the latest run -- filterable inbox, and a side-by-side SI vs BL diff
for each flagged field. See [`web/README.md`](web/README.md) for deployment.

```bash
python web/build_report.py          # regenerate web/report.json after every run
cd web && python -m http.server 8777
```

```powershell
python web\build_report.py
Set-Location web; python -m http.server 8777
```

Then open <http://localhost:8777>. Opening `index.html` off the filesystem will not
work -- the `fetch` of `report.json` has to be served over http.

## Plugging in the hackathon dataset

The bundle lives in [`data/`](data) and is gitignored -- it carries `ground_truth.json`
and the scorer, which are organizer-only material. Point the pipeline at it with
`INBOX_SOURCE` in `.env`:

- **Local files** (default): `INBOX_SOURCE=data/data_v2`
- **Docker dataset server**: `INBOX_SOURCE=http://localhost:8080`, started with
  `docker compose up --build` from `data/`. Only needed for the `POST /submit`
  endpoint; local scoring via `score_cli.py` needs no server.

## Project layout

```
app/
  schema.py            # EmailCategory, ShipmentFields, ComparisonResult
  llm_client.py         # OpenAI-compatible client for JSON-only structured calls
  main.py                # FastAPI app, POST /run
  pipeline/
    classify.py          # stage 1: email -> category (+ confidence)
    extract.py            # stage 2: SI/BL text -> ShipmentFields
    compare.py             # stage 3: SI vs BL -> mismatches (deterministic, no LLM)
    run.py                  # orchestrator, checkpointing, decides needs_review
web/
  build_report.py       # joins results.jsonl + inbox -> report.json
  index.html             # static review dashboard (no build step)
data/
  loader.py             # hackathon dataset loader (Inbox class)
  data_v2/               # inbox/, attachments/, sample_submission.json
  server/                 # dataset server + score_cli.py
```

## Current scope

- Attachment extraction handles `.txt` SI/BL documents only. `.pdf`, `.docx` and
  `.xlsx` are routed to `needs_review` (`unreadable`) rather than guessed at -- see
  `app/pipeline/run.py`. That covers 58 of 250 attachments, and is the largest single
  block of unclaimed score.
- `Dockerfile` is not built yet.
- See [`HANDOFF.md`](HANDOFF.md) for the running log of decisions and open questions.
