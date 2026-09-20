"""Thin Google Gen AI (Gemini) SDK wrapper for JSON-only structured calls."""
import json
import os
import random
import time
from typing import Any, Optional

from google import genai
from google.genai import errors, types

# Free-tier quotas (~30 requests/min) make 429s routine on a full-inbox run, so
# transient API failures are retried here instead of reaching the pipeline.
MAX_ATTEMPTS = 5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Gemini 3.x spends "thinking" tokens out of the same budget as the reply, and
# measured ~800-980 of them on a single extract call. At 1024 the JSON was being
# truncated more often than not, which the pipeline then misread as an
# unreadable document, so the default needs real headroom above that.
DEFAULT_MAX_TOKENS = int(os.environ.get("GEMINI_MAX_TOKENS", "4096"))

_client: Optional[genai.Client] = None


class LLMUnavailableError(RuntimeError):
    """The API call failed and could not be completed.

    Deliberately distinct from the ValueError raised for malformed model output:
    callers use this to tell an infrastructure failure apart from a document the
    model genuinely could not read, so a rate limit never books itself as a
    verdict about the document.
    """


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to .env before running the pipeline."
            )
        _client = genai.Client(api_key=api_key)
    return _client


def _was_truncated(response) -> bool:
    """True if the reply stopped because it ran out of output budget."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return False
    reason = getattr(candidates[0], "finish_reason", None)
    return reason is not None and getattr(reason, "name", str(reason)) == "MAX_TOKENS"


def _generate(model: str, system: str, user: str, max_tokens: int):
    """Call the model, retrying transient failures with exponential backoff."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _get_client().models.generate_content(
                model=model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )
        except errors.APIError as exc:
            status = getattr(exc, "code", None)
            if status not in RETRYABLE_STATUS_CODES or attempt == MAX_ATTEMPTS - 1:
                raise LLMUnavailableError(
                    f"Gemini call failed after {attempt + 1} attempt(s): {exc}"
                ) from exc
            time.sleep(2 ** (attempt + 1) + random.uniform(0, 1))


def call_json(system: str, user: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    """Call the model and parse its reply as JSON.

    `system` must instruct the model to reply with JSON only, no prose.

    Raises LLMUnavailableError if the API could not be reached or the reply was
    cut off, ValueError if it replied with something that isn't JSON.
    """
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    response = _generate(model, system, user, max_tokens)

    # A truncated reply is a budget problem, not a malformed one: surfacing it as
    # a JSON parse error would let the pipeline book it against the document.
    if _was_truncated(response):
        raise LLMUnavailableError(
            f"reply hit the {max_tokens}-token output budget before completing "
            "(thinking tokens share this budget -- raise GEMINI_MAX_TOKENS)"
        )

    text = response.text or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {text!r}") from exc
