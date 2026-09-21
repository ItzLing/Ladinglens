"""Attachment file -> plain text, whatever its format.

extract.py only ever sees text, so every format is flattened here: .txt is read
as is, .docx and .xlsx are parsed locally, and .pdf uses its text layer. A PDF
with no text layer is a scan, and only then does a vision model transcribe it.
"""
import hashlib
import io
from pathlib import Path

import openpyxl
from docx import Document
from pypdf import PdfReader

from app.llm_client import LLMUnavailableError, call_vision_text, vision_model_name

# A page with fewer characters than this has no usable text layer.
MIN_TEXT_CHARS = 30
# SI and BL documents are one page. The cap keeps a stray long PDF from turning
# into an unbounded number of image tokens.
MAX_OCR_PAGES = 5

# Transcriptions are model output, so they are kept on disk: a rerun (or the
# dashboard) reuses them instead of spending API quota on the same scan again.
OCR_CACHE_DIR = Path(__file__).resolve().parents[2] / "ocr_cache"

OCR_SYSTEM_PROMPT = """You transcribe scanned shipping documents.

Copy the text exactly as printed, one line per line of the document, keeping each
label on the same line as its value. Do not correct spelling, reformat numbers,
or fill in anything you cannot read -- write [illegible] in place of any text you
cannot read. Reply with the transcription only, no commentary."""
OCR_USER_PROMPT = "Transcribe this document."


class DocumentUnreadableError(ValueError):
    """The file could not be turned into text: corrupt, empty, or unsupported.

    A ValueError so run.py files it under needs_review(unreadable), the same as
    any other document the pipeline genuinely cannot read.
    """


def _read_txt(data: bytes, ocr: bool) -> str:
    return data.decode("utf-8", errors="replace")


def _page_images_png(pages) -> list[tuple[bytes, str]]:
    images = []
    for page in pages[:MAX_OCR_PAGES]:
        for image in page.images:
            picture = image.image
            if picture.mode not in ("RGB", "L"):
                picture = picture.convert("RGB")
            buffer = io.BytesIO()
            picture.save(buffer, "PNG")
            images.append((buffer.getvalue(), "image/png"))
    return images


def _ocr(pdf_bytes: bytes, images: list[tuple[bytes, str]], ocr: bool) -> str:
    # The key covers the model and prompt as well as the file, so changing either
    # can never serve a transcription made under the old settings.
    key = hashlib.sha256(
        pdf_bytes + OCR_SYSTEM_PROMPT.encode() + vision_model_name().encode()
    ).hexdigest()
    cache_file = OCR_CACHE_DIR / f"{key}.txt"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    if not ocr:
        raise DocumentUnreadableError("scanned PDF and OCR is switched off")

    text = call_vision_text(OCR_SYSTEM_PROMPT, OCR_USER_PROMPT, images)
    if text.strip():
        OCR_CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_text(text, encoding="utf-8")
    return text


def _read_pdf(data: bytes, ocr: bool) -> str:
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if len(text.strip()) >= MIN_TEXT_CHARS:
        return text

    images = _page_images_png(reader.pages)
    if not images:
        raise DocumentUnreadableError("PDF has no text layer and no page images")
    return _ocr(data, images, ocr)


def _read_docx(data: bytes, ocr: bool) -> str:
    document = Document(io.BytesIO(data))
    lines = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells, seen = [], set()
            for cell in row.cells:
                # A merged cell appears once per column it spans.
                if id(cell._tc) in seen:
                    continue
                seen.add(id(cell._tc))
                if cell.text.strip():
                    cells.append(cell.text.strip().replace("\n", ", "))
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _format_cell(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_xlsx(data: bytes, ocr: bool) -> str:
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    lines = []
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [_format_cell(v) for v in row if v is not None and str(v).strip()]
                if cells:
                    lines.append(" | ".join(cells))
    finally:
        workbook.close()
    return "\n".join(lines)


_READERS = {
    ".txt": _read_txt,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".xlsx": _read_xlsx,
}


def read_document(inbox, path: str, ocr: bool = True) -> str:
    """Return the text of an attachment.

    `ocr=False` never calls the API: a scanned PDF then only succeeds if its
    transcription is already cached, and otherwise raises DocumentUnreadableError.

    Raises DocumentUnreadableError if the file is corrupt, empty or an
    unsupported type, and LLMUnavailableError if transcription failed on the API
    side -- which says nothing about the document itself.
    """
    suffix = Path(path).suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        raise DocumentUnreadableError(f"unsupported file type: {suffix or 'none'}")

    data = inbox.read_bytes(path)
    try:
        text = reader(data, ocr)
    except (DocumentUnreadableError, LLMUnavailableError):
        raise
    except Exception as exc:
        # pypdf, python-docx and openpyxl each raise their own exception types
        # for a damaged file, so catch them here, at the parser boundary only.
        raise DocumentUnreadableError(f"could not parse {suffix} file: {exc}") from exc

    if not text.strip():
        raise DocumentUnreadableError(f"{suffix} file contains no text")
    return text
