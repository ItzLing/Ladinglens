# HANDOFF.md

Running log of session-to-session progress and decisions. **Append-only** — do not edit or
delete prior entries. See `AGENT.md` for the full protocol.

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

## 2026-09-18 — Planning (pre-code)

**What changed:**
- No code yet. Defined the overall approach and repo conventions for the hackathon.

**Why:**
- Establishing a shared plan before implementation starts, so Claude Code sessions and
  team members don't duplicate or contradict each other's work.

**Decisions made:**
- Pipeline shape: **Classify → Extract → Compare → Ask for help (escalate)**, per the
  brief. Only `document-comparison` requests continue past classification.
- Seven fields to compare: shipper, consignee, notify party, port of loading, port of
  discharge, container count, gross weight (kg).
- Output format: one JSON object keyed by `email_id`, matching
  `sample_submission.json`, so we can use the self-evaluation endpoint while building.
- Adopted `AGENT.md` + `HANDOFF.md` as the sync mechanism between local Claude Code
  sessions and any web-based planning chats, since the two don't share context
  automatically.

**Open questions / next steps:**
- Start with the static bundle vs. Docker local server — decide based on whichever is
  faster to set up.
- Begin with one email + its two attachments end-to-end before scaling to the full inbox.
- Decide how field-label variation ("Port of Loading" vs "Load Port") will be handled —
  fixed synonym map vs. LLM-based field matching.
- Advanced stage (PDF/Word/scanned docs, messier inputs, human review) deferred until
  the basic pipeline is scoring reasonably on the self-evaluation endpoint.

**Synced through:** `(no commits yet)`

---

## 2026-09-18 — Claude Code — Ling (scaffold)

**What changed:**
- Scaffolded the full pipeline structure: `app/schema.py` (EmailCategory, ShipmentFields,
  ComparisonResult), `app/llm_client.py` (thin Anthropic wrapper for JSON-only calls),
  `app/pipeline/{classify,extract,compare,run}.py`, `app/main.py` (FastAPI, `POST /run`).
- Moved the hackathon bundle from `sdoc-hackathon-bundle/` into `data/` (`loader.py`,
  `inbox/`, `attachments/`, `sample_submission.json`, `README.md`) so it matches
  `loader.py`'s own expected layout (`Inbox("data")`) and the target project structure.
- Added `requirements.txt` (fastapi, uvicorn, pydantic, anthropic, python-dotenv),
  `.env` + `.env.example` (no API key filled in yet -- `.env` is already gitignored).
- Rewrote root `README.md` with setup instructions and dataset wiring instead of the
  one-line placeholder.
- Did **not** build `streamlit_app.py` or `Dockerfile` yet, per the brief (Dockerfile
  explicitly deferred until pipeline logic works; streamlit not yet requested).
- Verified every new/moved `.py` file with `python -m py_compile`, and smoke-tested
  `data/loader.py` loading all 520 emails and reading an SI attachment.

**Why:**
- Get a working skeleton in place so the next session can wire in the Anthropic API key
  and start iterating on prompt quality for classify/extract, without also deciding
  project layout.

**Decisions made:**
- Treated the repo root as the `ladinglens/` project root (no extra nested `ladinglens/`
  folder) since the repo is already named/scoped as Ladinglens and already had a root
  README -- avoids redundant nesting.
- `ComparisonResult` (schema.py) uses the field names specified in the brief
  (`mismatch_found`, `mismatches`, `needs_review`, `review_reason`) as the *internal*
  pipeline representation, separate from the hackathon's submission shape
  (`status`, `defect_fields`, `has_defect`). Added `ComparisonResult.to_submission()`
  to map one to the other -- `run.py` calls this when building `output.json`.
- `ShipmentFields.container_count` and `.gross_weight_kg` are typed `Optional[str]`
  (not int/float) since the raw values are compound strings (`"6 x 40'HC"`,
  `"131,058 KG"`) -- normalizing further is future work if scoring needs it.
- `compare.py` does exact-match comparison on whitespace-collapsed, upper-cased
  strings -- no fuzzy matching, so the diff stays auditable per the brief's
  "deterministic, no LLM call" requirement.
