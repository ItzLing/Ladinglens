"""Orchestrator: classify -> extract -> compare, deciding needs_review.

needs_review is set explicitly at every branch below, never guessed away.
"""
from typing import Optional

from app.llm_client import LLMUnavailableError
from app.pipeline.classify import classify_email
from app.pipeline.compare import compare_fields
from app.pipeline.extract import extract_fields
from app.schema import ComparisonResult, EmailCategory, ReviewReason

CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.2


def _is_text_attachment(path: str) -> bool:
    # PDF/DOCX/XLSX extraction is deferred (see HANDOFF.md) -- route those
    # to needs_review(unreadable) instead of guessing at their content.
    return path.lower().endswith(".txt")


def process_email(email: dict, inbox) -> ComparisonResult:
    """Run classify -> extract -> compare for one email.

    `inbox` is a data/loader.py Inbox instance, used to fetch attachment text.
    """
    email_id = email["email_id"]

    try:
        category, confidence = classify_email(email)
    except (LLMUnavailableError, ValueError, KeyError):
        # The model never returned a usable category. Report the neutral bucket
        # so the submission stays well-formed, but flag it so the score isn't
        # read as a real classification.
        return ComparisonResult(
            email_id=email_id,
            category=EmailCategory.GENERAL,
            needs_review=True,
            review_reason=ReviewReason.PROCESSING_ERROR,
        )

    if category != EmailCategory.BL_COMPARISON:
        return ComparisonResult(
            email_id=email_id, category=category, confidence=confidence
        )

    if confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.LOW_CONFIDENCE,
        )

    attachments = email.get("attachments", [])
    si_candidates = [a for a in attachments if "_SI" in a]
    bl_candidates = [a for a in attachments if "_BL" in a]

    if not si_candidates or not bl_candidates:
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.MISSING_ATTACHMENT,
        )

    si_path, bl_path = si_candidates[0], bl_candidates[0]

    if not (_is_text_attachment(si_path) and _is_text_attachment(bl_path)):
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.UNREADABLE,
        )

    try:
        si_fields = extract_fields(inbox.read_text(si_path))
        bl_fields = extract_fields(inbox.read_text(bl_path))
    except LLMUnavailableError:
        # An API failure says nothing about the document -- keep it out of the
        # unreadable bucket so rate limits don't masquerade as real verdicts.
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.PROCESSING_ERROR,
        )
    except (ValueError, OSError):
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.UNREADABLE,
        )

    si_missing = any(v is None for v in si_fields.model_dump().values())
    bl_missing = any(v is None for v in bl_fields.model_dump().values())
    if si_missing or bl_missing:
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.MISSING_VALUE,
        )

    mismatches = compare_fields(si_fields, bl_fields)
    return ComparisonResult(
        email_id=email_id,
        category=category,
        confidence=confidence,
        mismatch_found=bool(mismatches),
        mismatches=mismatches,
    )


def run_pipeline(inbox, limit: Optional[int] = None) -> tuple[dict, dict]:
    """Process the inbox, or only its first `limit` emails.

    Returns (submission, classify_records). classify_records pairs each email's
    raw self-reported confidence with its computed verdict, so the confidence
    threshold can be re-swept offline instead of re-spending API quota.
    """
    emails = inbox.emails()
    if limit is not None:
        emails = emails[:limit]

    submission = {}
    classify_records = {}
    for email in emails:
        result = process_email(email, inbox)
        entry = result.to_submission()
        submission[result.email_id] = entry
        classify_records[result.email_id] = {"confidence": result.confidence, **entry}
    return submission, classify_records
