"""Re-apply the comparison rules to a finished run, without calling the API.

Stage 3 is deterministic, so a change to compare.py does not need the documents
read again -- the per-field SI/BL values are already in results.jsonl. This
re-runs the current rules over them and rewrites output.json, classify_cache.json
and the checkpoint.

    python scripts/recompare.py            # rewrite in place
    python scripts/recompare.py --dry-run  # report what would change

Only valid when the change *relaxes* comparison (fewer mismatches). A stricter
rule could flag fields that were equal at run time, and those are not recorded --
re-run the pipeline for that.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.paths import results_file  # noqa: E402
from app.pipeline.compare import _PARTY_FIELDS, _normalize, _same_party  # noqa: E402

SUBMISSION_KEYS = ("category", "status", "review_reason", "defect_fields", "has_defect")


def still_differs(field: str, pair: dict) -> bool:
    si, bl = _normalize(field, pair.get("si")), _normalize(field, pair.get("bl"))
    if si == bl:
        return False
    if field in _PARTY_FIELDS and _same_party(si, bl):
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    checkpoint = results_file("results.jsonl")
    records = [json.loads(l) for l in checkpoint.read_text().splitlines() if l.strip()]

    changed = 0
    for record in records:
        before = dict(record.get("mismatches") or {})
        if not before:
            continue
        after = {f: v for f, v in before.items() if still_differs(f, v)}
        if set(after) == set(before):
            continue
        changed += 1
        record["mismatches"] = after
        record["defect_fields"] = list(after)
        record["has_defect"] = bool(after)
        if record["status"] == "MISMATCH" and not after:
            record["status"] = "OK"
        print(f"  {record['email_id']}: {sorted(before)} -> {sorted(after) or 'no mismatch'}")

    print(f"\n{changed} of {len(records)} emails changed")
    if args.dry_run:
        print("dry run -- nothing written")
        return 0

    submission = {r["email_id"]: {k: r[k] for k in SUBMISSION_KEYS} for r in records}
    cache = {
        r["email_id"]: {"confidence": r.get("confidence"), **{k: r[k] for k in SUBMISSION_KEYS}}
        for r in records
    }
    results_file("output.json").write_text(json.dumps(submission, indent=2))
    results_file("classify_cache.json").write_text(json.dumps(cache, indent=2))
    checkpoint.write_text("".join(json.dumps(r) + "\n" for r in records))
    print(f"rewrote output.json, classify_cache.json, results.jsonl in {results_file('').parent.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
