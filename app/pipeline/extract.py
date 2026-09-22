"""Stage 2: SI/BL attachment -> ShipmentFields, through a fallback ladder.

Field-label normalization happens here: the SI and BL often label the same
field differently (e.g. "Port of Loading" vs "Load Port"), so the model is
asked to align by meaning, not by header text, before compare.py ever runs.

The ladder, cheapest and most trustworthy step first:

 1. Read the file's text (read_document.py). A document with text goes to an LLM
    that maps it onto the 7 fields (extract_fields).
 2. No usable text (a scanned PDF) or an image file: OCR it with Tesseract, which
    reports a confidence per word. A field's confidence is the MINIMUM of the
    words in it.
 3. A field found by keyword ("Load Port: NHAVA SHEVA") with high confidence is
    accepted with no LLM call.
 4. Low OCR confidence means characters were misread, so re-parsing that garbled
    text cannot fix it: the field goes straight to a vision LLM looking at the page
    image. Only the fields that need it are sent.
 5. High OCR confidence but no keyword match (a label we do not list) means the
    text is fine and only the wording is unfamiliar: an LLM parses the clean text.
 6. Every value from OCR or an LLM is validated (validate.py) before it is
    accepted. A value that fails is treated like low confidence.
 7. A field still unresolved is reported as a FieldIssue with its reason and
    evidence, and the email goes to a human. Nothing is guessed or dropped.
"""
import os
from typing import Optional

from app.llm_client import call_json, call_vision_json
from app.pipeline.ocr import (
    keyword_hits,
    label_line,
    mean_confidence,
    ocr_available,
    ocr_lines,
    text_lines,
)
from app.pipeline.read_document import LoadedDocument, load_document
from app.pipeline.validate import validate_field
from app.schema import ExtractionResult, FieldIssue, FieldIssueReason, ShipmentFields

SYSTEM_PROMPT = """You extract 7 shipment fields from a shipping document (an SI or a
draft Bill of Lading). The document may label a field differently than the field
name below -- match by meaning, not by header text (e.g. "Load Port", "POL", and
"Port of Loading" all mean port_of_loading).

Fields to extract:
- shipper
- consignee
- notify_party
- port_of_loading
- port_of_discharge
- container_count (keep the raw value as written, e.g. "6 x 40'HC")
- gross_weight_kg (keep the raw value as written, e.g. "131,058 KG")

If a field is not present in the document, use null for it. Respond with JSON
only, no prose, in this exact shape:
{"shipper": ..., "consignee": ..., "notify_party": ..., "port_of_loading": ...,
 "port_of_discharge": ..., "container_count": ..., "gross_weight_kg": ...}"""

VISION_SYSTEM_PROMPT = """You read one shipping document (an SI or a draft Bill of
Lading) from an image of its page and report the fields you are asked for.

Copy each value exactly as printed. Do not correct, complete or guess. If a value
is missing, cut off, or you cannot read every character of it with certainty, use
null for it. Respond with JSON only, no prose."""

_FIELD_GUIDE = {
    "shipper": "the shipper / exporter",
    "consignee": "the consignee (also written 'To the Order of')",
    "notify_party": "the notify party",
    "port_of_loading": "the port of loading (also 'Load Port', 'POL')",
    "port_of_discharge": "the port of discharge (also 'Discharge Port', 'POD')",
    "container_count": "the number of containers, as written, e.g. \"6 x 40'HC\"",
    "gross_weight_kg": "the total gross weight, as written, e.g. \"131,058 KG\"",
}

FIELD_NAMES = list(ShipmentFields.model_fields)

# Headers of the other document types this dataset's "BL" attachments sometimes
# actually are (commercial invoice, packing list, certificate of origin), instead
# of an SI or a draft BL. Checked before the extraction ladder runs, so a wrong
# attachment goes to a person as wrong_doc_type instead of missing_value.
_WRONG_DOC_MARKERS = ("COMMERCIAL INVOICE", "PACKING LIST", "CERTIFICATE OF ORIGIN")


class WrongDocTypeError(ValueError):
    """The document's own text says it is not an SI or a BL at all."""


def _wrong_doc_type(text: str) -> Optional[str]:
    upper = text.upper()
    for marker in _WRONG_DOC_MARKERS:
        if marker in upper:
            return marker
    return None

# Tesseract word confidence (0-100) below which a field is not trusted. Not yet
# calibrated against real scans -- see HANDOFF.md.
DEFAULT_OCR_MIN_CONFIDENCE = 80.0


def extract_fields(doc_text: str) -> ShipmentFields:
    """Extract the 7 shipment fields from raw SI or BL text via one LLM call."""
    result = call_json(SYSTEM_PROMPT, doc_text)
    return ShipmentFields(**result)


def _min_confidence() -> float:
    return float(os.environ.get("OCR_MIN_CONFIDENCE", DEFAULT_OCR_MIN_CONFIDENCE))


