"""Orchestrator: classify -> extract -> compare, deciding needs_review.

needs_review is set explicitly at every branch below, never guessed away.

Every stage is isolated: a failure in one becomes a controlled review result that
records which stage failed (`failure_stage`), and never stops the next email. Logs
carry the email ID, stage and error type only, never document contents.
"""
import logging
import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app import run_state
from app.llm_client import LLMUnavailableError, llm_request_context
from app.pipeline.classify import classify_email
from app.pipeline.compare import compare_fields
from app.pipeline.extract import extract_document
from app.schema import (
    ComparisonResult,
    EmailCategory,
    ExtractedDocument,
    ExtractionResult,
    ReviewReason,
)
from app.store import better_failure, is_failed

CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.2

logger = logging.getLogger(__name__)


def _log_stage_failure(
    email_id: str,
    stage: str,
    exc: Exception,
    final_status: str,
) -> None:
    """Log failure metadata without exception messages or document contents."""
    logger.error(
        "email_stage_failed",
        extra={
            "email_id": email_id,
            "processing_stage": stage,
            "final_status": final_status,
            "error_type": type(exc).__name__,
        },
    )


def _processing_error(
    email_id: str,
    stage: str,
    category: EmailCategory = EmailCategory.GENERAL,
    confidence: Optional[float] = None,
    summary: Optional[str] = None,
) -> ComparisonResult:
    return ComparisonResult(
        email_id=email_id,
        category=category,
        confidence=confidence,
        summary=summary,
        needs_review=True,
        review_reason=ReviewReason.PROCESSING_ERROR,
        failure_stage=stage,
    )


def _extract_document(
    *,
    email_id: str,
    stage: str,
    label: str,
    path: str,
    inbox,
    base: dict,
) -> tuple[Optional[ExtractionResult], Optional[ComparisonResult]]:
    """Read and extract one document, translating failure into a review result.

    `base` is the email's category, confidence and summary, kept on any failure.
    """
    try:
        with llm_request_context(email_id, stage):
            return extract_document(inbox, path, label), None
    except LLMUnavailableError as exc:
        # Provider failures say nothing about document quality.
        _log_stage_failure(email_id, stage, exc, "processing_error")
        return None, _processing_error(email_id, stage, **_without_id(base))
    except (ValueError, OSError) as exc:
        # Malformed output and unreadable local files are permanent for this run.
        _log_stage_failure(email_id, stage, exc, "unreadable")
        return None, ComparisonResult(
            **base,
            needs_review=True,
            review_reason=ReviewReason.UNREADABLE,
            failure_stage=stage,
        )
    except Exception as exc:
        # The outer boundary remains the final guard, while this preserves stage.
        _log_stage_failure(email_id, stage, exc, "processing_error")
        return None, _processing_error(email_id, stage, **_without_id(base))


def _without_id(base: dict) -> dict:
    return {k: v for k, v in base.items() if k != "email_id"}


def _extracted(si: ExtractionResult, bl: ExtractionResult) -> dict:
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
        with llm_request_context(email_id, "classification"):
            category, confidence, summary = classify_email(email)
    except (LLMUnavailableError, ValueError, KeyError, TypeError) as exc:
        # The model never returned a usable category. Report the neutral bucket
        # so the submission stays well-formed, but flag it so the score isn't
        # read as a real classification.
        _log_stage_failure(email_id, "classification", exc, "processing_error")
        return _processing_error(email_id, "classification")
    except Exception as exc:
        _log_stage_failure(email_id, "classification", exc, "processing_error")
        return _processing_error(email_id, "classification")

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
            **base,
            needs_review=True,
            review_reason=ReviewReason.MISSING_ATTACHMENT,
            failure_stage="attachment_identification",
        )

    si, failure = _extract_document(
        email_id=email_id, stage="si_extraction", label="SI",
        path=si_candidates[0], inbox=inbox, base=base,
    )
    if failure is not None:
        return failure

    bl, failure = _extract_document(
        email_id=email_id, stage="bl_extraction", label="BL",
        path=bl_candidates[0], inbox=inbox, base=base,
    )
    if failure is not None:
        return failure

    extracted = _extracted(si, bl)

    # A field the ladder could not settle is never compared or guessed at: the
    # email goes to a human, with each field's reason and evidence attached.
    issues = si.issues + bl.issues
    if issues:
        return ComparisonResult(
            **base,
            needs_review=True,
            review_reason=ReviewReason.MISSING_VALUE,
            failure_stage="field_validation",
            field_issues=issues,
            extracted=extracted,
        )

    try:
        mismatches = compare_fields(si.fields, bl.fields)
    except Exception as exc:
        _log_stage_failure(email_id, "comparison", exc, "processing_error")
        return _processing_error(email_id, "comparison", **_without_id(base))
    return ComparisonResult(
        **base,
        mismatch_found=bool(mismatches),
        mismatches=mismatches,
        extracted=extracted,
    )


SUBMISSION_KEYS = ("category", "status", "review_reason", "defect_fields", "has_defect")