- Attachment matching in `run.py` uses `"_SI"` / `"_BL"` substring matching on
  attachment filenames (matches the dataset's naming convention). Non-`.txt`
  attachments (`.pdf`, `.docx`, `.xlsx` -- confirmed present in the dataset: 28 pdf,
  8 docx, 22 xlsx, 192 txt) are routed to `needs_review(unreadable)` rather than
  parsed, consistent with the prior entry's "advanced stage deferred" decision.
- Classification confidence below 0.6 (self-reported by the model) triggers
  `needs_review(unreadable)` before extraction is attempted -- arbitrary threshold,
  not yet tuned against the scoring endpoint.

**Open questions / next steps:**
- No `ANTHROPIC_API_KEY` yet -- pipeline is untested end-to-end against the LLM.
  Nothing in `app/` can actually run until a key is added to `.env`.
- Confidence threshold (0.6) and the model choice (`claude-sonnet-5` default,
  overridable via `ANTHROPIC_MODEL`) are both guesses -- revisit once real scoring
  feedback is available.
- `streamlit_app.py` (reviewable inbox + side-by-side SI/BL view) and `Dockerfile`
  are still not built, per the brief's explicit sequencing.
- PDF/DOCX/XLSX attachment parsing is still deferred; `requirements.txt` doesn't yet
  include `pypdf`/`python-docx`/`openpyxl` -- add them when that work starts.
- Decide whether `data/sample_submission.json`'s baseline (`GENERAL`/`OK` for every
  email) is worth diffing against once real output.json runs are possible, as a sanity
  check before wiring up the self-eval endpoint.

**Synced through:** `3592d1f` (no new commit made this session -- scaffold left uncommitted for review)

---

## 2026-09-20 — Claude Code (LLM provider swap)

**What changed:**
- Swapped `app/llm_client.py` from the Anthropic SDK to Google Gemini's `google-genai` SDK,
  keeping `call_json(system, user, max_tokens=1024) -> dict[str, Any]`'s exact signature and
  error-raising behavior, so `app/pipeline/classify.py` and `app/pipeline/extract.py` needed
  zero changes.
- Updated `requirements.txt` (`anthropic` -> `google-genai`), `.env.example`
  (`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` -> `GEMINI_API_KEY`/`GEMINI_MODEL`), and `README.md`
  (setup instructions + project-layout comment).

**Why:**
- No `ANTHROPIC_API_KEY` had ever been set up (see prior entry), and the Anthropic API isn't
  free, so the pipeline had never run end-to-end. Gemini's free tier (Google AI Studio, no
  billing) removes that blocker. Gemini was chosen over Groq/OpenRouter/Ollama alternatives
  because it also supports vision input, keeping the door open for the still-unbuilt
  OCR/scanned-document advanced-stage goal without committing to it now.

**Decisions made:**
- Used the current `google-genai` SDK (`from google import genai`), not the deprecated
  `google-generativeai` package.
- Defaulted to `GEMINI_MODEL=gemini-2.5-flash` (confirmed free-tier-eligible and multimodal)
  over the floating `gemini-flash-latest` alias, for reproducibility.
- Used provider-level JSON mode (`response_mime_type="application/json"` on
  `GenerateContentConfig`) without a `response_schema`, keeping `call_json`'s existing
  "ask for JSON via prompt, parse whatever text comes back" contract unchanged rather than
  moving to schema-validated output.
- Guarded `response.text` with `or ""` before `json.loads`, since it can be `None` on a
  blocked/empty response -- falls into the existing `ValueError` path instead of crashing.

**Open questions / next steps:**
- No retry/backoff for free-tier rate limits (roughly 30 RPM / ~1,500 RPD on
  `gemini-2.5-flash`) -- a full 520-email `/run` may approach these; still unimplemented.
- Pipeline still has never actually been run end-to-end -- next session should add a real
  `GEMINI_API_KEY` to `.env`, run `POST /run`, and ideally submit `output.json` to the
  hackathon's self-evaluation endpoint for a baseline score.
- Vision/OCR path is still unbuilt, deferred per original scope -- Gemini's multimodal support
  just keeps that option open for later.

**Synced through:** `8590ee3` (no new commit made this session -- Gemini swap left uncommitted for review)

---

## 2026-09-20 — Claude Code (run reliability + confidence cache)

**What changed:**
- `app/llm_client.py`: added exponential backoff with jitter (5 attempts) for retryable
  statuses (429/500/502/503/504), and a new `LLMUnavailableError` raised when the API can't
  be reached -- deliberately distinct from the `ValueError` raised for malformed model output.
