"""Build web/report.json, the static data the dashboard reads.

Joins results/results.jsonl (verdicts + per-field SI/BL mismatches) with the inbox
records (subject, sender) and the attachment text, so the review UI can show the
source evidence the brief asks for without calling an API.

    python web/build_report.py            # the latest full run
    python web/build_report.py --sample   # the latest limited run (POST /run?limit=N)

report.json stays in web/ rather than results/ because the dashboard is a static
page served from web/ and fetches it from there.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from dotenv import load_dotenv  # noqa: E402

# .env supplies INBOX_SOURCE (where the emails are) and TESSERACT_CMD (to read scans).
load_dotenv(ROOT / ".env")

from loader import Inbox  # noqa: E402

from app.paths import inbox_source, results_file  # noqa: E402
from app.pipeline.read_document import read_document  # noqa: E402

OUT = ROOT / "web" / "report.json"
# Attachment text is shipped so reviewers can check a flagged field against the
# document. Capped because the whole report is served as one static file.
MAX_DOC_CHARS = 4000


def load_results(checkpoint: Path) -> dict:
    """Latest record per email, preferring a real verdict over a failed attempt."""
    records: dict[str, dict] = {}
    for line in checkpoint.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        prior = records.get(record["email_id"])
        if prior and prior.get("review_reason") != "processing_error":
            if record.get("review_reason") == "processing_error":
                continue
        records[record["email_id"]] = record
    return records


def main(sample: bool = False) -> None:
    checkpoint = results_file("results.sample.jsonl" if sample else "results.jsonl")
    if not checkpoint.exists():
        hint = "POST /run?limit=N" if sample else "POST /run"
        sys.exit(f"{checkpoint.relative_to(ROOT)} not found -- run the pipeline first ({hint})")

    results = load_results(checkpoint)
    failed = sum(1 for r in results.values() if r.get("review_reason") == "processing_error")
    if failed:
        print(
            f"WARNING: {failed} of {len(results)} emails are processing_error. The model API "
            "call failed (usually the daily quota), it is not a verdict on the documents. "
            "Fix the cause, then re-run with ?resume=true."
        )
    inbox = Inbox(inbox_source())

    emails = []
    for email in inbox.emails():
        email_id = email["email_id"]
        record = results.get(email_id)
        if record is None:
            continue

        entry = {
            "email_id": email_id,
            "subject": email.get("subject", ""),
            "from": email.get("from", ""),
            "body": (email.get("body", "") or "")[:600],
            "category": record["category"],
            "status": record["status"],
            "review_reason": record.get("review_reason"),
            "confidence": record.get("confidence"),
            "has_defect": record.get("has_defect", False),
            "defect_fields": record.get("defect_fields", []),
            "mismatches": record.get("mismatches", {}),
            "field_issues": record.get("field_issues", []),
            "attachments": email.get("attachments", []),
        }

        # Only comparison requests get their documents attached -- for the rest
        # there is nothing to compare and it would just inflate the payload.
        if record["category"] == "BL_COMPARISON":
            for role in ("SI", "BL"):
                match = next(
                    (a for a in email.get("attachments", []) if f"_{role}" in a), None
                )
                if match:
                    try:
                        # Never spends API calls: a scan is read by local OCR, and
                        # is simply left out if Tesseract is not installed.
                        text = read_document(inbox, match)
                        entry[f"{role.lower()}_text"] = text[:MAX_DOC_CHARS]
                    except (ValueError, OSError):
                        pass
        emails.append(entry)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "total": len(emails),
            "categories": dict(Counter(e["category"] for e in emails)),
            "statuses": dict(Counter(e["status"] for e in emails)),
            "review_reasons": dict(
                Counter(e["review_reason"] for e in emails if e["review_reason"])
            ),
            "defects": sum(1 for e in emails if e["has_defect"]),
        },
        "emails": emails,
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.relative_to(ROOT)}  {len(emails)} emails  {size_kb:.0f} KB")
    print("summary:", json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build web/report.json from a run's results.")
    parser.add_argument("--sample", action="store_true", help="use the limited run (results.sample.jsonl)")
    main(sample=parser.parse_args().sample)
