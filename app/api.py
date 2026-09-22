"""Read-only JSON API for the web UI, plus retrying a single email.

    GET  /api/status                       progress, version, storage backend
    GET  /api/report                       one light row per email, and totals
    GET  /api/emails/{id}                  the full case
    GET  /api/emails/{id}/documents/{SI|BL}/pages/{n}.png
    POST /api/emails/{id}/retry            run the pipeline again for one email
    GET  /api/db/status                    the MongoDB explorer
    GET  /api/db/collections/{name}
    POST /api/emails/{id}/correction       save a reviewer's corrected field values
    DELETE /api/emails/{id}/correction     clear a saved correction
    POST /api/emails/{id}/delegate         hand a case to a named person
    DELETE /api/emails/{id}/delegate       take a delegated case back

A correction or delegation is appended to the same checkpoint as any other result,
under a "correction" / "delegation" key on the record, so it survives in
results.jsonl and is picked up by report.json / output.json on the next build.
Nothing here changes a verdict except the retry, which re-runs the pipeline.
"""
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app import __version__, run_state
from app.paths import DATA_DIR, inbox_source

sys.path.insert(0, str(DATA_DIR))

from loader import Inbox  # noqa: E402

from app.pipeline.read_document import DocumentUnreadableError, load_document  # noqa: E402
from app.pipeline.run import _record, process_email  # noqa: E402
from app.store import FileCheckpoint, SCOPES, checkpoint_file, get_store, is_failed  # noqa: E402

router = APIRouter(prefix="/api")

# Emails do not change while the app runs, and reading 520 files per request is wasteful.
_EMAIL_TTL_SECONDS = 60
_email_cache: dict = {"source": None, "at": 0.0, "emails": {}}


def _inbox() -> Inbox:
    return Inbox(inbox_source())


def _emails() -> dict:
    source = inbox_source()
    fresh = time.monotonic() - _email_cache["at"] < _EMAIL_TTL_SECONDS
    if _email_cache["source"] != source or not fresh:
        _email_cache.update(
            source=source,
            at=time.monotonic(),
            emails={e["email_id"]: e for e in _inbox().emails()},
        )
    return _email_cache["emails"]


def _records(scope: str) -> tuple[dict, str, str]:
    """(records, scope actually used, where they came from).

    "auto" means the full run if there is one, otherwise the latest limited run.
    """
    if scope not in ("auto", *SCOPES):
        raise HTTPException(status_code=422, detail="scope must be auto, full or sample")
    store = get_store()
    order = SCOPES if scope == "auto" else (scope,)
    for candidate in order:
        records, source = store.load(candidate)
        if records or candidate == order[-1]:
            return records, candidate, source
    return {}, order[-1], "files"


def _row(email: dict, record: dict) -> dict:
    return {
        "email_id": email["email_id"],
        "subject": email.get("subject", ""),
        "from": email.get("from", ""),
        "category": record["category"],
        "status": record["status"],
        "review_reason": record.get("review_reason"),
        "confidence": record.get("confidence"),
        "summary": record.get("summary"),
        "has_defect": record.get("has_defect", False),
        "defect_fields": record.get("defect_fields", []),
        "issue_count": len(record.get("field_issues", [])),
        "attachment_count": len(email.get("attachments", [])),
    }


def _needs_attention(row: dict) -> bool:
    return row["status"] in ("NEEDS_REVIEW", "MISMATCH")


@router.get("/status")
def status():
    store = get_store()
    scope = run_state.running_scope()
    view = scope or "sample"
    processed = len(FileCheckpoint(checkpoint_file(view)).records())
    return {
        "version": __version__,
        "running": scope is not None,
        "stopping": scope is not None and run_state.stop_requested(),
        "scope": scope,
        "processed": processed if scope else None,
        "total": run_state.current["total"] if scope else None,
        "storage": store.backend,
        "storage_error": store.error,
    }


@router.post("/run/stop")
def stop_run():
    """Stop the run in progress after the emails already being processed.

    What has finished is kept, so `resume=true` carries on from there.
    """
    if not run_state.request_stop():
        raise HTTPException(status_code=409, detail="no run is in progress")
    return {"stopping": True}


@router.get("/report")
def report(scope: str = Query("auto")):
    records, used, source = _records(scope)
    emails = _emails()
    rows = [_row(emails[eid], rec) for eid, rec in sorted(records.items()) if eid in emails]
    return {
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": used,
        "source": source,
        "summary": {
            "total": len(rows),
            "inbox_total": len(emails),
            "categories": dict(Counter(r["category"] for r in rows)),
            "statuses": dict(Counter(r["status"] for r in rows)),
            "review_reasons": dict(Counter(r["review_reason"] for r in rows if r["review_reason"])),
            "defects": sum(1 for r in rows if r["has_defect"]),
            "needs_attention": sum(1 for r in rows if _needs_attention(r)),
            "failed": sum(1 for eid in records if is_failed(records[eid])),
        },
        "emails": rows,
    }


def _attachment(email: dict, role: str) -> Optional[str]:
    return next((a for a in email.get("attachments", []) if f"_{role}" in a), None)


