"""Orchestrator: classify -> extract -> compare, deciding needs_review.

needs_review is set explicitly at every branch below, never guessed away.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app.llm_client import LLMUnavailableError
from app.pipeline.classify import classify_email
from app.pipeline.compare import compare_fields
from app.pipeline.extract import extract_document
from app.schema import ComparisonResult, EmailCategory, ExtractedDocument, ReviewReason
from app.store import better_failure, is_failed

CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.2


def _extracted(si, bl) -> dict:
    """Every value read from the two documents, kept alongside the verdict."""
    return {
        label: ExtractedDocument(
            file=result.file, fields=result.fields.model_dump(), sources=result.sources
        )
        for label, result in (("SI", si), ("BL", bl))
    }


def process_email(email: dict, inbox) -> ComparisonResult:
    """Run classify -> extract -> compare for one email.

    `inbox` is a data/loader.py Inbox instance, used to fetch attachment text.
    """
    email_id = email["email_id"]

    try:
        category, confidence, summary = classify_email(email)
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

    base = dict(email_id=email_id, category=category, confidence=confidence, summary=summary)

    if category != EmailCategory.BL_COMPARISON:
        return ComparisonResult(**base)

    if confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return ComparisonResult(
            **base, needs_review=True, review_reason=ReviewReason.LOW_CONFIDENCE
        )

    attachments = email.get("attachments", [])
    si_candidates = [a for a in attachments if "_SI" in a]
    bl_candidates = [a for a in attachments if "_BL" in a]

    if not si_candidates or not bl_candidates:
        return ComparisonResult(
            **base, needs_review=True, review_reason=ReviewReason.MISSING_ATTACHMENT
        )

    si_path, bl_path = si_candidates[0], bl_candidates[0]

    try:
        si = extract_document(inbox, si_path, "SI")
        bl = extract_document(inbox, bl_path, "BL")
    except LLMUnavailableError:
        # An API failure says nothing about the document -- keep it out of the
        # unreadable bucket so rate limits don't masquerade as real verdicts.
        return ComparisonResult(
            **base, needs_review=True, review_reason=ReviewReason.PROCESSING_ERROR
        )
    except (ValueError, OSError):
        return ComparisonResult(
            **base, needs_review=True, review_reason=ReviewReason.UNREADABLE
        )

    extracted = _extracted(si, bl)

    # A field the ladder could not settle is never compared or guessed at: the
    # email goes to a human, with each field's reason and evidence attached.
    issues = si.issues + bl.issues
    if issues:
        return ComparisonResult(
            **base,
            needs_review=True,
            review_reason=ReviewReason.MISSING_VALUE,
            field_issues=issues,
            extracted=extracted,
        )

    mismatches = compare_fields(si.fields, bl.fields)
    return ComparisonResult(
        **base,
        mismatch_found=bool(mismatches),
        mismatches=mismatches,
        extracted=extracted,
    )


SUBMISSION_KEYS = ("category", "status", "review_reason", "defect_fields", "has_defect")


def _record(result) -> dict:
    """Flatten a result into one checkpoint line.

    Carries `mismatches` (the per-field SI/BL values) and `field_issues` (why a
    field went to review, with its evidence) alongside the submission fields,
    since to_submission() drops them and the review UI needs them.
    """
    return {
        "email_id": result.email_id,
        "confidence": result.confidence,
        "mismatches": result.mismatches,
        "field_issues": [issue.model_dump(mode="json") for issue in result.field_issues],
        "summary": result.summary,
        "extracted": {k: v.model_dump(mode="json") for k, v in result.extracted.items()},
        **result.to_submission(),
    }


def run_pipeline(
    inbox,
    limit: Optional[int] = None,
    checkpoint=None,
    resume: bool = False,
    concurrency: Optional[int] = None,
) -> tuple[dict, dict]:
    """Process the inbox, or only its first `limit` emails.

    Each result is appended to `checkpoint` (a store.Checkpoint) as it completes,
    so a run that dies partway can be continued with resume=True instead of
    restarting. Work is spread over a thread pool because the pipeline is I/O-bound
    on API calls, not CPU-bound.

    Returns (submission, classify_records). classify_records pairs each email's
    raw self-reported confidence with its computed verdict, so the confidence
    threshold can be re-swept offline instead of re-spending API quota.
    """
    if concurrency is None:
        concurrency = int(os.environ.get("LLM_CONCURRENCY", "8"))

    emails = inbox.emails()
    if limit is not None:
        emails = emails[:limit]

    done, failed = checkpoint.load() if checkpoint is not None and resume else ({}, {})
    if checkpoint is not None and not resume:
        checkpoint.reset()

    todo = [e for e in emails if e["email_id"] not in done]

    def work(email: dict) -> dict:
        try:
            return _record(process_email(email, inbox))
        except Exception:
            # One unexpected failure must not take the whole batch down with it.
            return _record(
                ComparisonResult(
                    email_id=email["email_id"],
                    category=EmailCategory.GENERAL,
                    needs_review=True,
                    review_reason=ReviewReason.PROCESSING_ERROR,
                )
            )

    if todo:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(work, email) for email in todo]
            # as_completed yields in this thread, so appends stay serialized.
            for future in as_completed(futures):
                record = future.result()
                if is_failed(record):
                    record = better_failure(failed.get(record["email_id"]), record)
                done[record["email_id"]] = record
                if checkpoint is not None:
                    checkpoint.append(record)

    submission = {}
    classify_records = {}
    for email in emails:  # restore input order, which completion order loses
        record = done[email["email_id"]]
        entry = {key: record[key] for key in SUBMISSION_KEYS}
        submission[email["email_id"]] = entry
        classify_records[email["email_id"]] = {"confidence": record["confidence"], **entry}
    return submission, classify_records
