"""Compare a run's verdicts with another run's, on the emails that have documents.

The default is this run (results/claude-llm/results.jsonl) against web/report.json, the earlier
full run from a different model. Agreeing on verdict, defect fields and review reason for an
email is strong evidence that both read its documents the same way. A disagreement means one of
the two got it wrong, and is worth a look.

    python reference/claude-as-llm/crosscheck.py
    python reference/claude-as-llm/crosscheck.py --mine results/results.jsonl --other web/report.json
"""
import argparse
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--mine", type=Path, default=ROOT / "results" / "claude-llm" / "results.jsonl")
parser.add_argument("--other", type=Path, default=ROOT / "web" / "report.json")
args = parser.parse_args()

mine = {}
for line in args.mine.read_text(encoding="utf-8").splitlines():
    if line.strip():
        record = json.loads(line)
        mine[record["email_id"]] = record
other = {e["email_id"]: e for e in json.loads(args.other.read_text(encoding="utf-8"))["emails"]}

with_documents = set()
for path in glob.glob(str(ROOT / "data" / "inbox" / "*.json")):
    email = json.loads(Path(path).read_text(encoding="utf-8"))
    if email.get("attachments"):
        with_documents.add(email["email_id"])


def verdict(record):
    return (record["status"], tuple(sorted(record.get("defect_fields") or [])), record.get("review_reason"))


agree = 0
differences = []
for email_id in sorted(with_documents):
    if email_id in mine and email_id in other:
        if verdict(mine[email_id]) == verdict(other[email_id]):
            agree += 1
        else:
            differences.append((email_id, verdict(mine[email_id]), verdict(other[email_id])))

print(f"emails with documents in both runs: {agree + len(differences)}")
print(f"identical verdict, defect fields and reason: {agree}")
print(f"differences: {len(differences)}")
for email_id, a, b in differences:
    print(f"  {email_id}\n    this run: {a}\n    other:    {b}")
