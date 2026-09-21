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

---

## 2026-09-21 — Claude Code (first real baseline: 0.4037)

**What changed:**
- `llm_client.py`: `timeout=60` (env `LLM_TIMEOUT`) and `max_retries=0` on the client.
- `run.py`: thread-pool concurrency (`LLM_CONCURRENCY`, default 8) and JSONL checkpointing;
  each result appends to `results.jsonl` as it completes. `POST /run?resume=true` continues.
- `run.py`: checkpoint splits into succeeded/failed. Failures are retried on resume, but a
  retry that *also* fails can't downgrade what the earlier attempt knew.
- `.gitignore`: `results*.jsonl`.

**FIRST REAL SCORE: 0.4037** (`stage1 macro-F1 0.707` · `stage3 defect-F1 0.432` ·
`end-to-end 0.196`; weights s1=0.3, s3=0.2, **e2e=0.5**).

**Why / what was learned:**
- **The SDK's default 600s timeout was the stall.** An 80-minute run produced nothing: one
  hung call blocks for 10 minutes, and our 5 retries stacked on the SDK's own retries.
- **Free-tier token caps, not request caps, are the binding constraint.** Groq
  `gpt-oss-120b` allows **200k tokens/day**; a full run needs ~1M. `gpt-oss-20b` and
  `qwen/qwen3.8-27b` allow 8k tokens/min and 1000 requests/day -- a run needs ~936 calls.
- **Reasoning models are the reason.** `gpt-oss-120b` and `gemini-3.6-flash` spend ~800-1000
  *thinking* tokens per call. `gemini-3.1-flash-lite` spends ~10 completion tokens and still
  classifies correctly, extracts 7/7 fields, and resolves "Load Port" -> `port_of_loading`.
  Picking a non-reasoning model is worth more than any prompt tuning here.
- **`temperature` was unset**, so extraction was non-deterministic and invented mismatches
  (observed once in five runs on `email_001`). Now pinned to 0.
- **uvicorn `--reload` watches `.py`, not `.env`.** A provider switch looked like a total
  failure because the server held the dead config in memory. Touch a `.py` file after
  editing `.env`.

**Decisions made:**
- Threads over asyncio for concurrency: the work is I/O-bound and `process_email` stays
  synchronous, so no rewrite of the pipeline stages was needed.
- `resume` defaults to **off**, so a prompt change never silently reuses stale verdicts.

**Open questions / next steps:**
- **Both providers' quotas are exhausted as of 2026-09-21 01:15.** Blocked until they reset,
  or until Ollama has a model pulled (`ollama pull llama3.1:8b`) -- local is the only
  uncapped path and the only way to iterate freely.
- **157 of 520 emails are `processing_error`** in the current `output.json` -- pure
  infrastructure loss. They drag `BL_COMPARISON` recall to **0.46** (precision is a perfect
  1.00), and an email not routed to comparison can never have its defect caught. Retrying
  those is the single biggest available win; `?resume=true` now does exactly that.
- After that, the real accuracy target is **defect recall 0.326** (precision 0.833) -- we
  miss two thirds of genuine discrepancies. Investigate against `ground_truth.json`.
- A retry attempt at 00:28 failed on quota and *regressed* output 102 -> 69 BL_COMPARISON.
  Restored from `results.jsonl.bak`; the `_better_failure` guard now prevents a repeat.

---

## 2026-09-21 — Claude Code + team (0.4037 -> 0.7465)

**Score progression this session:**

| run | model / change | stage1 | defect F1 | e2e | FINAL |
|---|---|---|---|---|---|
| baseline | `gemini-3.1-flash-lite`, 157 API failures | 0.707 | 0.432 | 0.196 | **0.4037** |
| +tokens | `gemini-3.6-flash`, `LLM_MAX_TOKENS=16384` | 0.872 | 0.622 | 0.478 | **0.6442** |
| +prompts | classify prompt sharpened | 0.865 | 0.761 | 0.674 | **0.7465** |

End-to-end (weighted 0.5, the headline metric) went 9/46 -> 22/46 -> **31/46** defect
emails caught.

