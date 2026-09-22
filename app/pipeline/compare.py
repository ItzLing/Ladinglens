"""Stage 3: SI vs BL -> mismatches.

Deterministic, no LLM call here -- once both documents are normalized to the
same schema by extract.py, the diff itself should be plain, auditable Python.
"""
import re
from typing import Optional

from app.pipeline.validate import _COUNT, _WEIGHT
from app.schema import ShipmentFields

# A comma between digit groups ("243,588") is a thousands separator, not text.
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# Address parts are joined by ",", ";" or "|" depending on the file format the
# document came in, so none of them can count as a difference.
_SEPARATORS = re.compile(r"[,;|]")
_WEIGHT_UNIT = re.compile(r"\bKGS?\b")
# One document often writes a party as name + full address while the other gives
# the name alone. That is the same party described at two levels of detail, not a
# discrepancy. Restricted to these three fields on purpose: applying it to a
# number would let "3" match "30" and hide a real container-count defect.
_PARTY_FIELDS = frozenset({"shipper", "consignee", "notify_party"})
# These two fields are quantities, not text: "6 x 40'HC" and "6" are the same
# container count, and "131,058.00 KG" and "131058 KG" are the same weight. The
# regexes are the same ones validate.py uses to accept the value in the first
# place, so a value that passed validation always parses here too.
_NUMERIC_PATTERNS = {"container_count": _COUNT, "gross_weight_kg": _WEIGHT}


def _numeric(field: str, value: Optional[str]) -> Optional[float]:
    pattern = _NUMERIC_PATTERNS.get(field)
    if pattern is None or value is None:
        return None
    match = pattern.match(value.strip())
    if match is None:
        return None
    return float(match.group("number").replace(",", ""))


def _normalize(field: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = _THOUSANDS_COMMA.sub("", value.upper())
    text = _SEPARATORS.sub(" ", text)
    if field == "gross_weight_kg":
        text = _WEIGHT_UNIT.sub("", text)
    return " ".join(text.split())


def _same_party(left: Optional[str], right: Optional[str]) -> bool:
    """True when one value is the other plus extra detail (usually an address)."""
    if not left or not right:
        return False
    return left.startswith(right) or right.startswith(left)


def compare_fields(si: ShipmentFields, bl: ShipmentFields) -> dict[str, dict[str, Optional[str]]]:
    """Diff two ShipmentFields field by field, after light normalization.

    Returns {field_name: {"si": value, "bl": value}} for every field whose
    normalized values differ. Normalizing only removes formatting: case,
    spacing, address separators, thousands commas and the "KG" unit on weight.
    Words and digits are never altered, so a real difference still shows.

    A party field also matches when one side is the other plus an address -- see
    _same_party. container_count and gross_weight_kg are compared as the number
    they represent, not as normalized text, so "6 x 40'HC" matches "6" and
    "131,058.00 KG" matches "131058 KG" -- see _numeric.
    """
    mismatches: dict[str, dict[str, Optional[str]]] = {}
    for field in ShipmentFields.model_fields:
        si_val = getattr(si, field)
        bl_val = getattr(bl, field)
        if field in _NUMERIC_PATTERNS:
            si_num = _numeric(field, si_val)
            bl_num = _numeric(field, bl_val)
            if si_num is not None and bl_num is not None:
                if si_num != bl_num:
                    mismatches[field] = {"si": si_val, "bl": bl_val}
                continue
        si_norm = _normalize(field, si_val)
        bl_norm = _normalize(field, bl_val)
        if si_norm == bl_norm:
            continue
        if field in _PARTY_FIELDS and _same_party(si_norm, bl_norm):
            continue
        mismatches[field] = {"si": si_val, "bl": bl_val}
    return mismatches
