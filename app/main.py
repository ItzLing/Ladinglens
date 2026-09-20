"""FastAPI app exposing POST /run."""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
sys.path.insert(0, str(DATA_DIR))

load_dotenv(ROOT_DIR / ".env")

from loader import Inbox  # noqa: E402

from app.pipeline.run import run_pipeline  # noqa: E402

app = FastAPI(title="Ladinglens")


@app.post("/run")
def run():
    """Run the full pipeline, writing output.json and classify_cache.json.

    Reads INBOX_SOURCE from the environment: a local folder (defaults to
    data/) or an http(s) URL if using the hackathon's Docker dataset server.
    """
    source = os.environ.get("INBOX_SOURCE", str(DATA_DIR))
    inbox = Inbox(source)
    submission, classify_records = run_pipeline(inbox)

    output_path = ROOT_DIR / "output.json"
    output_path.write_text(json.dumps(submission, indent=2))

    cache_path = ROOT_DIR / "classify_cache.json"
    cache_path.write_text(json.dumps(classify_records, indent=2))

    return {
        "emails_processed": len(submission),
        "output_path": str(output_path),
        "classify_cache_path": str(cache_path),
    }
