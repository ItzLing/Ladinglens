"""Orchestrator: classify -> extract -> compare, deciding needs_review.

needs_review is set explicitly at every branch below, never guessed away.
"""
import json
import logging
import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app.llm_client import LLMUnavailableError, llm_request_context
from app.pipeline.classify import classify_email
from app.pipeline.compare import compare_fields
from app.pipeline.extract import extract_fields
from app.pipeline.read_document import read_document
from app.schema import ComparisonResult, EmailCategory, ReviewReason

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
) -> ComparisonResult:
    return ComparisonResult(
        email_id=email_id,
        category=category,
        confidence=confidence,
        needs_review=True,
        review_reason=ReviewReason.PROCESSING_ERROR,
        failure_stage=stage,
    )


def _extract_document(
    *,
    email_id: str,
    stage: str,
    path: str,
    inbox,
    category: EmailCategory,
    confidence: float,
) -> tuple[object, Optional[ComparisonResult]]:
    """Read and extract one document, translating failure into a review result."""
    try:
        with llm_request_context(email_id, stage):
            return extract_fields(read_document(inbox, path)), None
    except LLMUnavailableError as exc:
        # Provider failures say nothing about document quality.
        _log_stage_failure(email_id, stage, exc, "processing_error")
        return None, _processing_error(
            email_id, stage, category=category, confidence=confidence
        )
    except (ValueError, OSError) as exc:
        # Malformed output and unreadable local files are permanent for this run.
        _log_stage_failure(email_id, stage, exc, "unreadable")
        return None, ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.UNREADABLE,
            failure_stage=stage,
        )
    except Exception as exc:
        # The outer boundary remains the final guard, while this preserves stage.
        _log_stage_failure(email_id, stage, exc, "processing_error")
        return None, _processing_error(
            email_id, stage, category=category, confidence=confidence
        )


def process_email(email: dict, inbox) -> ComparisonResult:
    """Run classify -> extract -> compare for one email.

    `inbox` is a data/loader.py Inbox instance, used to fetch attachment text.
    """
    email_id = email["email_id"]

    try:
        with llm_request_context(email_id, "classification"):
            category, confidence = classify_email(email)
    except (LLMUnavailableError, ValueError, KeyError, TypeError) as exc:
        # The model never returned a usable category. Report the neutral bucket
        # so the submission stays well-formed, but flag it so the score isn't
        # read as a real classification.
        _log_stage_failure(email_id, "classification", exc, "processing_error")
        return _processing_error(email_id, "classification")
    except Exception as exc:
        _log_stage_failure(email_id, "classification", exc, "processing_error")
        return _processing_error(email_id, "classification")

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
            failure_stage="attachment_identification",
        )

    si_path, bl_path = si_candidates[0], bl_candidates[0]

    si_fields, failure = _extract_document(
        email_id=email_id,
        stage="si_extraction",
        path=si_path,
        inbox=inbox,
        category=category,
        confidence=confidence,
    )
    if failure is not None:
        return failure

    bl_fields, failure = _extract_document(
        email_id=email_id,
        stage="bl_extraction",
        path=bl_path,
        inbox=inbox,
        category=category,
        confidence=confidence,
    )
    if failure is not None:
        return failure

    si_missing = any(v is None for v in si_fields.model_dump().values())
    bl_missing = any(v is None for v in bl_fields.model_dump().values())
    if si_missing or bl_missing:
        return ComparisonResult(
            email_id=email_id,
            category=category,
            confidence=confidence,
            needs_review=True,
            review_reason=ReviewReason.MISSING_VALUE,
            failure_stage="field_validation",
        )

    try:
        mismatches = compare_fields(si_fields, bl_fields)
    except Exception as exc:
        _log_stage_failure(email_id, "comparison", exc, "processing_error")
        return _processing_error(
            email_id,
            "comparison",
            category=category,
            confidence=confidence,
        )
    return ComparisonResult(
        email_id=email_id,
        category=category,
        confidence=confidence,
        mismatch_found=bool(mismatches),
        mismatches=mismatches,
    )


SUBMISSION_KEYS = ("category", "status", "review_reason", "defect_fields", "has_defect")


def _failed(record: dict) -> bool:
    return record.get("review_reason") == ReviewReason.PROCESSING_ERROR.value


def _better_failure(prior: Optional[dict], new: dict) -> dict:
    """Pick whichever failed attempt still knows the most.

    A failure after a successful classification keeps the real category; one
    where classification itself failed only has the GENERAL fallback. Retrying
    while the API is down must not trade the former for the latter.
    """
    if prior is None:
        return new
    if prior["category"] != EmailCategory.GENERAL.value:
        if new["category"] == EmailCategory.GENERAL.value:
            return prior
    return new


def _load_checkpoint(path) -> tuple[dict, dict]:
    """Read a checkpoint file, split into (succeeded, failed) by email_id.

    Failures are kept separate so resuming retries them rather than banking an
    API outage as a verdict -- but they're still returned, so a retry that also
    fails can fall back to what the earlier attempt knew.
    """
    if path is None or not path.exists():
        return {}, {}
    done: dict = {}
    failed: dict = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a run killed mid-write can leave one torn line
        email_id = record["email_id"]
        if _failed(record):
            failed[email_id] = _better_failure(failed.get(email_id), record)
        else:
            done[email_id] = record
            failed.pop(email_id, None)
    return done, failed


def _record(result) -> dict:
    """Flatten a result into one checkpoint line.

    Carries `mismatches` (the per-field SI/BL values) alongside the submission
    fields, since to_submission() drops them and the review UI needs them.
    """
    return {
        "email_id": result.email_id,
        "confidence": result.confidence,
        "mismatches": result.mismatches,
        "failure_stage": result.failure_stage,
        **result.to_submission(),
    }


def run_pipeline(
    inbox,
    limit: Optional[int] = None,
    checkpoint_path=None,
    resume: bool = False,
    concurrency: Optional[int] = None,
) -> tuple[dict, dict]:
    """Process the inbox, or only its first `limit` emails.

    Each result is appended to `checkpoint_path` as it completes, so a run that
    dies partway can be continued with resume=True instead of restarting. Work
    is spread over a thread pool because the pipeline is I/O-bound on API calls,
    not CPU-bound.

    Returns (submission, classify_records). classify_records pairs each email's
    raw self-reported confidence with its computed verdict, so the confidence
    threshold can be re-swept offline instead of re-spending API quota.
    """
    if concurrency is None:
        concurrency = int(os.environ.get("LLM_CONCURRENCY", "8"))

    emails = inbox.emails()
    if limit is not None:
        emails = emails[:limit]

    done, failed = _load_checkpoint(checkpoint_path) if resume else ({}, {})
    if checkpoint_path is not None and not resume:
        checkpoint_path.write_text("")

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

    def work(email_id: str, email: dict) -> dict:
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
                if _failed(record):
                    record = _better_failure(failed.get(email_id), record)
                done[email_id] = record
                if checkpoint_path is not None:
                    with checkpoint_path.open("a") as fh:
                        fh.write(json.dumps(record) + "\n")

    submission = {}
    classify_records = {}
    for email_id, _email in email_items:  # restore input order after concurrency
        record = done[email_id]
        entry = {key: record[key] for key in SUBMISSION_KEYS}
        submission[email_id] = entry
        classify_records[email_id] = {"confidence": record["confidence"], **entry}
    return submission, classify_records