**What changed:**
- Switched to `gemini-3.6-flash` with `LLM_MAX_TOKENS=16384`. This was the single
  biggest jump (+0.24). The prior budget was truncating replies mid-JSON, which the
  pipeline logged as `processing_error` -- a *document* verdict for an *infrastructure*
  problem. `processing_error` went 157 -> 0.
- Classification prompt sharpened: `SI_REQUEST` precision 0.64 -> 0.93, which lifted
  `BL_COMPARISON` recall 0.46 -> 0.68. The two categories were being confused with each
  other, and a misrouted email can never have its defect caught.
- Built `web/` -- a static review dashboard (no build step) with a filterable inbox and
  the side-by-side SI vs BL field diff the brief asks for. `web/build_report.py` joins
  `results.jsonl` with the inbox to produce `report.json`, since `output.json` alone
  drops `ComparisonResult.mismatches` and so cannot drive that view.
- `README.md` rewritten: bash **and** PowerShell for every command, and the stale bits
  fixed (Ollama was no longer the default; `INBOX_SOURCE` is `data/data_v2`).
- `.gitignore` widened to `.env.*` -- it previously matched only the exact name `.env`,
  so a `.env.bak` sat unignored with a live API key in it.

**Decisions made:**
- Dashboard is a **static page, not Next.js**: no build step means nothing can fail
  during a judging demo, and Vercel still allows `api/*.py` functions alongside it if
  live processing is wanted later. Deploy with Root Directory = `web`.
- The dashboard banner explains whichever escalation reason dominates. With 64 emails
  escalated and no explanation, a reader would assume breakage; it now states plainly
  that 30 carry PDF/Word/Excel attachments this version does not parse, and that
  escalating beats guessing -- which is the brief's own requirement.

**Open questions / next steps:**
- **Document parsing is the biggest remaining win.** 58 of 250 attachments are non-txt
  (28 pdf, 22 xlsx, 8 docx) and **54 of 150 comparison requests never reach comparison**.
  The PDFs carry a text layer (`/Font` present, ~3 KB each) so **no OCR is needed** --
  `pypdf` + `python-docx` and a dispatcher into the existing `extract_fields()` is
  enough. `openpyxl` is already installed.
- `GENERAL` precision is now **0.42** (recall 0.83) -- it has taken over as the
  over-predicting category from `SI_REQUEST`. `BL_COMPARISON` recall is still 0.68.
- Escalation precision 0.281 (64 flagged vs 20 gold) -- mostly the unreadable
  attachments above; it should fall out once those are parsed.
- Whiteboard items deliberately **not** pursued: Airflow/Spark (wrong-sized for an
  I/O-bound job over 520 docs), Mongo (JSONL checkpointing already covers this scale),
  chatbot. None move the rubric. Per-email checkpointing already makes the work
  resumable and splittable, which is the honest answer to a scale question.
- `HANDOFF.md` is now 10 entries; `AGENT.md` asks for archiving past ~5. Worth moving
  the pre-2026-09-21 entries into `HANDOFF-archive.md` as a separate commit.
- `results.jsonl.bak` / `results.jsonl.afterretry` are tracked (commit `8ce18bb`) but
  are scratch run data -- `git rm --cached` when convenient.

**Synced through:** `938aa57`


---

## 2026-09-21 — Claude Code — Ling (PDF / Word / Excel parsing + OCR)

**What changed:**
- New `app/pipeline/read_document.py`: turns any attachment into plain text before
  `extract_fields()` sees it. `.txt` as is; `.docx` (paragraphs + tables) and `.xlsx` (every
  non-empty row) parsed locally; `.pdf` via its text layer; a PDF with **no** text layer is a
  scan, so its page image is sent to a vision model to transcribe (OCR).
- `run.py`: removed the ".txt only" gate that sent every other format to
  `needs_review(unreadable)`; attachments now go through `read_document`. Corrupt / empty /
  unsupported files raise `DocumentUnreadableError` (a `ValueError`) -> still `unreadable`; an
  API failure during OCR raises `LLMUnavailableError` -> `processing_error`, as before.
