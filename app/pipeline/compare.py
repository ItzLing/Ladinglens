"""Stage 3: SI vs BL -> mismatches.

Deterministic, no LLM call here -- once both documents are normalized to the
same schema by extract.py, the diff itself should be plain, auditable Python.
"""
import re
from typing import Optional

from app.schema import ShipmentFields

# A comma between digit groups ("243,588") is a thousands separator, not text.
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# Address parts are joined by ",", ";" or "|" depending on the file format the
# document came in, so none of them can count as a difference.
_SEPARATORS = re.compile(r"[,;|]")
_WEIGHT_UNIT = re.compile(r"\bKGS?\b")


def _normalize(field: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = _THOUSANDS_COMMA.sub("", value.upper())
    text = _SEPARATORS.sub(" ", text)
    if field == "gross_weight_kg":
        text = _WEIGHT_UNIT.sub("", text)
    return " ".join(text.split())


def compare_fields(si: ShipmentFields, bl: ShipmentFields) -> dict[str, dict[str, Optional[str]]]:
    """Diff two ShipmentFields field by field, after light normalization.

    Returns {field_name: {"si": value, "bl": value}} for every field whose
    normalized values differ. Normalizing only removes formatting: case,
    spacing, address separators, thousands commas and the "KG" unit on weight.
    Words and digits are never altered, so a real difference still shows.
    """
    mismatches: dict[str, dict[str, Optional[str]]] = {}
    for field in ShipmentFields.model_fields:
        si_val = getattr(si, field)
        bl_val = getattr(bl, field)
        if _normalize(field, si_val) != _normalize(field, bl_val):
            mismatches[field] = {"si": si_val, "bl": bl_val}
    return mismatches