def _record(result) -> dict:
    """Flatten a result into one checkpoint line.

    Carries what to_submission() drops but the review UI and later runs need:
    `mismatches` (the per-field SI/BL values), `field_issues` (why a field went to
    review, with its evidence), the email `summary`, every `extracted` value, and
    `failure_stage` (which stage failed).
    """
    return {
        "email_id": result.email_id,
        "confidence": result.confidence,
        "mismatches": result.mismatches,
        "field_issues": [issue.model_dump(mode="json") for issue in result.field_issues],
        "summary": result.summary,
        "extracted": {k: v.model_dump(mode="json") for k, v in result.extracted.items()},
        "failure_stage": result.failure_stage,
        **result.to_submission(),
    }


def run_pipeline(
    inbox,
    limit: Optional[int] = None,
    checkpoint=None,
    resume: bool = False,
    concurrency: Optional[int] = None,
    new_only: bool = False,
) -> tuple[dict, dict]:
    """Process the inbox, or only its first `limit` emails.

    Each result is appended to `checkpoint` (a store.Checkpoint) as it completes,
    so a run that dies partway can be continued with resume=True instead of
    restarting. Work is spread over a thread pool because the pipeline is I/O-bound
    on API calls, not CPU-bound.

    Returns (submission, classify_records). classify_records pairs each email's
    raw self-reported confidence with its computed verdict, so the confidence
    threshold can be re-swept offline instead of re-spending API quota.

    `resume` skips the emails already finished but retries the ones that failed.
    `new_only` goes further: it also leaves the failed ones alone, so only emails with
    no saved result at all are processed. That is what to use after adding emails to
    the inbox. It implies resume.
    """
    if concurrency is None:
        concurrency = int(os.environ.get("LLM_CONCURRENCY", "8"))

    emails = inbox.emails()
    if limit is not None:
        emails = emails[:limit]

    resume = resume or new_only
    done, failed = checkpoint.load() if checkpoint is not None and resume else ({}, {})
    if new_only:
        done.update(failed)  # a failed email already has a saved result: leave it as it is
        failed = {}
    if checkpoint is not None and not resume:
        checkpoint.reset()

    email_items = []
    for index, email in enumerate(emails):
        raw_email_id = email.get("email_id") if isinstance(email, Mapping) else None
        email_id = (
            raw_email_id
            if isinstance(raw_email_id, str) and raw_email_id
            else f"invalid_email_{index:04d}"
        )
        email_items.append((email_id, email))

    todo = [
        (email_id, email)
        for email_id, email in email_items
        if email_id not in done
    ]

    def work(email_id: str, email: dict) -> Optional[dict]:
        if run_state.stop_requested():
            return None  # asked to stop: leave this one for a resume
        if not isinstance(email, Mapping) or email.get("email_id") != email_id:
            invalid_record = TypeError("email record has no valid string email_id")
            _log_stage_failure(
                email_id, "email_validation", invalid_record, "processing_error"
            )
            return _record(_processing_error(email_id, "email_validation"))
        try:
            record = _record(process_email(email, inbox))
        except Exception as exc:
            # One unexpected failure must not take the whole batch down with it.
            _log_stage_failure(email_id, "email_boundary", exc, "processing_error")
            record = _record(_processing_error(email_id, "email_boundary"))
        logger.info(
            "email_processing_complete",
            extra={
                "email_id": record["email_id"],
                "processing_stage": record.get("failure_stage") or "complete",
                "final_status": record["status"],
                "error_type": None,
            },
        )
        return record

    if todo:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(work, email_id, email): email_id
                for email_id, email in todo
            }
            # as_completed yields in this thread, so appends stay serialized.
            for future in as_completed(futures):
                email_id = futures[future]
                try:
                    record = future.result()
                except Exception as exc:
                    # Protect the batch if the worker's own fallback fails.
                    _log_stage_failure(
                        email_id, "batch_boundary", exc, "processing_error"
                    )
                    record = _record(_processing_error(email_id, "batch_boundary"))
                if record is None:
                    continue
                # The scheduled ID is authoritative if a stage returns a wrong one.
                if record.get("email_id") != email_id:
                    returned_id = ValueError("stage returned a different email_id")
                    _log_stage_failure(
                        email_id,
                        "email_validation",
                        returned_id,
                        "processing_error",
                    )
                    record = _record(_processing_error(email_id, "email_validation"))
                if is_failed(record):
                    record = better_failure(failed.get(email_id), record)
                done[email_id] = record
                if checkpoint is not None:
                    checkpoint.append(record)

    submission = {}
    classify_records = {}
    for email_id, _email in email_items:  # restore input order after concurrency
        if email_id not in done:
            continue  # only possible when the run was stopped early
        record = done[email_id]
        entry = {key: record[key] for key in SUBMISSION_KEYS}
        submission[email_id] = entry
        classify_records[email_id] = {"confidence": record["confidence"], **entry}
    return submission, classify_records
