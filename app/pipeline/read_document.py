"""Attachment file -> text, or page images when there is no text to read.

Step 1 of the extraction ladder. .txt, .docx and .xlsx are parsed locally and a
PDF uses its text layer. A PDF whose text layer is empty or near-empty is a scan,
and an image file (jpg/png/tiff) is one by definition: for those the page images
are returned and extract.py sends them through OCR.
"""
import io
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from docx import Document
from pypdf import PdfReader

from app.pipeline.ocr import ocr_available, ocr_lines

# A PDF with fewer characters than this has no usable text layer.
MIN_TEXT_CHARS = 30
# SI and BL documents are one page. The cap keeps a stray long file from turning
# into an unbounded amount of OCR work and image tokens.
MAX_OCR_PAGES = 5

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


class DocumentUnreadableError(ValueError):
    """The file could not be turned into text or images: corrupt, empty, or unsupported.

    A ValueError so run.py files it under needs_review(unreadable), the same as
    any other document the pipeline genuinely cannot read.
    """


@dataclass
class LoadedDocument:
    path: str
    text: str = ""
    # (PNG bytes, mime type) per page. Present only when there is no usable text.
    images: list[tuple[bytes, str]] = field(default_factory=list)

    @property
    def scanned(self) -> bool:
        return bool(self.images)


def _read_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _read_docx(data: bytes) -> str:
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


def _read_xlsx(data: bytes) -> str:
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


_TEXT_READERS = {".txt": _read_txt, ".docx": _read_docx, ".xlsx": _read_xlsx}


def _to_png(picture) -> tuple[bytes, str]:
    if picture.mode not in ("RGB", "L"):
        picture = picture.convert("RGB")
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return buffer.getvalue(), "image/png"


def _load_pdf(path: str, data: bytes) -> LoadedDocument:
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if len(text.strip()) >= MIN_TEXT_CHARS:
        return LoadedDocument(path, text=text)

    images = [
        _to_png(image.image)
        for page in reader.pages[:MAX_OCR_PAGES]
        for image in page.images
    ]
    if not images:
        raise DocumentUnreadableError("PDF has no text layer and no page images")
    return LoadedDocument(path, images=images)


def _load_image(path: str, data: bytes) -> LoadedDocument:
    from PIL import Image, ImageSequence

    picture = Image.open(io.BytesIO(data))
    frames = ImageSequence.Iterator(picture)  # a multi-page TIFF has several
    images = [_to_png(frame.copy()) for _, frame in zip(range(MAX_OCR_PAGES), frames)]
    return LoadedDocument(path, images=images)


def load_document(inbox, path: str) -> LoadedDocument:
    """Load an attachment as text, or as page images if it has no usable text.

    Raises DocumentUnreadableError if the file is corrupt, empty or an
    unsupported type.
    """
    suffix = Path(path).suffix.lower()
    if suffix not in _TEXT_READERS and suffix != ".pdf" and suffix not in IMAGE_SUFFIXES:
        raise DocumentUnreadableError(f"unsupported file type: {suffix or 'none'}")

    data = inbox.read_bytes(path)
    try:
        if suffix in IMAGE_SUFFIXES:
            document = _load_image(path, data)
        elif suffix == ".pdf":
            document = _load_pdf(path, data)
        else:
            document = LoadedDocument(path, text=_TEXT_READERS[suffix](data))
    except DocumentUnreadableError:
        raise
    except Exception as exc:
        # pypdf, python-docx, openpyxl and Pillow each raise their own exception
        # types for a damaged file, so catch them here, at the parser boundary only.
        raise DocumentUnreadableError(f"could not parse {suffix} file: {exc}") from exc

    if not document.text.strip() and not document.images:
        raise DocumentUnreadableError(f"{suffix} file contains no text")
    return document


def read_document(inbox, path: str) -> str:
    """Return the text of an attachment, running local OCR on a scan.

    For showing a document to a reviewer. Never calls an API: OCR is Tesseract on
    this machine, and a scan raises DocumentUnreadableError if it is not installed.
    """
    document = load_document(inbox, path)
    if not document.scanned:
        return document.text
    if not ocr_available():
        raise DocumentUnreadableError("scanned document and no OCR engine is installed")
    return "\n".join(
        line.text for image, _ in document.images for line in ocr_lines(image)
    )
