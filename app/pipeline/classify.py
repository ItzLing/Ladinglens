"""Stage 1: email -> category (+ confidence, + a one-line summary)."""
from typing import Optional

from app.llm_client import call_json
from app.schema import EmailCategory

SYSTEM_PROMPT = """You classify inbound shipping-operations emails into exactly one category:

- BL_COMPARISON: wants a draft Bill of Lading checked against the Shipping
  Instruction. This includes an email that only asks for the draft BL to be sent
  for checking or confirmation. Attachments are common but NOT required -- many
  of these carry none, and their absence never rules the category out.
- SI_REQUEST: the Shipping Instruction itself is being handed over or asked for.
  These set out the shipment in the body -- shipper, consignee, notify party,
  ports, weights -- rather than asking for a document to be reviewed.
- INVOICE_QUERY: about freight invoices, charges, or payment status.
- GENERAL: any other legitimate business email, including automated notices from
  the company's own systems (billing runs, schedule changes, reminders).
- SPAM: unsolicited external marketing, or content irrelevant to the business.
  A machine-generated notice from an internal system is GENERAL, not SPAM.

To separate BL_COMPARISON from SI_REQUEST, ask what the sender wants done:
requesting a draft BL so it can be checked is BL_COMPARISON; supplying shipment
details so an instruction can be raised is SI_REQUEST. Both may mention a draft
BL, and neither reliably has attachments.

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