def _documents(email: dict) -> list[dict]:
    """The SI and BL attachments: their text, or how many page images a scan has."""
    documents = []
    for role in ("SI", "BL"):
        path = _attachment(email, role)
        if path is None:
            continue
        item = {"role": role, "file": path, "kind": "unreadable", "text": None, "pages": 0}
        try:
            loaded = load_document(_inbox(), path)
        except (DocumentUnreadableError, OSError):
            documents.append(item)
            continue
        if loaded.scanned:
            item.update(kind="scan", pages=len(loaded.images))
        else:
            item.update(kind="text", text=loaded.text)
        documents.append(item)
    return documents


def _case(email_id: str, scope: str) -> tuple[dict, dict, str]:
    records, used, _ = _records(scope)
    email = _emails().get(email_id)
    if email is None or email_id not in records:
        raise HTTPException(status_code=404, detail=f"no result for {email_id}")
    return email, records[email_id], used


@router.get("/emails/{email_id}")
def email_case(email_id: str, scope: str = Query("auto")):
    email, record, used = _case(email_id, scope)
    return {
        "scope": used,
        "email": {
            "email_id": email_id,
            "subject": email.get("subject", ""),
            "from": email.get("from", ""),
            "body": email.get("body", ""),
            "attachments": email.get("attachments", []),
        },
        "record": record,
        "documents": _documents(email),
    }


@router.get("/emails/{email_id}/documents/{role}/pages/{page}.png")
def page_image(email_id: str, role: str, page: int):
    if role not in ("SI", "BL"):
        raise HTTPException(status_code=404, detail="role must be SI or BL")
    email = _emails().get(email_id)
    path = _attachment(email, role) if email else None
    if path is None:
        raise HTTPException(status_code=404, detail="no such document")
    try:
        loaded = load_document(_inbox(), path)
    except (DocumentUnreadableError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not loaded.scanned or not 1 <= page <= len(loaded.images):
        raise HTTPException(status_code=404, detail="no such page image")
    data, mime = loaded.images[page - 1]
    return Response(content=data, media_type=mime)


@router.post("/emails/{email_id}/retry")
def retry(email_id: str, scope: str = Query("auto")):
    """Run the pipeline again for one email, saving the result like any other."""
    if not run_state.lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="a run is already in progress")
    try:
        email = _emails().get(email_id)
        if email is None:
            raise HTTPException(status_code=404, detail=f"no such email {email_id}")
        _, used, _ = _records(scope)
        record = _record(process_email(email, _inbox()))
        get_store().checkpoint(used).append(record)
        return {"email_id": email_id, "scope": used, "status": record["status"],
                "review_reason": record["review_reason"], "failed": is_failed(record)}
    finally:
        run_state.lock.release()


class CorrectionIn(BaseModel):
    fields: dict[str, str] = {}
    notes: str = ""
    updated_at: Optional[str] = None


class DelegationIn(BaseModel):
    to: str


def _record_for_write(email_id: str, scope: str) -> tuple[dict, str]:
    """The current record for `email_id`, and the scope it actually lives in."""
    if _emails().get(email_id) is None:
        raise HTTPException(status_code=404, detail=f"no such email {email_id}")
    records, used, _ = _records(scope)
    if email_id not in records:
        raise HTTPException(status_code=404, detail=f"no result for {email_id}")
    return dict(records[email_id]), used


@router.post("/emails/{email_id}/correction")
def save_correction(email_id: str, payload: CorrectionIn, scope: str = Query("auto")):
    record, used = _record_for_write(email_id, scope)
    record["correction"] = {
        "fields": payload.fields,
        "notes": payload.notes,
        "updated_at": payload.updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    get_store().checkpoint(used).append(record)
    return {"email_id": email_id, "scope": used, "correction": record["correction"]}


@router.delete("/emails/{email_id}/correction")
def clear_correction(email_id: str, scope: str = Query("auto")):
    record, used = _record_for_write(email_id, scope)
    record.pop("correction", None)
    get_store().checkpoint(used).append(record)
    return {"email_id": email_id, "scope": used, "correction": None}


@router.post("/emails/{email_id}/delegate")
def save_delegation(email_id: str, payload: DelegationIn, scope: str = Query("auto")):
    to = payload.to.strip()
    if not to:
        raise HTTPException(status_code=422, detail="to must not be empty")
    record, used = _record_for_write(email_id, scope)
    record["delegation"] = {"to": to, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    get_store().checkpoint(used).append(record)
    return {"email_id": email_id, "scope": used, "delegation": record["delegation"]}


@router.delete("/emails/{email_id}/delegate")
def clear_delegation(email_id: str, scope: str = Query("auto")):
    record, used = _record_for_write(email_id, scope)
    record.pop("delegation", None)
    get_store().checkpoint(used).append(record)
    return {"email_id": email_id, "scope": used, "delegation": None}


@router.get("/db/status")
def db_status():
    return get_store().status()


@router.get("/db/collections/{name}")
def db_documents(
    name: str,
    email_id: Optional[str] = None,
    limit: int = Query(25, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    try:
        return get_store().documents(name, email_id=email_id, limit=limit, skip=skip)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no collection named {name}")
