"""Orchestrator: classify -> extract -> compare, deciding needs_review.

needs_review is set explicitly at every branch below, never guessed away.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from app.llm_client import LLMUnavailableError
from app.pipeline.classify import classify_email
from app.pipeline.compare import compare_fields
from app.pipeline.extract import extract_fields
from app.pipeline.read_document import read_document
from app.schema import ComparisonResult, EmailCategory, ReviewReason

CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.2


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

    try:
        si_fields = extract_fields(read_document(inbox, si_path))
        bl_fields = extract_fields(read_document(inbox, bl_path))
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
                if _failed(record):
                    record = _better_failure(failed.get(record["email_id"]), record)
                done[record["email_id"]] = record
                if checkpoint_path is not None:
                    with checkpoint_path.open("a") as fh:
                        fh.write(json.dumps(record) + "\n")

    submission = {}
    classify_records = {}
    for email in emails:  # restore input order, which completion order loses
        record = done[email["email_id"]]
        entry = {key: record[key] for key in SUBMISSION_KEYS}
        submission[email["email_id"]] = entry
        classify_records[email["email_id"]] = {"confidence": record["confidence"], **entry}
    return submission, classify_records
