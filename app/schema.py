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
