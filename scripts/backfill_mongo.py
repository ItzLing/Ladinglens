"""Push an existing run's results up to MongoDB, without re-running anything.

Results only reach MongoDB if MONGODB_URI was set while the run happened, and
resume skips emails already done -- so a run finished before the database was
configured never gets mirrored. This copies what is already in the checkpoint.

    python scripts/backfill_mongo.py                 # the full run
    python scripts/backfill_mongo.py --scope sample  # the ?limit= run
    python scripts/backfill_mongo.py --dry-run

Safe to repeat: the mirror upserts on (scope, email_id), and it will not trade a
real verdict for a later failure. Makes no API calls.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

from app.store import FileCheckpoint, checkpoint_file, get_store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", default="full", choices=("full", "sample"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = checkpoint_file(args.scope)
    if not path.exists():
        return print(f"No checkpoint at {path}. Run the pipeline first.") or 1

    records = FileCheckpoint(path).records()
    print(f"{len(records)} records in {path.name}")

    store = get_store()
    if not store.configured:
        return print("MONGODB_URI is not set -- nothing to mirror to.") or 1
    if store.error:
        return print(f"MongoDB unreachable: {store.error}") or 1

    checkpoint = store.checkpoint(args.scope)
    if checkpoint.mirror is None:
        return print("Could not open the MongoDB mirror.") or 1

    before = checkpoint.mirror.results.count_documents({"scope": args.scope})
    print(f"already in MongoDB: {before}")

    if args.dry_run:
        print(f"dry run -- would push {len(records)} records")
        return 0

    for i, record in enumerate(records.values(), start=1):
        checkpoint.mirror.append(record)
        if i % 100 == 0:
            print(f"  {i}/{len(records)}")

    after = checkpoint.mirror.results.count_documents({"scope": args.scope})
    print(f"done. MongoDB now holds {after} records for scope '{args.scope}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