- `llm_client.py`: `_generate` now takes messages + an optional JSON mode; added
  `call_vision_text()` (image + prompt -> plain text) and `vision_model_name()`. `call_json`
  behaves exactly as before. New optional env var `LLM_VISION_MODEL` (defaults to `LLM_MODEL`).
- `compare.py`: normalization now also ignores address separators (`,` `;` `|`), thousands
  commas, and the `KG`/`KGS` unit on `gross_weight_kg`. See Decisions.
- `web/build_report.py` reads documents via `read_document(..., ocr=False)` so the dashboard
  can show PDF/Word/Excel text and cached scans; it now calls `load_dotenv` (see Decisions).
  `web/index.html`: the "unreadable" banner no longer claims PDF/Word/Excel are unsupported.
- `requirements.txt`: `pypdf`, `python-docx`, `openpyxl`, `pillow`. `.gitignore`: `ocr_cache/`.
  `.env.example` + `README.md` document the new behavior.

**Why:**
- 58 of 250 attachments were non-txt and 54 of 150 comparison requests never reached
  comparison (previous entry) -- the largest block of unclaimed score. The brief lists
  "scanned documents" as a requirement and explicitly allows OCR, a vision LLM, or both.

**What the data actually contains (checked, not assumed):**
- 28 PDFs: 20 have a clean text layer (no OCR needed), **6 are image-only scans**
  (`email_512`-`514`, SI + BL each, clean rendered text), **2 are truncated ~770-byte files**
  (`email_511_BL`, `email_515_BL`; their emails say "the BL file will not open").
- 8 docx (bilingual EN/CN labels in a table) and 22 xlsx (label | value rows, weight as a
  bare number). All parse.

**Decisions made:**
- **Vision LLM for OCR, not Tesseract/EasyOCR.** No new system binary or heavy model wheel
  (unclear support on Python 3.14), it reuses the existing provider, and the transcript then
  goes through the same `extract_fields()` path as every other format. Cost: OCR needs a
  vision-capable model -- Gemini is, a local `llama3.1` is not (hence `LLM_VISION_MODEL`).
- **Transcribe to text, then extract** (two calls) rather than image -> fields (one call): the
  transcript is inspectable and cached, and one extraction path is easier to reason about.
- **OCR transcripts cached in `ocr_cache/`**, keyed on the file bytes + prompt + vision model,
  so a rerun doesn't re-spend quota and a model/prompt change can't serve stale text.
- **`compare.py` normalization widened -- this was a real bug, not polish.** Once xlsx and
  docx were readable, `email_055` (xlsx SI vs docx BL) reported 4 mismatches that were all
  formatting: `243588` vs `243,588`, and address parts joined by `;`/`|` in the xlsx but `,`
  in the docx. It only removes formatting; words and digits are never altered, and real
  differences (weight digit, name, port, container) are still caught. Also applies to `.txt`,
  where it can only remove separator-only false positives.
- Any exception from pypdf/python-docx/openpyxl on a damaged file is caught **at the parser
  boundary only** and re-raised as `DocumentUnreadableError`; API errors are never swallowed.
- Scan pages capped at `MAX_OCR_PAGES = 5`; SI/BL documents are one page.

**Verification:**
- All 250 attachments run through `read_document(ocr=False)`: 242 parse; 2 corrupt PDFs ->
  `unreadable`; 6 scans wait for OCR. No API used.
- Live OCR on all 6 scans (Gemini); `512_SI` checked field by field against the image.
- Live end-to-end: `email_059` (text PDF) and `email_005` (xlsx vs xlsx) -> `OK`.
- With the LLM stubbed: 511/515 -> `unreadable`; 512-514 -> read from cache with the API
  pointed at a dead port (proves cache + no-API path); 055 -> `OK`.
- **Not verified:** any score. `data/` here has no `ground_truth.json`, and free-tier quota
  ran out mid-session, so there is no full run and no self-evaluation number for this change.

