"""Thin Google Gen AI (Gemini) SDK wrapper for JSON-only structured calls."""
import json
import os
from typing import Any, Optional

from google import genai
from google.genai import types

_client: Optional[genai.Client] = None


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


def call_json(system: str, user: str, max_tokens: int = 1024) -> dict[str, Any]:
    """Call the model and parse its reply as JSON.

    `system` must instruct the model to reply with JSON only, no prose.
    """
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    response = _get_client().models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        ),
    )
    text = response.text or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {text!r}") from exc
