"""Python OCR with per-word confidence, and keyword lookup of the 7 fields.

Tesseract reports a confidence for every word it reads. A field's confidence is
the MINIMUM over the words that make it up, not the average: one misread
character in "128,544" makes the whole number untrustworthy, and averaging would
let the other correct characters hide it.

Everything here that does not touch the Tesseract program (label matching,
confidence aggregation) is plain Python and works without it installed.
"""
import io
import os
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

_WINDOWS_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


@dataclass
class Word:
    text: str
    conf: float  # 0-100, as reported by Tesseract


@dataclass
class OcrLine:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class FieldHit:
    value: str
    confidence: float
    evidence: str  # the whole OCR line the value was read from


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    """True if pytesseract is installed AND the Tesseract program can be found.

    Set TESSERACT_CMD to the executable's path if it is not on PATH.
    """
    try:
        import pytesseract
    except ImportError:
        return False
    command = (
        os.environ.get("TESSERACT_CMD")
        or shutil.which("tesseract")
        or (_WINDOWS_DEFAULT if os.path.exists(_WINDOWS_DEFAULT) else None)
    )
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        return False
    return True


def ocr_lines(image_png: bytes) -> list[OcrLine]:
    """Run Tesseract on one page image and return its lines, word by word."""
    import pytesseract
    from PIL import Image

    # Finding the executable (TESSERACT_CMD) happens inside ocr_available(), so
    # call it here rather than relying on the caller having done so first.
    if not ocr_available():
        raise RuntimeError("Tesseract is not installed or not found (see TESSERACT_CMD)")

    data = pytesseract.image_to_data(
        Image.open(io.BytesIO(image_png)), output_type=pytesseract.Output.DICT
    )
    lines: dict[tuple, list[Word]] = {}
    for i, raw in enumerate(data["text"]):
        text = raw.strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:  # conf -1 marks a layout block, not a word
            continue
        key = (data["page_num"][i], data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(Word(text, conf))
    return [OcrLine(words) for words in lines.values()]


def field_confidence(words: list[Word]) -> float:
    """Confidence of a field: the weakest word in it."""
    return min(w.conf for w in words)


def mean_confidence(lines: list[OcrLine]) -> float:
    """Average confidence over the whole page, as a measure of scan quality."""
    confs = [w.conf for line in lines for w in line.words]
    return sum(confs) / len(confs) if confs else 0.0


# Label text (lowercased, parentheses removed) -> the field it names. Only the
# label variants seen in the dataset; anything else is left to the LLM.
_LABELS = {
    "shipper": r"shipper(/exporter)?|exporter",
    "consignee": r"consignee|to the order of",
    "notify_party": r"notify( party)?(/intermediate consignee)?",
    "port_of_loading": r"port of loading|load port|loading port|pol",
    "port_of_discharge": r"port of discharge|discharge port|pod",
    "container_count": r"total containers|containers|container count|no\. of containers( or packages)?",
    "gross_weight_kg": r"(total )?gross (weight|wt)( kgs?)?",
}
_LABEL_PATTERNS = {field: re.compile(rf"^(?:{pattern})$") for field, pattern in _LABELS.items()}


def _normalize_label(label: str) -> str:
    label = re.sub(r"\([^)]*\)", " ", label.lower())
    # Bilingual labels glue Chinese (or a broken-font box) onto the English text.
    label = re.sub(r"[^\x00-\x7f]", " ", label)
    return " ".join(label.split())


def _split_at_colon(words: list[Word]) -> Optional[tuple[str, list[Word]]]:
    """Split a "Label: value" line into (label, value words)."""
    label_parts: list[str] = []
    for i, word in enumerate(words):
        if ":" in word.text:
            head, _, tail = word.text.partition(":")
            if head:
                label_parts.append(head)
            value = ([Word(tail, word.conf)] if tail else []) + words[i + 1:]
            return " ".join(label_parts), value
        label_parts.append(word.text)
    return None


def keyword_hits(lines: list[OcrLine]) -> dict[str, FieldHit]:
    """Find the fields whose "Label: value" line is recognisable, by keyword.

    Only same-line values are handled; a label with its value on the next line,
    or a label wording not listed above, is simply not found here, and the caller
    falls back to the LLM for it.
    """
    hits: dict[str, FieldHit] = {}
    for line in lines:
        split = _split_at_colon(line.words)
        if split is None:
            continue
        label, value_words = split
        if not value_words:
            continue
        normalized = _normalize_label(label)
        for field, pattern in _LABEL_PATTERNS.items():
            if field not in hits and pattern.match(normalized):
                hits[field] = FieldHit(
                    value=" ".join(w.text for w in value_words),
                    confidence=field_confidence(value_words),
                    evidence=line.text,
                )
    return hits


def text_lines(text: str) -> list[OcrLine]:
    """Plain text as full-confidence lines, so label lookup works on it too.

    A "Label | value" row (how .xlsx and .docx tables are flattened) is read as
    "Label: value".
    """
    lines = []
    for raw in text.splitlines():
        if ":" not in raw.split("|")[0] and "|" in raw:
            raw = raw.replace("|", ":", 1)
        words = [Word(w, 100.0) for w in raw.split()]
        if words:
            lines.append(OcrLine(words))
    return lines


def label_line(lines: list[OcrLine], field: str) -> Optional[tuple[str, str]]:
    """Find the line that labels `field`, even if its value is blank or garbage.

    Returns (the raw value as printed, the whole line), or None if no line carries
    a recognisable label for the field. Used to cross-check what an LLM reported
    against what the document actually says, and as evidence for a reviewer.
    """
    pattern = _LABEL_PATTERNS[field]
    for line in lines:
        split = _split_at_colon(line.words)
        if split and pattern.match(_normalize_label(split[0])):
            return " ".join(w.text for w in split[1]), line.text
    return None
