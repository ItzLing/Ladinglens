"""Stage 1: email -> category (+ confidence)."""
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
{"category": "<one of the five values above>", "confidence": <float 0-1>}

`confidence` is your own self-assessed certainty in the category call."""


def classify_email(email: dict) -> tuple[EmailCategory, float]:
    """Classify an email. Returns (category, confidence in [0, 1])."""
    user = (
        f"Subject: {email.get('subject', '')}\n"
        f"From: {email.get('from', '')}\n"
        f"Body:\n{email.get('body', '')}\n"
        f"Attachments: {email.get('attachments', [])}"
    )
    result = call_json(SYSTEM_PROMPT, user)
    category = EmailCategory(result["category"])
    confidence = float(result.get("confidence", 1.0))
    return category, confidence
