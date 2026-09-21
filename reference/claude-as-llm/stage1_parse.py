"""Stage 1: parse every attachment of every email (OCR for scans, keyword parser for text).

No model is used here. For each document and each of the 7 fields it records what the parser
read, how confident it is, and whether the value passes the pipeline's own validation. The
documents where a field is missing, low-confidence or invalid are exactly the ones a model has to
be asked about; everything else is settled without one.

    python reference/claude-as-llm/stage1_parse.py    # writes results/claude-llm/parsed.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from loader import Inbox

from app.paths import inbox_source
from app.pipeline.extract import FIELD_NAMES, _min_confidence
from app.pipeline.ocr import keyword_hits, mean_confidence, ocr_available, ocr_lines, text_lines
from app.pipeline.read_document import DocumentUnreadableError, load_document
from app.pipeline.validate import validate_field

OUT = ROOT / "results" / "claude-llm" / "parsed.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
inbox = Inbox(inbox_source())
threshold = _min_confidence()
print("OCR engine available:", ocr_available(), "| min word confidence:", threshold, flush=True)

docs = {}
for email in inbox.emails():
    for path in email.get("attachments", []):
        role = "SI" if "_SI" in path else "BL" if "_BL" in path else "?"
        rec = {"email_id": email["email_id"], "role": role, "path": path}
        try:
            doc = load_document(inbox, path)
        except DocumentUnreadableError as exc:
            rec.update(kind="unreadable", error=str(exc), fields={})
            docs[path] = rec
            continue
        if doc.scanned:
            lines = [ln for image, _ in doc.images for ln in ocr_lines(image)]
            rec["kind"] = "scanned"
            rec["pages"] = len(doc.images)
            rec["page_quality"] = round(mean_confidence(lines), 1)
            rec["ocr_text"] = "\n".join(ln.text for ln in lines)
        else:
            lines = text_lines(doc.text)
            rec["kind"] = "text"
            rec["text"] = doc.text
        hits = keyword_hits(lines)
        fields = {}
        for name in FIELD_NAMES:
            hit = hits.get(name)
            if hit is None:
                fields[name] = {"status": "missing"}
                continue
            problem = validate_field(name, hit.value)
            if hit.confidence < threshold:
                status = "low_confidence"
            elif problem:
                status = "invalid"
            else:
                status = "accepted"
            fields[name] = {"status": status, "value": hit.value, "confidence": round(hit.confidence, 1), "problem": problem}
        rec["fields"] = fields
        docs[path] = rec

OUT.write_text(json.dumps(docs, indent=1), encoding="utf-8")
print("documents parsed:", len(docs), flush=True)
