# Ladinglens

AI-powered inbox triage and SI/BL discrepancy checker for shipping operations teams.

Classifies inbox emails into `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`,
or `SPAM`. For `BL_COMPARISON` emails, it extracts 7 shipment fields from the Shipping
Instruction (SI) and draft Bill of Lading (BL) attachments, compares them, and reports
mismatches -- escalating to a human (`needs_review`) whenever it can't complete a step
confidently.

Pipeline: **classify -> extract -> compare**, per [`app/pipeline/`](app/pipeline).

## Setup

Requires Python 3.14.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp .env.example .env          # then pick an LLM provider block (see below)
```

The pipeline talks to any **OpenAI-compatible** endpoint, so the provider is a `.env`
setting (`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`), not a code change. `.env.example`
carries ready-made blocks for each:

- **Ollama** (default) -- local, no key, no quota. Install from [ollama.com](https://ollama.com),
  then `ollama pull llama3.1:8b`. Best for iterating, since a full run costs nothing.
- **Groq** or **Gemini** -- hosted free tiers, stronger models, but daily request caps.

A full `/run` over the 520-email dataset makes one classify call per email plus two extract
calls per `BL_COMPARISON` email -- upwards of 1,000 calls, which can exceed a hosted free
tier in a single run. Expect it to take a while either way.

## Running the pipeline

```bash
uvicorn app.main:app --reload
```

Then, with the dataset in place (see below):

```bash
curl -X POST http://localhost:8000/run
```

This writes `output.json` at the repo root: one JSON object keyed by `email_id`,
matching the shape of `data/sample_submission.json`, ready for the hackathon's
self-evaluation endpoint.

## Plugging in the hackathon dataset

The dataset package (`loader.py`, `inbox/`, `attachments/`, `sample_submission.json`)
lives in [`data/`](data). It's already in place from the hackathon bundle -- if you're
starting from a fresh ZIP, drop its contents into `data/` the same way, without
overwriting `data/loader.py` unless the organizers shipped a newer version.

Two ways to point the pipeline at data, via `INBOX_SOURCE` in `.env`:

- **Local files** (default): `INBOX_SOURCE=data`
- **Hackathon Docker dataset server**: `INBOX_SOURCE=http://localhost:8080`

See [`data/README.md`](data/README.md) for the original hackathon bundle instructions
and scoring details.

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
    run.py                  # orchestrator, decides needs_review
data/
  loader.py             # hackathon dataset loader (Inbox class)
  inbox/                 # per-email JSON records
  attachments/            # SI/BL documents (.txt, .pdf, .docx, .xlsx)
```

`streamlit_app.py` (reviewable inbox UI) and `Dockerfile` are not built yet.

## Current scope

- Attachment extraction currently handles `.txt` SI/BL documents only. `.pdf`,
  `.docx`, and `.xlsx` attachments are routed to `needs_review` (`unreadable`) rather
  than guessed at -- see `app/pipeline/run.py`.
- See [`HANDOFF.md`](HANDOFF.md) for the running log of decisions and open questions.
