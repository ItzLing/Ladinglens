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
