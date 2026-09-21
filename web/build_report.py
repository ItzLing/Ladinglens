"""Build web/report.json, the static data the frontend reads.

Joins results.jsonl (verdicts + per-field SI/BL mismatches) with the inbox
records (subject, sender) and the attachment text, so the review UI can show the
source evidence the brief asks for without calling an API.

    python web/build_report.py
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))

from loader import Inbox  # noqa: E402

CHECKPOINT = ROOT / "results.jsonl"
OUT = ROOT / "web" / "report.json"
INBOX_SOURCE = "data/data_v2"
# Attachment text is shipped so reviewers can check a flagged field against the
# document. Capped because the whole report is served as one static file.
MAX_DOC_CHARS = 4000


def load_results() -> dict:
    """Latest record per email, preferring a real verdict over a failed attempt."""
    records: dict[str, dict] = {}
    for line in CHECKPOINT.read_text().splitlines():
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


def main() -> None:
    inbox = Inbox(str(ROOT / INBOX_SOURCE))
    results = load_results()

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
            "attachments": email.get("attachments", []),
        }

        # Only comparison requests get their documents attached -- for the rest
        # there is nothing to compare and it would just inflate the payload.
        if record["category"] == "BL_COMPARISON":
            for role in ("SI", "BL"):
                match = next(
                    (a for a in email.get("attachments", []) if f"_{role}" in a), None
                )
                if match and match.lower().endswith(".txt"):
                    try:
                        entry[f"{role.lower()}_text"] = inbox.read_text(match)[:MAX_DOC_CHARS]
                    except OSError:
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
    main()