- `app/pipeline/run.py`: the classify call is now inside error handling (previously it was
  unprotected, so a single 429 crashed the whole `/run` and lost every prior result).
  Extract failures now split by cause: `LLMUnavailableError` -> `processing_error`,
  genuine read/parse failures -> `unreadable`.
- `app/schema.py`: added `ReviewReason.PROCESSING_ERROR` and `ReviewReason.LOW_CONFIDENCE`,
  plus an internal `ComparisonResult.confidence` field (excluded from `to_submission()`).
- `app/main.py` + `run_pipeline()`: `/run` now also writes `classify_cache.json`, pairing each
  email's self-reported confidence with its computed verdict. `run_pipeline()` returns
  `(submission, classify_records)`.
- `.gitignore`: ignore the generated `output.json` and `classify_cache.json`.

**Why:**
- The team is about to take the first real baseline run against the self-eval endpoint and
  then tune `classify.py`'s prompt and the 0.6 threshold. Three things blocked that: a 429
  during classify killed the entire run; a 429 during extract was silently swallowed into
  `needs_review(unreadable)`, which looks like a legitimate document verdict and would have
  quietly corrupted the baseline score; and re-running all 520 emails for every threshold
  tweak would burn free-tier quota unnecessarily.

**Decisions made:**
- Retry lives in `llm_client.py`, not `run.py`, so the pipeline stays provider-agnostic --
  `run.py` catches `LLMUnavailableError` and never imports the SDK.
- Error handling in `run.py` narrowed from a blanket `except Exception` to
  `LLMUnavailableError` / `(ValueError, OSError)`. A missing `GEMINI_API_KEY` now crashes the
  run loudly instead of being recorded as 520 unreadable documents.
