"""FastAPI app exposing POST /run."""
import json
import sys
import threading
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from app.paths import DATA_DIR, ROOT_DIR, inbox_source, results_file

sys.path.insert(0, str(DATA_DIR))

load_dotenv(ROOT_DIR / ".env")

from loader import Inbox  # noqa: E402

from app.pipeline.run import run_pipeline  # noqa: E402

app = FastAPI(title="Ladinglens")

# A run takes far longer than a polling interval, so a scheduler will try to
# start a second one on top of the first. Two runs would append to the same
# checkpoint and race on output.json, so the second is refused rather than
# allowed to corrupt the first. In-process rather than a lock file, which would
# survive a crash and wedge every later run.
_run_lock = threading.Lock()


@app.get("/status")
def status():
    """Whether a run is in progress, and what the last one produced."""
    checkpoint = results_file("results.jsonl")
    processed = 0
    if checkpoint.exists():
        processed = sum(1 for line in checkpoint.read_text().splitlines() if line.strip())
    return {
        "running": _run_lock.locked(),
        "checkpoint_records": processed,
        "output_written": results_file("output.json").exists(),
    }


@app.post("/run")
def run(
    limit: Optional[int] = Query(None, gt=0, description="Process only the first N emails"),
    resume: bool = Query(False, description="Continue from the checkpoint instead of starting over"),
):
    """Run the pipeline, writing output.json and classify_cache.json into results/.

    Reads INBOX_SOURCE from the environment: a folder holding inbox/ and
    attachments/ (defaults to data/) or an http(s) URL if using the hackathon's
    Docker dataset server.

    `limit` processes a subset, for iterating on prompts without spending a
    full run's quota. Those results land in output.sample.json instead, so a
    partial run can never overwrite a full baseline.

    Results stream to results/results.jsonl as they complete. `resume` picks that file
    back up rather than re-spending quota on emails already done -- it defaults
    to off, so a prompt change doesn't silently reuse stale verdicts.
    """
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a run is already in progress")
    try:
        return _do_run(limit, resume)
    finally:
        _run_lock.release()


def _do_run(limit: Optional[int], resume: bool) -> dict:
    inbox = Inbox(inbox_source())

    suffix = ".sample" if limit else ""
    checkpoint_path = results_file(f"results{suffix}.jsonl")
    submission, classify_records = run_pipeline(
        inbox, limit=limit, checkpoint_path=checkpoint_path, resume=resume
    )

    output_path = results_file(f"output{suffix}.json")
    output_path.write_text(json.dumps(submission, indent=2))

    cache_path = results_file(f"classify_cache{suffix}.json")
    cache_path.write_text(json.dumps(classify_records, indent=2))

    return {
        "emails_processed": len(submission),
        "output_path": str(output_path),
        "classify_cache_path": str(cache_path),
        "checkpoint_path": str(checkpoint_path),
    }
