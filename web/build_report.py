"""Build web/report.json, the data behind the read-only demo (no server needed).

It asks the API's own functions for the report and for every case, so the demo
shows exactly what the running app shows, from the same store (MongoDB if it is
configured, otherwise the files in results/). Scanned pages become "this is a scan"
in the demo, since page images need the running app.

    python web/build_report.py            # the full run, else the latest limited run
    python web/build_report.py --sample   # the latest limited run (POST /run?limit=N)

report.json stays in web/ rather than results/ because the static page is served
from web/ and fetches it from there.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

# .env supplies INBOX_SOURCE, MONGODB_URI and TESSERACT_CMD.
load_dotenv(ROOT / ".env")

from app import api  # noqa: E402

OUT = ROOT / "web" / "report.json"
# Document text is shipped so a flagged field can be checked against the source.
# Capped because the whole report is served as one static file.
MAX_DOC_CHARS = 4000


def build(sample: bool = False) -> dict:
    scope = "sample" if sample else "auto"
    report = api.report(scope=scope)
    if not report["emails"]:
        sys.exit("No results found. Run the pipeline first (POST /run).")

    cases = {}
    for row in report["emails"]:
        case = api.email_case(row["email_id"], scope=report["scope"])
        for document in case["documents"]:
            if document.get("text"):
                document["text"] = document["text"][:MAX_DOC_CHARS]
        cases[row["email_id"]] = case
    return {**report, "cases": cases}


def main(sample: bool = False) -> None:
    report = build(sample)
    failed = report["summary"]["failed"]
    if failed:
        print(
            f"WARNING: {failed} of {report['summary']['total']} emails are processing_error. The "
            "model API call failed (usually the daily quota), it is not a verdict on the "
            "documents. Fix the cause, then re-run with ?resume=true."
        )
    OUT.write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  {report['summary']['total']} emails  "
          f"{OUT.stat().st_size / 1024:.0f} KB  (scope {report['scope']}, from {report['source']})")
    print("summary:", json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build web/report.json from a run's results.")
    parser.add_argument("--sample", action="store_true", help="use the limited run")
    main(sample=parser.parse_args().sample)