**Open questions / next steps:**
- **Quota:** the API returned `429 ... limit: 20, model: gemini-3.6-flash` (free tier, per day)
  -- far below the 500/day noted in `.env.example`/`README.md`. Testing OCR alone used ~6.
  A full run needs ~724 calls, so expect to need another model, a paid key, or Ollama.
- **Run the full pipeline and score it** when quota allows -- this change should move the 54
  stuck comparison requests, but that is unmeasured. Use `?resume=true` only if the model
  is unchanged (see previous entries).
- **OCR misreads can create false mismatches.** The prompt asks for `[illegible]` where the
  model can't read text, but nothing yet turns an `[illegible]` value into
  `needs_review(missing_value)`. Worth doing if scans get messier than the clean ones here.
- `web/build_report.py` still hard-codes `INBOX_SOURCE = "data/data_v2"`; this checkout only
  has `data/inbox` + `data/attachments`, so it can't be run here as-is.
- `HANDOFF.md` is ~11 entries; archive the old ones into `HANDOFF-archive.md` as its own commit.

**Synced through:** `aa38e80` (committed as `8983325`, `6d20a09`, `ed6c5ce`, `aa38e80`, one per task)


---

## 2026-09-21 — Claude Code — Ling (OCR fallback ladder in extract.py)

**What changed:**
- `app/pipeline/extract.py`: `extract_document(inbox, path, label)` now runs the 7-step ladder
  from the refined design (ladder is documented at the top of the file). `extract_fields()` and
  its prompt are unchanged -- they are step 5's "LLM parses clean text".
- New `app/pipeline/ocr.py`: `pytesseract` per-word OCR, `field_confidence` = **minimum** over a
  field's words, page quality = mean, keyword label lookup (`keyword_hits`), and `label_line`
  / `text_lines` for reading the raw "Label: value" line of any text.
- New `app/pipeline/validate.py`: weight (number, KG unit, 100-1,000,000), container count
  (leading integer, 1-200), names/ports (has letters, no stray symbols, not a placeholder such
  as `TBA`/`N/A`). Limits were set from the dataset (20,065-360,415 kg; 1-16 containers).
- `read_document.py` rewritten around `load_document()` -> `LoadedDocument(text | images)`.
  Adds `.jpg/.jpeg/.png/.tif/.tiff` (multi-page TIFF supported). `read_document(inbox, path)`
  remains for the dashboard and now uses local OCR; its `ocr=` argument is gone.
- `llm_client.py`: `call_vision_text` replaced by `call_vision_json`.
- `schema.py`: `FieldIssue` (document, file, field, reason, detail, source, value, evidence),
  `FieldIssueReason` (not_found / invalid_value / unreadable), `ExtractionResult`, and
  `ComparisonResult.field_issues`.
- `run.py`: uses `extract_document`; any unresolved field -> `needs_review` /
  `missing_value` with `field_issues` attached, never compared. `_record` writes them to
  `results.jsonl`; `web/build_report.py` passes them into `report.json`.
- New `tests/test_extract_ladder.py` (33 stdlib `unittest` tests, all offline).
  `python -m unittest discover -s tests`. Added to `AGENT.md`.
- `requirements.txt` + `pytesseract`; `.env.example` + `OCR_MIN_CONFIDENCE`, `TESSERACT_CMD`;
  README rewritten for the ladder; `ocr_cache/` and its `.gitignore` entry removed.

**Why:**
- The design was refined after the last entry: OCR should be a Python library with per-field
  confidence, vision only per low-confidence field, and every field validated, with unresolved
  fields reported with evidence rather than guessed. The previous entry's OCR (a vision LLM
  transcribing the whole page, cached) did not match that, so it is **superseded** (that entry
  is left as written; the log is append-only).

**Design vs code, before this change (gap analysis):**
- Already correct: step 1 (text extraction first, PDF/Word/Excel/txt), step 5's LLM text parse,
  a `needs_review`/`missing_value` route.
- Missing: Python OCR, image formats, per-field confidence, per-field vision, validation,
  per-field reason + evidence (run.py only had "any field None").

