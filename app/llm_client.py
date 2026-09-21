"""OpenAI-compatible client for JSON-only structured calls.

Ollama, Groq, Cerebras, OpenRouter and Gemini all speak the OpenAI chat
completions API, so the provider is a base URL plus a model name in .env rather
than a code change. See .env.example for ready-made settings for each.
"""
import base64
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Optional

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.5

logger = logging.getLogger(__name__)

_email_id: ContextVar[Optional[str]] = ContextVar("llm_email_id", default=None)
_processing_stage: ContextVar[Optional[str]] = ContextVar(
    "llm_processing_stage", default=None
)

_client: Optional[OpenAI] = None


class LLMUnavailableError(RuntimeError):
    """The API call failed and could not be completed.

    Deliberately distinct from the ValueError raised for malformed model output:
    callers use this to tell an infrastructure failure apart from a document the
    model genuinely could not read, so a rate limit never books itself as a
    verdict about the document.
    """


@contextmanager
def llm_request_context(email_id: str, stage: str) -> Iterator[None]:
    """Attach safe per-email metadata to provider logs in the current thread."""
    email_token = _email_id.set(email_id)
    stage_token = _processing_stage.set(stage)
    try:
        yield
    finally:
        _processing_stage.reset(stage_token)
        _email_id.reset(email_token)


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
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if not isinstance(exc, APIStatusError):
        return False
    status_code = getattr(exc, "status_code", None)
    return status_code in {408, 429} or (
        isinstance(status_code, int) and 500 <= status_code < 600
    )


def _log_fields(
    *,
    attempt_number: Optional[int],
    error_type: Optional[str] = None,
    status_code: Optional[int] = None,
    retry_exhausted: bool = False,
) -> dict[str, Any]:
    """Return non-sensitive metadata shared by provider log records."""
    return {
        "email_id": _email_id.get(),
        "processing_stage": _processing_stage.get(),
        "attempt_number": attempt_number,
        "max_attempts": MAX_ATTEMPTS,
        "error_type": error_type,
        "status_code": status_code,
        "retry_exhausted": retry_exhausted,
    }


def _was_truncated(response) -> bool:
    """True if the reply stopped because it ran out of output budget."""
    choices = getattr(response, "choices", None) or []
    return bool(choices) and getattr(choices[0], "finish_reason", None) == "length"


def _generate(
    model: str,
    messages: list,
    max_tokens: int,
    json_mode: bool,
    *,
    sleep_fn: Optional[Callable[[float], None]] = None,
):
    """Call the model, retrying transient failures with exponential backoff."""
    if sleep_fn is None:
        sleep_fn = time.sleep

    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
    for attempt_number in range(1, MAX_ATTEMPTS + 1):
        try:
            response = _get_client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                # Extraction is a reading task, not a creative one. At the
                # default sampling temperature the same document yields
                # different field values between runs -- when the SI and BL
                # happen to disagree, compare.py reports a discrepancy that
                # isn't in the documents.
                temperature=0,
                messages=messages,
                **extra,
            )
            logger.info(
                "llm_request_succeeded",
                extra=_log_fields(attempt_number=attempt_number),
            )
            return response
        except (
            APITimeoutError,
            RateLimitError,
            APIConnectionError,
            APIStatusError,
        ) as exc:
            retryable = _is_retryable(exc)
            exhausted = retryable and attempt_number == MAX_ATTEMPTS
            status_code = getattr(exc, "status_code", None)
            fields = _log_fields(
                attempt_number=attempt_number,
                error_type=type(exc).__name__,
                status_code=status_code,
                retry_exhausted=exhausted,
            )
            if not retryable or exhausted:
                fields["retryable"] = retryable
                fields["final_status"] = "provider_error"
                logger.error("llm_request_failed", extra=fields)
                status_suffix = (
                    f", HTTP {status_code}" if status_code is not None else ""
                )
                raise LLMUnavailableError(
                    f"LLM call failed after {attempt_number} attempt(s) "
                    f"({type(exc).__name__}{status_suffix})"
                ) from exc

            delay_seconds = RETRY_BASE_DELAY_SECONDS * (2 ** (attempt_number - 1))
            fields.update(
                {
                    "retryable": True,
                    "next_attempt": attempt_number + 1,
                    "delay_seconds": delay_seconds,
                }
            )
            logger.warning("llm_request_retry", extra=fields)
            sleep_fn(delay_seconds)


def _default_max_tokens() -> int:
    # Reasoning models spend thinking tokens out of this same budget, so it
    # needs headroom well above the size of the reply itself.
    return int(os.environ.get("LLM_MAX_TOKENS", "4096"))


def _complete(model: str, messages: list, max_tokens: int, json_mode: bool) -> str:
    """Run one call and return the reply text, raising on failure or truncation."""
    response = _generate(model, messages, max_tokens, json_mode)

    # A truncated reply is a budget problem, not a malformed one: surfacing it as
    # a JSON parse error would let the pipeline book it against the document.
    if _was_truncated(response):
        logger.error(
            "llm_response_truncated",
            extra={
                **_log_fields(
                    attempt_number=None,
                    error_type="TruncatedResponse",
                ),
                "final_status": "processing_error",
            },
        )
        raise LLMUnavailableError(
            f"reply hit the {max_tokens}-token output budget before completing "
            "(raise LLM_MAX_TOKENS)"
        )

    choices = getattr(response, "choices", None) or []
    return (choices[0].message.content or "") if choices else ""


def call_json(system: str, user: str, max_tokens: Optional[int] = None) -> dict[str, Any]:
    """Call the model and parse its reply as JSON.

    `system` must instruct the model to reply with JSON only, no prose.

    Raises LLMUnavailableError if the API could not be reached or the reply was
    cut off, ValueError if it replied with something that isn't JSON.
    """
    model = os.environ.get("LLM_MODEL", "llama3.1:8b")
    text = _complete(
        model,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens or _default_max_tokens(),
        json_mode=True,
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(
            "llm_response_invalid_json",
            extra={
                **_log_fields(
                    attempt_number=None,
                    error_type=type(exc).__name__,
                ),
                "final_status": "invalid_response",
            },
        )
        raise ValueError("model did not return valid JSON") from exc


def vision_model_name() -> str:
    return os.environ.get("LLM_VISION_MODEL") or os.environ.get("LLM_MODEL", "llama3.1:8b")


def call_vision_json(
    system: str,
    user: str,
    images: list[tuple[bytes, str]],
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Send page images (bytes, mime type) with a prompt and parse the reply as JSON.

    Uses LLM_VISION_MODEL if set, since the text model may not accept images
    (a local llama3.1 doesn't); otherwise falls back to LLM_MODEL.

    Raises LLMUnavailableError if the API could not be reached, rejected the
    images, or the reply was cut off, ValueError if the reply is not JSON.
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for data, mime in images:
        encoded = base64.b64encode(data).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
        )
    text = _complete(
        vision_model_name(),
        [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        max_tokens or _default_max_tokens(),
        json_mode=True,
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {text!r}") from exc
