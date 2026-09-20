"""OpenAI-compatible client for JSON-only structured calls.

Ollama, Groq, Cerebras, OpenRouter and Gemini all speak the OpenAI chat
completions API, so the provider is a base URL plus a model name in .env rather
than a code change. See .env.example for ready-made settings for each.
"""
import json
import os
import random
import time
from typing import Any, Optional

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

MAX_ATTEMPTS = 5
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}

_client: Optional[OpenAI] = None


class LLMUnavailableError(RuntimeError):
    """The API call failed and could not be completed.

    Deliberately distinct from the ValueError raised for malformed model output:
    callers use this to tell an infrastructure failure apart from a document the
    model genuinely could not read, so a rate limit never books itself as a
    verdict about the document.
    """


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        base_url = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
        # Local runtimes ignore the key, but the SDK insists on a non-empty one.
        api_key = os.environ.get("LLM_API_KEY") or "not-needed"
        _client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            # The SDK defaults to a 600s timeout and its own retries. Stacked
            # under our backoff, one hung call could stall a run for the better
            # part of an hour. Retries belong to _generate(), not the SDK.
            timeout=float(os.environ.get("LLM_TIMEOUT", "60")),
            max_retries=0,
        )
    return _client


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (RateLimitError, APIConnectionError)):
        return True
    return getattr(exc, "status_code", None) in RETRYABLE_STATUS_CODES


def _was_truncated(response) -> bool:
    """True if the reply stopped because it ran out of output budget."""
    choices = getattr(response, "choices", None) or []
    return bool(choices) and getattr(choices[0], "finish_reason", None) == "length"


def _generate(model: str, system: str, user: str, max_tokens: int):
    """Call the model, retrying transient failures with exponential backoff."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return _get_client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                # Extraction is a reading task, not a creative one. At the
                # default sampling temperature the same document yields
                # different field values between runs -- when the SI and BL
                # happen to disagree, compare.py reports a discrepancy that
                # isn't in the documents.
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except (RateLimitError, APIConnectionError, APIStatusError) as exc:
            if not _is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                raise LLMUnavailableError(
                    f"LLM call failed after {attempt + 1} attempt(s): {exc}"
                ) from exc
            time.sleep(2 ** (attempt + 1) + random.uniform(0, 1))


def call_json(system: str, user: str, max_tokens: Optional[int] = None) -> dict[str, Any]:
    """Call the model and parse its reply as JSON.

    `system` must instruct the model to reply with JSON only, no prose.

    Raises LLMUnavailableError if the API could not be reached or the reply was
    cut off, ValueError if it replied with something that isn't JSON.
    """
    model = os.environ.get("LLM_MODEL", "llama3.1:8b")
    if max_tokens is None:
        # Reasoning models spend thinking tokens out of this same budget, so it
        # needs headroom well above the size of the JSON itself.
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "4096"))

    response = _generate(model, system, user, max_tokens)

    # A truncated reply is a budget problem, not a malformed one: surfacing it as
    # a JSON parse error would let the pipeline book it against the document.
    if _was_truncated(response):
        raise LLMUnavailableError(
            f"reply hit the {max_tokens}-token output budget before completing "
            "(raise LLM_MAX_TOKENS)"
        )

    choices = getattr(response, "choices", None) or []
    text = (choices[0].message.content or "") if choices else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {text!r}") from exc