- A failed classification reports `category=GENERAL` (keeps the submission well-formed, and
  matches `sample_submission.json`'s own default) but always with
  `needs_review + processing_error`, rather than emitting a null category the scoring
  endpoint may not accept.
- Low confidence now reports `low_confidence` rather than reusing `unreadable`, so the
  threshold's effect is legible in the output while tuning. `status` is still `NEEDS_REVIEW`
  either way, so the submission's scored fields are unaffected.
- No proactive rate limiter added: backoff already self-paces, and a second throttling
  mechanism would duplicate it.

**Open questions / next steps:**
- Still no automated test suite in-repo. The routing and retry behavior was verified with
  throwaway scripts (16 checks, all passing) that were not committed -- worth promoting into
  a real `tests/` directory if the team wants them.
- `classify_cache.json` makes *raising* the threshold a free offline sweep, but only down to
  whatever threshold the cached run used: emails that were sent to review never got extract
  or compare results. Run the baseline at a low threshold to keep the whole range sweepable.
- Dataset files are absent from `data/` locally (gitignored), so `INBOX_SOURCE` now points at
  the Docker server. `submit()` is HTTP-only ([loader.py:66-69](data/loader.py)), and nothing
  in the app calls it yet -- submitting to the self-eval endpoint is still a manual step.

**Synced through:** `1bf67c4` (reliability work left uncommitted for review)

---

## 2026-09-20 — Claude Code (model correction + .env loading)

**What changed:**
- Default model moved from `gemini-2.5-flash` to **`gemini-3.6-flash`** in
  `app/llm_client.py`, `.env.example` and `README.md`. The prior two entries' choice of
  `gemini-2.5-flash` is superseded -- left in place there since this log is append-only.
- `app/main.py` now calls `load_dotenv(ROOT_DIR / ".env")`. `python-dotenv` was already in
  `requirements.txt` but nothing ever called it, so `.env` was never actually read and every
  run would have died on a missing `GEMINI_API_KEY`.

**Why:**
- The first live smoke test returned `404 NOT_FOUND: This model models/gemini-2.5-flash is no
  longer available to new users. Please update your code to use models/gemini-3.6-flash`.
  Confirmed against `client.models.list()` that `gemini-3.6-flash` is available on this key.

**Decisions made:**
- Took the model the API itself recommended (`gemini-3.6-flash`) rather than the newest
  listed (`gemini-3.7-flash`/`gemini-3.8-flash`), since free-tier eligibility for those is
  unverified and the recommendation is authoritative.
- Kept the model env-overridable, so trying a newer one is a `.env` edit, not a code change.

**Verification:**
- Live single-call smoke test passed both stages on `gemini-3.6-flash`: classify returned
  `(BL_COMPARISON, 0.98)`, and extract correctly resolved the label variants "Load Port" ->
  `port_of_loading` and "Discharge Port" -> `port_of_discharge`, which is the brief's
  field-label-variation requirement.
- The 404 also validated the new error handling: non-retryable status failed fast after 1
  attempt with a clear `LLMUnavailableError`, instead of burning all 5 retries.

**Open questions / next steps:**
- **The dataset is still missing and blocks any full run.** `data/` contains only
  `loader.py` -- no `inbox/`, `attachments/`, or `sample_submission.json` -- and there is no
  `docker-compose.yml` anywhere in the repo, so `INBOX_SOURCE=http://localhost:8080` has
  nothing to connect to. Re-extract the hackathon bundle ZIP before attempting a baseline.
- Consider making `CLASSIFICATION_CONFIDENCE_THRESHOLD` env-configurable if the team wants to
  sweep it without editing `app/pipeline/run.py`.

**Synced through:** `1bf67c4` (committed as `8b34d28`)

---

## 2026-09-20 — Claude Code (truncation bug: thinking tokens ate the output budget)

**What changed:**
- `app/llm_client.py`: default output budget raised from 1024 to 4096
  (`DEFAULT_MAX_TOKENS`, overridable via `GEMINI_MAX_TOKENS`), and added
  `_was_truncated()` so a reply that stops on `finish_reason=MAX_TOKENS` raises
  `LLMUnavailableError` instead of falling through to the JSON parse error.
- `.env.example`: documents `GEMINI_MAX_TOKENS` and why it needs headroom.

**Why:**
- A live 3-email run had `email_001` come back `needs_review(unreadable)` even though both
  its attachments are clean plain text that extract handles perfectly in isolation. Measuring
  the raw call three times showed why: `gemini-3.6-flash` spent **815-980 tokens thinking**,
  and thinking tokens are drawn from the *same* `max_output_tokens` budget as the reply. At
  1024, two of three runs finished on `MAX_TOKENS` with only ~40 output tokens, leaving
  truncated JSON -- which the pipeline then misread as an unreadable *document*.
- Left unfixed this would have silently poisoned the baseline: a large and randomly-varying
  share of the 520 emails would have scored as `unreadable` for no document-related reason.

**Decisions made:**
- Raised the budget rather than setting `ThinkingConfig(thinking_budget=0)`. Disabling
  thinking would also have worked and would cost fewer tokens, but the free-tier quota was
  exhausted before it could be verified on `gemini-3.6-flash`, and shipping an unverified
  config risks failing *every* call. Worth testing once quota resets.
- Truncation raises `LLMUnavailableError` (-> `processing_error`), not `ValueError`
  (-> `unreadable`), keeping the rule that only the document's own content earns a document
  verdict.

**Open questions / next steps:**
- **Free-tier quota was exhausted** by this session's diagnostics (429 RESOURCE_EXHAUSTED);
  it needs to reset before any further runs.
- Try `thinking_budget=0` when quota allows -- if it works it cuts roughly 800-980 tokens per
  call, which materially stretches the free-tier daily budget across a 520-email run.
- The earlier 3-email sample also showed classify confidences clustered high (0.95-0.98),
  so the 0.6 threshold may rarely bind. Worth confirming against the cache on a real run
  before spending effort tuning it.

**Synced through:** `1bf67c4` (committed as `8b34d28`)

---

## 2026-09-20 — Claude Code (provider-neutral client, Ollama by default)

**What changed:**
- `app/llm_client.py` rewritten against the **OpenAI SDK** instead of `google-genai`. Any
  OpenAI-compatible endpoint now works, selected by `LLM_BASE_URL` / `LLM_API_KEY` /
  `LLM_MODEL` / `LLM_MAX_TOKENS`. `call_json()`'s contract and `LLMUnavailableError` are
  unchanged, so `classify.py`, `extract.py` and `run.py` needed no edits.
- `requirements.txt`: `google-genai` -> `openai`.
- `.env.example` / `.env`: provider blocks for Ollama (active default), Groq and Gemini.
- `.gitignore`: added `data/data_v2/`, `data/server/`, `data/docker-compose.yml`.

**Why:**
- The Gemini free-tier quota was exhausted partway through a session, and a full run needs
  1,000+ calls (520 classify + two extracts per `BL_COMPARISON`), which can exceed a hosted
  free tier in a *single* run. Ollama runs locally with no quota at all, so prompt and
  threshold iteration stops being rationed.
- The gitignore addition is the urgent half: `data/data_v2/` holds `ground_truth.json`, and
  `data/README.md` marks the bundle as the ORGANIZERS package ("Do NOT hand it to
  participants"). It was untracked but unignored, so any `git add -A` would have committed
  the answer key.

**Decisions made:**
- OpenAI-compatible over a provider-specific SDK: Ollama, Groq, Cerebras, OpenRouter and
  Gemini all speak it, so provider choice became config. Develop free against a local model,
  point at a hosted one for a final higher-quality run.
- Env vars renamed `GEMINI_*` -> `LLM_*`, since they no longer describe one vendor.
- `LLM_MAX_TOKENS` now resolved inside `call_json()` rather than at import, removing a
  dependency on `load_dotenv()` running before the module is imported.
- Default `llama3.1:8b` -- small enough to run on modest hardware, and the task (5-way
  classification, 7 labeled fields from short clean text) is not especially demanding.

**Verification:**
- 8/8 pipeline routing checks and 7/7 client checks pass against stubs, covering: 429
  retried then succeeding, connection-refused (Ollama not running) reported as
  `LLMUnavailableError` rather than a document verdict, non-retryable 400 failing fast,
  `finish_reason=length` truncation, malformed JSON, null content, and the outgoing request
  carrying JSON mode plus the system prompt.
- Not yet verified against a live model: **Ollama is not installed on this machine.**

**Open questions / next steps:**
- Install Ollama and `ollama pull llama3.1:8b`, then re-run the 3-email sanity check before
  committing to all 520. An 8B model's JSON discipline is weaker than a hosted model's, so
  watch for `unreadable` verdicts caused by malformed output rather than real defects.
- `CLASSIFICATION_CONFIDENCE_THRESHOLD` is now `0.2` (lowered from `0.6`) so the baseline run
  keeps the whole threshold range sweepable from `classify_cache.json`.
- Local models may not honor `response_format={"type": "json_object"}` as reliably as the
  hosted ones; if that shows up, the fallback is to strip code fences before `json.loads`.

---

## 2026-09-20 — Claude Code (limit param for cheap iteration)

**What changed:**
- `POST /run?limit=N` processes only the first N emails. `run_pipeline(inbox, limit=None)`
  now slices `inbox.emails()` rather than iterating the inbox directly.
- Limited runs write `output.sample.json` / `classify_cache.sample.json`; only a full run
  writes `output.json` / `classify_cache.json`.
- `.gitignore` widened to `output*.json` / `classify_cache*.json`.

**Why:**
- Every prompt tweak previously cost a full 520-email run (1,000+ LLM calls: one classify per
  email plus two extracts per `BL_COMPARISON`). On a metered provider that is unaffordable to
  repeat, and it was the main thing making prompt iteration expensive on *any* provider.
- Separate filenames exist so a 20-email sanity run can't silently clobber a full baseline
  that cost real quota -- and so `score_cli.py` is never accidentally pointed at a partial
  submission, which would score 20 predictions against 520 ground-truth rows.

**Decisions made:**
- Chose the `limit` param over building dual-provider fallback (the other candidate). Cheap
  iteration helps on every provider; fallback only helps when quota runs out, and risks
  silently mixing model quality within one run, which would corrupt the baseline being
  measured. Revisit fallback only if quota actually bites mid-run.
- `limit` validated as `gt=0`, so `?limit=0` and negatives are rejected with HTTP 422 rather
  than silently producing an empty submission.

**Verification:**
- Slicing checked at `limit` = None / 1 / 5 / larger-than-inbox, and for order preservation;
  endpoint checked for sample-vs-full file routing and 422 on invalid input; the 8 routing
  and 7 client checks still pass.

**Open questions / next steps:**
- **The last full run produced 520 identical `processing_error` entries** -- Ollama was
  running but no model had been pulled (`404 model 'llama3.1:8b' not found`, non-retryable,
  so every email failed instantly). `output.json` is currently unusable. Either
  `ollama pull llama3.1:8b` or switch `.env` to the Groq block, then re-run.
- Frontend work is blocked on a real run. Note that `output.json` alone cannot drive the
  side-by-side SI/BL view the brief requires: `to_submission()` drops
  `ComparisonResult.mismatches`, which holds the actual per-field SI and BL values. A
  `report.json` carrying the full result (plus subject/sender) is needed first.
