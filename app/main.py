"""FastAPI app: POST /run, the read-only /api, and the web UI."""
import json
import sys
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, run_state
from app.paths import DATA_DIR, ROOT_DIR, inbox_source, results_file

sys.path.insert(0, str(DATA_DIR))

load_dotenv(ROOT_DIR / ".env")

from loader import Inbox  # noqa: E402

from app.api import router as api_router  # noqa: E402
from app.pipeline.run import run_pipeline  # noqa: E402
from app.store import FileCheckpoint, checkpoint_file, get_store  # noqa: E402

WEB_DIR = ROOT_DIR / "web"
NO_CACHE = {"Cache-Control": "no-cache"}


class RevalidatingStaticFiles(StaticFiles):
    """Static files the browser re-checks on every load (a cheap 304 when unchanged).

    Without this a browser can keep serving an old copy of a script after the UI
    has been updated.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response

app = FastAPI(title="Ladinglens", version=__version__)
app.include_router(api_router)


@app.get("/status")
def status():
    """Whether a run is in progress, and what the last one produced."""
    processed = len(FileCheckpoint(checkpoint_file("full")).records())
    return {
        "running": run_state.lock.locked(),
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

    Results stream to results/results.jsonl as they complete, and are copied into
    MongoDB when MONGODB_URI is set. `resume` picks that file back up rather than
    re-spending quota on emails already done -- it defaults to off, so a prompt
    change doesn't silently reuse stale verdicts.
    """
    if not run_state.lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a run is already in progress")
    try:
        return _do_run(limit, resume)
    finally:
        run_state.end()
        run_state.lock.release()


def _do_run(limit: Optional[int], resume: bool) -> dict:
    inbox = Inbox(inbox_source())
    store = get_store()

    scope = "sample" if limit else "full"
    available = len(inbox.emails())
    run_state.begin(scope, available if limit is None else min(limit, available))

    run_id = store.start_run(scope, limit, resume)
    submission, classify_records = run_pipeline(
        inbox, limit=limit, checkpoint=store.checkpoint(scope), resume=resume
    )
    counts: dict = {}
    for entry in submission.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    store.finish_run(run_id, counts)

    suffix = ".sample" if limit else ""
    output_path = results_file(f"output{suffix}.json")
    output_path.write_text(json.dumps(submission, indent=2))

    cache_path = results_file(f"classify_cache{suffix}.json")
    cache_path.write_text(json.dumps(classify_records, indent=2))

    return {
        "emails_processed": len(submission),
        "output_path": str(output_path),
        "classify_cache_path": str(cache_path),
        "checkpoint_path": str(checkpoint_file(scope)),
        "storage": store.backend,
        "storage_error": store.error,
    }


# The UI. Only index.html, css/ and js/ are served, not the rest of web/.
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)


app.mount("/css", RevalidatingStaticFiles(directory=WEB_DIR / "css", check_dir=False), name="css")
app.mount("/js", RevalidatingStaticFiles(directory=WEB_DIR / "js", check_dir=False), name="js")
