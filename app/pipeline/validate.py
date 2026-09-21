"""Format and sanity checks on an extracted field value.

Run on every value coming out of OCR or an LLM before it is accepted. A value
that fails is treated as if it had low confidence: it is not trusted, and not
silently dropped either. The limits are wide on purpose -- they exist to catch
garbage (a blank, a value in the wrong unit, a misread digit run), not to police
real shipments -- and were set from the dataset: weights 20,065-360,415 kg,
1-16 containers.
"""
import re
from typing import Optional

MIN_WEIGHT_KG = 100
MAX_WEIGHT_KG = 1_000_000
MIN_CONTAINERS = 1
MAX_CONTAINERS = 200

# What a form says when the value is not known yet. Present in the source, these
# mean "left blank", so treating them as a real port or party would be a guess.
_PLACEHOLDERS = {
    "TBA", "TBC", "TBD", "N/A", "NA", "NIL", "NONE", "UNKNOWN", "-", "--", "?",
    "TO BE ADVISED", "TO BE CONFIRMED", "TO BE DECIDED",
}

_WEIGHT = re.compile(r"^\s*(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>[A-Za-z]+)?\s*$")
_COUNT = re.compile(r"^\s*(?P<number>\d+)\b")
_LETTER = re.compile(r"[^\W\d_]")
# Anything outside letters, digits, spaces and the punctuation real names and
# addresses use. Brackets, underscores, braces and box glyphs are OCR debris.
_STRAY = re.compile(r"[^\w\s.,;:&()'\"/#|+@\-]|_")


def _check_weight(value: str) -> Optional[str]:
    match = _WEIGHT.match(value)
    if match is None:
        return "not a number"
    unit = match.group("unit")
    if unit and unit.upper() not in ("KG", "KGS"):
        return f"unit is {unit.upper()}, expected KG"
    weight = float(match.group("number").replace(",", ""))
    if not MIN_WEIGHT_KG <= weight <= MAX_WEIGHT_KG:
        return f"{weight:g} kg is outside {MIN_WEIGHT_KG:,}-{MAX_WEIGHT_KG:,}"
    return None


def _check_container_count(value: str) -> Optional[str]:
    match = _COUNT.match(value)
    if match is None:
        return "does not start with a whole number"
    count = int(match.group("number"))
    if not MIN_CONTAINERS <= count <= MAX_CONTAINERS:
        return f"{count} containers is outside {MIN_CONTAINERS}-{MAX_CONTAINERS}"
    return None


def _check_text(value: str) -> Optional[str]:
    if value.strip().upper() in _PLACEHOLDERS:
        return f"placeholder, not a real value ({value.strip()})"
    if not _LETTER.search(value):
        return "contains no letters"
    stray = sorted(set(_STRAY.findall(value)))
    if stray:
        return "stray symbols: " + " ".join(stray)
    return None


def validate_field(name: str, value: Optional[str]) -> Optional[str]:
    """Return why `value` is not acceptable for field `name`, or None if it is."""
    if value is None or not value.strip():
        return "empty"
    if name == "gross_weight_kg":
        return _check_weight(value)
    if name == "container_count":
        return _check_container_count(value)
    return _check_text(value)