**Decisions made:**
- **Text documents stay LLM-first.** The keyword pass exists only inside the OCR path. Measured
  on the corpus: keywords alone find all 7 fields in just 124 of 242 documents (PDFs put values on
  the next line; many label variants), so the LLM is still needed. Making keyword-first the
  default for text would save calls but risks the current score -- left as an open decision.
- **One vision call per document**, listing only the fields that need it, not one call per
  field. Same routing, far fewer calls.
- **"OCR confidence is fine" for a field the keyword pass did not find** is judged by the
  page's mean word confidence >= `OCR_MIN_CONFIDENCE`. Below it, the field goes to vision.
- **No Tesseract -> every field goes to vision** rather than failing. Scans still work
  (verified live), at one vision call per document.
- **Validation also checks the raw source line for text documents.** Live, the model turned
  `Port of Loading: ____MT` into `MT`, which is a valid-looking string; only the raw line
  exposes it. On the corpus this rejects 5 of 1,564 raw values, all in `email_516`-`518`, the
  emails whose own body says fields were left blank -- zero false positives.
- Unresolved fields all map to `review_reason=missing_value` in the submission (the hackathon's
  enum has no finer reason); the finer reason lives in `field_issues`, which stays out of
  `output.json` so it keeps the `sample_submission.json` shape.
- A text document has no page image, so a validation failure there ends the ladder in
  `needs_review` (no vision fallback).
- Kept the OCR-cache removal simple: no cache. Vision replies are not cached.

**Verification:**
- 33 tests pass. Mutation-checked: swapping min for mean, disabling validation, and a
  threshold of 0 each make specific tests fail.
- Live (Gemini `gemini-3.1-flash-lite`; `gemini-3.6-flash` is capped at 20 requests/day on this
  key): both `email_512` scans -> all 7 fields correct via the vision branch; `email_516`
  (`N/A` weight), `517` (`____MT`, `TBA`), `518` (`N/A`, `____MT`) -> flagged with the field's own
  line as evidence; `email_059` (text PDF) -> 7/7, no false alarm.
- **Not verified:** any real Tesseract output. **Tesseract is not installed on this machine**
  (`winget install --id UB-Mannheim.TesseractOCR` needs an install, which I did not do without
  asking), so steps 2-3 and 5 only run against mocks. `OCR_MIN_CONFIDENCE=80` is a placeholder.
  No score either -- there is no `ground_truth.json` locally.

**Open questions / next steps:**
- **Install Tesseract and calibrate `OCR_MIN_CONFIDENCE`.** The 6 dataset scans are clean
  rendered text, so they won't exercise the threshold; make blurred / JPEG-compressed / skewed
  versions to see where per-word confidence actually falls.
- **OCR library:** `pytesseract` chosen as you suggested (pure-Python wrapper, needs the
  Tesseract program). Alternatives (RapidOCR/EasyOCR) need onnxruntime/torch wheels that may not
  exist for Python 3.14. The engine call is isolated in `ocr.ocr_lines`, so swapping is one
  function.
- **Vision model.** Any OpenAI-compatible vision model via `LLM_VISION_MODEL`. Gemini works;
  `gemini-3.1-flash-lite` is the cheap one that had quota. Decide the cost-sensitive choice.
- **Keyword-first for text documents?** Would cut LLM calls; needs a ground-truth comparison
  first (see Decisions).
- **Latent bug, not fixed:** `extract_fields` builds `ShipmentFields(**reply)`, so a numeric
  JSON value (xlsx weights are bare numbers, e.g. `341715`) raises a pydantic `ValueError`,
  which `run.py` files as `unreadable`. Not seen in live runs, but a one-line
  `coerce_numbers_to_str` on `ShipmentFields` would remove the risk.
