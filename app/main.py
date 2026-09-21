"""FastAPI app: POST /run, the read-only /api, and the web UI."""
import json
import sys
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import __version__, run_state
from app.paths import DATA_DIR, ROOT_DIR, inbox_source, results_file

sys.path.insert(0, str(DATA_DIR))

load_dotenv(ROOT_DIR / ".env")

from loader import Inbox  # noqa: E402

from app.api import router as api_router  # noqa: E402
from app.llm_client import LLMUnavailableError  # noqa: E402
from app.pipeline.classify import classify_email  # noqa: E402
from app.pipeline.compare import compare_fields  # noqa: E402
from app.pipeline.extract import extract_fields  # noqa: E402
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
    stopped = run_state.stop_requested()
    counts: dict = {}
    for entry in submission.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    store.finish_run(run_id, counts)

    if stopped:
        # Every email finished so far is already in the checkpoint. Writing the
        # partial submission would replace a full output.json with a fragment, so
        # leave the outputs alone; resume=true carries on from the checkpoint.
        return {
            "stopped": True,
            "emails_processed": len(submission),
            "checkpoint_path": str(checkpoint_file(scope)),
            "storage": store.backend,
            "storage_error": store.error,
        }

    suffix = ".sample" if limit else ""
    output_path = results_file(f"output{suffix}.json")
    output_path.write_text(json.dumps(submission, indent=2))

    cache_path = results_file(f"classify_cache{suffix}.json")
    cache_path.write_text(json.dumps(classify_records, indent=2))

    return {
        "stopped": False,
        "emails_processed": len(submission),
        "output_path": str(output_path),
        "classify_cache_path": str(cache_path),
        "checkpoint_path": str(checkpoint_file(scope)),
        "storage": store.backend,
        "storage_error": store.error,
    }


class ProcessRequest(BaseModel):
    """One email and its two documents, supplied inline rather than read from disk."""

    subject: str = ""
    sender: str = ""
    body: str = ""
    si_text: Optional[str] = None
    bl_text: Optional[str] = None


@app.post("/process")
def process(payload: ProcessRequest):
    """Classify one email and compare its documents, with nothing read from disk.

    /run needs the dataset on the filesystem; this takes everything in the
    request instead, so a deployed instance needs no inbox mounted and no
    organizer material baked into its image.

    Comparison runs whenever both documents are supplied, regardless of the
    predicted category -- a caller who pasted an SI and a BL wants the diff,
    not a refusal because classification read the covering note differently.
    """
    result: dict = {"category": None, "confidence": None}

    if payload.subject or payload.body:
        try:
            category, confidence = classify_email(
                {
                    "subject": payload.subject,
                    "from": payload.sender,
                    "body": payload.body,
                    # Documents were supplied inline, so name them the way the
                    # dataset does -- attachments are the strongest signal the
                    # classifier has for a comparison request.
                    "attachments": (
                        ["inline_SI.txt", "inline_BL.txt"]
                        if payload.si_text and payload.bl_text
                        else []
                    ),
                }
            )
            result["category"] = category.value
            result["confidence"] = confidence
        except (LLMUnavailableError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=502, detail=f"classification failed: {exc}")

    if not (payload.si_text and payload.bl_text):
        result["status"] = "NEEDS_REVIEW" if result["category"] else "OK"
        result["review_reason"] = "missing_attachment"
        return result

    try:
        si = extract_fields(payload.si_text)
        bl = extract_fields(payload.bl_text)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=502, detail=f"extraction unavailable: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"could not read a document: {exc}")

    mismatches = compare_fields(si, bl)
    result.update(
        si_fields=si.model_dump(),
        bl_fields=bl.model_dump(),
        mismatches=mismatches,
        defect_fields=list(mismatches),
        has_defect=bool(mismatches),
        status="MISMATCH" if mismatches else "OK",
        review_reason=None,
    )
    return result


# The UI. Only index.html, css/ and js/ are served, not the rest of web/.
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)


app.mount("/css", RevalidatingStaticFiles(directory=WEB_DIR / "css", check_dir=False), name="css")
app.mount("/js", RevalidatingStaticFiles(directory=WEB_DIR / "js", check_dir=False), name="js")
