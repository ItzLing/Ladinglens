"""Stage 1: email -> category (+ confidence, + a one-line summary)."""
from typing import Optional

from app.llm_client import call_json
from app.schema import EmailCategory

SYSTEM_PROMPT = """You classify inbound shipping-operations emails into exactly one category:

- BL_COMPARISON: asks to check/confirm a draft Bill of Lading against a Shipping
  Instruction, usually with SI + draft BL attached.
- SI_REQUEST: asks to issue or send a new Shipping Instruction; no comparison requested.
- INVOICE_QUERY: about freight invoices, charges, or payment status.
- GENERAL: any other legitimate business email (status updates, scheduling, etc.).
- SPAM: unsolicited, irrelevant, or clearly automated marketing content.

Respond with JSON only, no prose, in this exact shape:
{"category": "<one of the five values above>", "confidence": <float 0-1>,
 "summary": "<one plain sentence, at most 20 words, saying what the email is about>"}

`confidence` is your own self-assessed certainty in the category call."""

MAX_SUMMARY_CHARS = 200


def classify_email(email: dict) -> tuple[EmailCategory, float, Optional[str]]:
    """Classify an email. Returns (category, confidence in [0, 1], summary or None)."""
    user = (
        f"Subject: {email.get('subject', '')}\n"
        f"From: {email.get('from', '')}\n"
        f"Body:\n{email.get('body', '')}\n"
        f"Attachments: {email.get('attachments', [])}"
    )
    result = call_json(SYSTEM_PROMPT, user)
    category = EmailCategory(result["category"])
    confidence = float(result.get("confidence", 1.0))
    summary = " ".join(str(result.get("summary") or "").split())[:MAX_SUMMARY_CHARS] or None
    return category, confidence, summary
