"""FastAPI app exposing POST /run."""
import json
import os
import sys
from pathlib import Path

from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
sys.path.insert(0, str(DATA_DIR))

load_dotenv(ROOT_DIR / ".env")

from loader import Inbox  # noqa: E402

from app.pipeline.run import run_pipeline  # noqa: E402

app = FastAPI(title="Ladinglens")


@app.post("/run")
def run(
    limit: Optional[int] = Query(None, gt=0, description="Process only the first N emails"),
    resume: bool = Query(False, description="Continue from the checkpoint instead of starting over"),
):
    """Run the pipeline, writing output.json and classify_cache.json.

    Reads INBOX_SOURCE from the environment: a local folder (defaults to
    data/) or an http(s) URL if using the hackathon's Docker dataset server.

    `limit` processes a subset, for iterating on prompts without spending a
    full run's quota. Those results land in output.sample.json instead, so a
    partial run can never overwrite a full baseline.

    Results stream to results.jsonl as they complete. `resume` picks that file
    back up rather than re-spending quota on emails already done -- it defaults
    to off, so a prompt change doesn't silently reuse stale verdicts.
    """
    source = os.environ.get("INBOX_SOURCE", str(DATA_DIR))
    inbox = Inbox(source)

    suffix = ".sample" if limit else ""
    checkpoint_path = ROOT_DIR / f"results{suffix}.jsonl"
    submission, classify_records = run_pipeline(
        inbox, limit=limit, checkpoint_path=checkpoint_path, resume=resume
    )

    output_path = ROOT_DIR / f"output{suffix}.json"
    output_path.write_text(json.dumps(submission, indent=2))

    cache_path = ROOT_DIR / f"classify_cache{suffix}.json"
    cache_path.write_text(json.dumps(classify_records, indent=2))

    return {
        "emails_processed": len(submission),
        "output_path": str(output_path),
        "classify_cache_path": str(cache_path),
        "checkpoint_path": str(checkpoint_path),
    }
