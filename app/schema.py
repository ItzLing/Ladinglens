"""Shared data model for the classify -> extract -> compare pipeline."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class EmailCategory(str, Enum):
    BL_COMPARISON = "BL_COMPARISON"
    SI_REQUEST = "SI_REQUEST"
    INVOICE_QUERY = "INVOICE_QUERY"
    GENERAL = "GENERAL"
    SPAM = "SPAM"


class ReviewReason(str, Enum):
    WRONG_DOC_TYPE = "wrong_doc_type"
    MISSING_ATTACHMENT = "missing_attachment"
    UNREADABLE = "unreadable"
    MISSING_VALUE = "missing_value"
    LOW_CONFIDENCE = "low_confidence"
    PROCESSING_ERROR = "processing_error"


class ShipmentFields(BaseModel):
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    notify_party: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    container_count: Optional[str] = None
    gross_weight_kg: Optional[str] = None


class FieldIssueReason(str, Enum):
    NOT_FOUND = "not_found"
    INVALID_VALUE = "invalid_value"
    UNREADABLE = "unreadable"


class FieldIssue(BaseModel):
    """A field that could not be resolved, with what a reviewer needs to settle it.

    Internal only: it rides along in results.jsonl and report.json, never in the
    submission, which must keep the hackathon's shape.
    """

    document: str  # "SI" or "BL"
    file: str
    field: str
    reason: FieldIssueReason
    detail: str  # why, including the route tried (e.g. "OCR confidence 42 < 80")
    source: str  # last step tried: "text", "ocr" or "vision"
    # The best candidate found. Kept for the reviewer, never used as the answer.
    value: Optional[str] = None
    evidence: Optional[str] = None  # the OCR line / text snippet it came from


class ExtractionResult(BaseModel):
    """What extracting one document produced: accepted fields, and unresolved ones."""

    file: str
    fields: ShipmentFields
    sources: dict[str, str] = {}  # accepted field -> "text", "ocr", "ocr_llm" or "vision"
    issues: list[FieldIssue] = []


class ComparisonResult(BaseModel):
    email_id: str
    category: EmailCategory
    # Internal only, deliberately absent from to_submission(): retained so the
    # confidence threshold can be re-swept offline against a cached run.
    confidence: Optional[float] = None
    mismatch_found: bool = False
    mismatches: dict[str, dict[str, Optional[str]]] = {}
    needs_review: bool = False
    review_reason: Optional[ReviewReason] = None
    field_issues: list[FieldIssue] = []

    def to_submission(self) -> dict:
        """Map to the hackathon's sample_submission.json shape."""
        if self.needs_review:
            status = "NEEDS_REVIEW"
        elif self.mismatch_found:
            status = "MISMATCH"
        else:
            status = "OK"
        return {
            "category": self.category.value,
            "status": status,
            "review_reason": self.review_reason.value if self.review_reason else None,
            "defect_fields": list(self.mismatches.keys()),
            "has_defect": self.mismatch_found,
        }