def _as_text(value) -> Optional[str]:
    """A model's reply value as clean text, or None if it gave nothing."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _snippet(text: str, value: Optional[str]) -> str:
    """The line of `text` that contains `value`, else the start of the text."""
    if value:
        for line in text.splitlines():
            if value.lower() in line.lower():
                return line.strip()[:300]
    return text.strip()[:300]


class _Resolution:
    """Accumulates the accepted fields and the unresolved ones for one document."""

    def __init__(self, path: str, document: str):
        self.path = path
        self.document = document
        self.values: dict[str, str] = {}
        self.sources: dict[str, str] = {}
        self.issues: list[FieldIssue] = []

    def accept(self, name: str, value: str, source: str) -> None:
        self.values[name] = value
        self.sources[name] = source

    def reject(self, name, reason, detail, source, value=None, evidence=None) -> None:
        self.issues.append(
            FieldIssue(
                document=self.document,
                file=self.path,
                field=name,
                reason=reason,
                detail=detail,
                source=source,
                value=value,
                evidence=evidence,
            )
        )

    def result(self) -> ExtractionResult:
        return ExtractionResult(
            file=self.path,
            fields=ShipmentFields(**self.values),
            sources=self.sources,
            issues=self.issues,
        )


def _extract_text(document: LoadedDocument, label: str) -> ExtractionResult:
    """A document with real text: LLM maps it onto the fields, then validate."""
    resolution = _Resolution(document.path, label)
    extracted = extract_fields(document.text)
    source_lines = text_lines(document.text)
    for name in FIELD_NAMES:
        value = _as_text(getattr(extracted, name))
        labelled = label_line(source_lines, name)
        evidence = labelled[1] if labelled else _snippet(document.text, value)
        if value is None:
            resolution.reject(
                name,
                FieldIssueReason.NOT_FOUND,
                "no value for this field in the document text",
                source="text",
                evidence=evidence,
            )
            continue
        problem = validate_field(name, value)
        if problem is None and labelled and labelled[0]:
            # The model may have tidied a garbage value into a plausible one
            # ("____MT" -> "MT"). Check what the document itself prints.
            raw_problem = validate_field(name, labelled[0])
            if raw_problem:
                problem = f"the document prints {labelled[0]!r}: {raw_problem}"
        if problem:
            # A text document has no page image to fall back to: the ladder ends here.
            resolution.reject(
                name,
                FieldIssueReason.INVALID_VALUE,
                f"failed validation: {problem}",
                source="text",
                value=value,
                evidence=evidence,
            )
        else:
            resolution.accept(name, value, "text")
    return resolution.result()


def _vision_extract(images: list[tuple[bytes, str]], names: list[str]) -> dict:
    """Ask the vision model for only `names`, reading them off the page image."""
    request = "Return a JSON object with exactly these keys:\n" + "\n".join(
        f"- {name}: {_FIELD_GUIDE[name]}" for name in names
    )
    reply = call_vision_json(VISION_SYSTEM_PROMPT, request, images)
    if not isinstance(reply, dict):
        raise ValueError(f"vision model did not return a JSON object: {reply!r}")
    return reply


def _extract_scanned(document: LoadedDocument, label: str) -> ExtractionResult:
    """A scan or image file: OCR, then keyword / text LLM / vision per field."""
    threshold = _min_confidence()
    resolution = _Resolution(document.path, label)

    # field -> why it could not be settled by OCR, for the reviewer's trail
    need_vision: dict[str, str] = {}
    hits: dict = {}

    if ocr_available():
        lines = [line for image, _ in document.images for line in ocr_lines(image)]
        hits = keyword_hits(lines)
        page_quality = mean_confidence(lines)
        ocr_text = "\n".join(line.text for line in lines)
        need_text: list[str] = []

        for name in FIELD_NAMES:
            hit = hits.get(name)
            if hit is None:
                if page_quality >= threshold:
                    need_text.append(name)
                else:
                    need_vision[name] = (
                        f"label not found and page OCR quality {page_quality:.0f} < {threshold:.0f}"
                    )
            elif hit.confidence < threshold:
                need_vision[name] = f"OCR confidence {hit.confidence:.0f} < {threshold:.0f}"
            else:
                problem = validate_field(name, hit.value)
                if problem:
                    need_vision[name] = f"OCR value failed validation: {problem}"
                else:
                    resolution.accept(name, hit.value, "ocr")

        if need_text:
            parsed = extract_fields(ocr_text)
            for name in need_text:
                value = _as_text(getattr(parsed, name))
                if value is None:
                    resolution.reject(
                        name,
                        FieldIssueReason.NOT_FOUND,
                        "clean OCR text has no value for this field",
                        source="ocr",
                        evidence=(label_line(lines, name) or (None, _snippet(ocr_text, None)))[1],
                    )
                    continue
                problem = validate_field(name, value)
                if problem:
                    need_vision[name] = f"LLM-parsed OCR text failed validation: {problem}"
                else:
                    resolution.accept(name, value, "ocr_llm")
    else:
        need_vision = {name: "no OCR engine available" for name in FIELD_NAMES}

    if need_vision:
        replies = _vision_extract(document.images, list(need_vision))
        for name, why in need_vision.items():
            value = _as_text(replies.get(name))
            hit = hits.get(name)
            evidence = hit.evidence if hit else None
            if value is None:
                resolution.reject(
                    name,
                    FieldIssueReason.UNREADABLE,
                    f"{why}; the vision model could not read it",
                    source="vision",
                    value=hit.value if hit else None,
                    evidence=evidence,
                )
                continue
            problem = validate_field(name, value)
            if problem:
                resolution.reject(
                    name,
                    FieldIssueReason.INVALID_VALUE,
                    f"{why}; the vision value failed validation: {problem}",
                    source="vision",
                    value=value,
                    evidence=evidence,
                )
            else:
                resolution.accept(name, value, "vision")

    return resolution.result()


def extract_document(inbox, path: str, label: str) -> ExtractionResult:
    """Run the ladder on one attachment. `label` is "SI" or "BL".

    Raises DocumentUnreadableError (a ValueError) for a file that cannot be read
    at all, and LLMUnavailableError if an API call failed -- which says nothing
    about the document.
    """
    document = load_document(inbox, path)
    if document.scanned:
        return _extract_scanned(document, label)
    marker = _wrong_doc_type(document.text)
    if marker is not None:
        raise WrongDocTypeError(
            f"{path} reads like a {marker.title()}, not an SI/BL"
        )
    return _extract_text(document, label)
