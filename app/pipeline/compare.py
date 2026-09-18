"""Stage 3: SI vs BL -> mismatches.

Deterministic, no LLM call here -- once both documents are normalized to the
same schema by extract.py, the diff itself should be plain, auditable Python.
"""
from typing import Optional

from app.schema import ShipmentFields


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return " ".join(value.split()).strip().upper()


def compare_fields(si: ShipmentFields, bl: ShipmentFields) -> dict[str, dict[str, Optional[str]]]:
    """Diff two ShipmentFields field by field, after light normalization.

    Returns {field_name: {"si": value, "bl": value}} for every field whose
    normalized (whitespace-collapsed, upper-cased) values differ.
    """
    mismatches: dict[str, dict[str, Optional[str]]] = {}
    for field in ShipmentFields.model_fields:
        si_val = getattr(si, field)
        bl_val = getattr(bl, field)
        if _normalize(si_val) != _normalize(bl_val):
            mismatches[field] = {"si": si_val, "bl": bl_val}
    return mismatches
