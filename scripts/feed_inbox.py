"""Drip emails into a staging folder so the pipeline has new work to find.

The dataset is a fixed set of files, so a poller finds nothing after its first
pass. This copies emails from the real dataset into a folder the pipeline
watches, a few at a time, so arrivals happen for real -- no simulation inside
the app, and no code path that only exists for a demo.

    python scripts/feed_inbox.py --reset            # empty the staging folder
    python scripts/feed_inbox.py --batch 5          # drop 5 in, then exit
    python scripts/feed_inbox.py --batch 3 --every 60   # 3 every 60s until done

Point the pipeline at it (in .env), then run the poller alongside:

    INBOX_SOURCE=data/live
    python scripts/poll.py --interval 60
"""
import argparse
import json
import random
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "data_v2"
STAGING = ROOT / "data" / "live"


def staged_ids() -> set[str]:
    inbox = STAGING / "inbox"
    return {p.stem for p in inbox.glob("email_*.json")} if inbox.is_dir() else set()


def available() -> list[Path]:
    files = sorted((SOURCE / "inbox").glob("email_*.json"))
    if not files:
        sys.exit(f"No dataset at {SOURCE}. Unzip the bundle there first.")
    return files


def deliver(record_path: Path) -> str:
    """Copy one email in, attachments first.

    Order matters: an email whose documents have not landed yet would be read as
    missing_attachment and banked as a verdict, which is not what we are
    demonstrating.
    """
    record = json.loads(record_path.read_text(encoding="utf-8"))
    for relative in record.get("attachments", []):
        source = SOURCE / relative
        if not source.exists():
            continue
        target = STAGING / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    target = STAGING / "inbox" / record_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(record_path, target)          # the JSON lands last
    return record["email_id"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=int, default=5, help="emails per delivery")
    ap.add_argument("--every", type=int, help="seconds between deliveries; omit for one batch")
    ap.add_argument("--reset", action="store_true", help="empty the staging folder and exit")
    ap.add_argument("--shuffle", action="store_true", help="deliver in random order")
    args = ap.parse_args()

    if args.reset:
        if STAGING.exists():
            shutil.rmtree(STAGING)
        (STAGING / "inbox").mkdir(parents=True)
        (STAGING / "attachments").mkdir(parents=True)
        print(f"emptied {STAGING.relative_to(ROOT)}")
        return

    pool = available()
    if args.shuffle:
        random.shuffle(pool)

    while True:
        done = staged_ids()
        pending = [p for p in pool if p.stem not in done]
        if not pending:
            print(f"all {len(pool)} emails delivered")
            return

        batch = pending[: args.batch]
        for record_path in batch:
            print(f"  delivered {deliver(record_path)}")
        print(f"{len(done) + len(batch)}/{len(pool)} in {STAGING.relative_to(ROOT)}")

        if args.every is None:
            return
        try:
            time.sleep(args.every)
        except KeyboardInterrupt:
            print("stopped")
            return


if __name__ == "__main__":
    main()