- **Design inconsistencies for you to decide** (all outside `extract.py`, so not touched):
  - `scripts/poll.py` + `GET /status` + the 409 run lock (teammate's "scheduling" commit) vs
    "no streaming pipeline". It is not Airflow/Spark/n8n, but it is scheduling; keep or drop?
  - `web/` is a static HTML dashboard, while the stack says Streamlit. `web/index.html` also
    doesn't render `field_issues` yet.
  - `README.md` still says Gemini's free tier is 500 requests/day/model; `gemini-3.6-flash`
    returned a limit of 20.
- `HANDOFF.md` is now ~12 entries; archive the old ones as its own commit.

**Synced through:** `c456daf` (committed by task: `65b57e0`, `6089248`, `e68e4f3`, `8d971e6`, `f283634`, `ccdd548`, `654d1e0`, `c456daf`)


---

## 2026-09-21 — Claude Code — Ling (Tesseract verified against the real scans)

**What changed:**
- `app/pipeline/ocr.py`: `ocr_lines()` now calls `ocr_available()` itself. The Tesseract path
  (`TESSERACT_CMD`) was only being set as a side effect of `ocr_available()`, so anything calling
  `ocr_lines()` directly got `TesseractNotFoundError`. The pipeline was unaffected (it always
  called `ocr_available()` first). Regression test added (34 tests, all pass).
- Local `.env` (gitignored): `TESSERACT_CMD=F:\Apps\Tesseract-OCR\tesseract.exe`.

**Environment facts:**
- Tesseract **5.5.3** is installed at `F:\Apps\Tesseract-OCR` (161 languages). It is not on
  `PATH` and not in the default `C:\Program Files` folder, so `TESSERACT_CMD` is required on this
  machine.
- `pip install tesseract` installs an **unrelated astronomy library** ("Tesselation based
  Recovery of Amorphous halo Concentrations"), not the OCR engine. It is in `.venv` and does no
  harm, but can be removed with `pip uninstall tesseract`. The OCR engine is a Windows program;
  pip only provides the `pytesseract` wrapper.

**Verification (real Tesseract, real scans):**
- `email_512`-`514` (SI + BL): page confidence only **62-72** and per-field 10-69. It misreads
  `6 x 40'HC` as `8x 40}` (conf 10) and `128,544` as `128.544`; OCR also often drops the colon
  after a label, so the keyword pass finds 0-2 of 7 fields.
- So at `OCR_MIN_CONFIDENCE=80` (kept, per the owner) every field goes to the vision model.
  End to end on all 6 documents: **7/7 fields, all correct, 0 issues, 6 vision calls** (one per
  document), on `gemini-3.1-flash-lite`. Nothing Tesseract misread was accepted.

**Findings (not acted on):**
- **Upscaling before OCR helps.** Page confidence goes ~72 -> ~89 at 2x-3x and the text is nearly
  right (`Containers 6 x 40'HC`, `Gross Weight 128,544 KG`). But it is not clean: per-field
  confidence stays erratic (26-89), 3x is worse than 2x on some documents, and dropped colons
  still cap keyword hits at 3/7. Worth a proper experiment when the threshold is calibrated; it
  would cut vision calls, not remove them.
- The keyword matcher requires a colon. Accepting a missing/garbled one ("Shipper. ACME") would
  raise keyword hits, at the risk of false matches.

**Decisions / deferred:**
- `OCR_MIN_CONFIDENCE` stays 80; owner will verify later.
- Left for later, as instructed: the scheduling/`poll.py` and static-dashboard-vs-Streamlit
  questions, and the numeric-JSON `ShipmentFields` coercion bug (see previous entry).
- "Keyword-first for text documents" is still an open, undecided idea (explained to the owner,
  who was unsure what it meant): use the deterministic label lookup as the *first* extractor
  for text files too, and call the LLM only for fields it misses. It would save LLM calls but
  finds all 7 fields in only 124 of 242 documents, so the LLM stays primary for now.

**Open questions / next steps:**
- Calibrate `OCR_MIN_CONFIDENCE` on degraded scans (blur, JPEG, skew); the dataset's own scans
  are clean, and even they score low at native resolution.
- Try 2x upscaling in `ocr_lines()`, measured against the vision-call count.

**Synced through:** `c456daf` (committed by task: `65b57e0`, `6089248`, `e68e4f3`, `8d971e6`, `f283634`, `ccdd548`, `654d1e0`, `c456daf`)
