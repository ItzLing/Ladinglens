"""Thin Anthropic SDK wrapper for JSON-only structured calls."""
import json
import os
from typing import Any, Optional

from anthropic import Anthropic

_client: Optional[Anthropic] = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env before running the pipeline."
            )
        _client = Anthropic(api_key=api_key)
    return _client


def call_json(system: str, user: str, max_tokens: int = 1024) -> dict[str, Any]:
    """Call the model and parse its reply as JSON.

    `system` must instruct the model to reply with JSON only, no prose.
    """
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    response = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {text!r}") from exc
