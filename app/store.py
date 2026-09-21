"""Where a run's results are kept.

The JSONL file in results/ is always written. It is the crash-safe checkpoint that
resume reads, so a database being down can never lose a run. When MONGODB_URI is
set, every record is also copied into MongoDB, and the API reads from there.

    results collection: {scope, email_id, record, attempts, updated_at}
        scope is "full" or "sample", so a ?limit=N run never overwrites a full one.
        A unique (scope, email_id) index makes every write idempotent.
    runs collection:    {scope, started_at, finished_at, limit, resume, counts, model, version}
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

from app import __version__
from app.paths import results_file
from app.schema import ReviewReason

SCOPES = ("full", "sample")
COLLECTIONS = ("results", "runs")
MAX_PAGE = 100


def is_failed(record: dict) -> bool:
    return record.get("review_reason") == ReviewReason.PROCESSING_ERROR.value


def better_failure(prior: Optional[dict], new: dict) -> dict:
    """Pick whichever failed attempt still knows the most.

    A failure after a successful classification keeps the real category; one
    where classification itself failed only has the GENERAL fallback. Retrying
    while the API is down must not trade the former for the latter.
    """
    if prior is None:
        return new
    if prior["category"] != "GENERAL" and new["category"] == "GENERAL":
        return prior
    return new


def _now() -> datetime:
    return datetime.now(timezone.utc)


def checkpoint_file(scope: str) -> Path:
    return results_file("results.jsonl" if scope == "full" else "results.sample.jsonl")


class FileCheckpoint:
    """One JSON record per line, appended as each email finishes."""

    def __init__(self, path: Path):
        self.path = path

    def reset(self) -> None:
        self.path.write_text("", encoding="utf-8")

    def append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def load(self) -> tuple[dict, dict]:
        """Split the file into (succeeded, failed) by email_id.

        Failures are kept separate so resuming retries them rather than banking an
        API outage as a verdict -- but they are still returned, so a retry that
        also fails can fall back to what the earlier attempt knew.
        """
        done: dict = {}
        failed: dict = {}
        if not self.path.exists():
            return done, failed
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a run killed mid-write can leave one torn line
            email_id = record["email_id"]
            if is_failed(record):
                failed[email_id] = better_failure(failed.get(email_id), record)
            else:
                done[email_id] = record
                failed.pop(email_id, None)
        return done, failed

    def records(self) -> dict:
        """The latest record per email, preferring a real verdict over a failure."""
        done, failed = self.load()
        return {**failed, **done}


class MongoMirror:
    """Copies each record into the `results` collection."""

    def __init__(self, database, scope: str):
        self.results = database["results"]
        self.scope = scope

    def reset(self) -> None:
        self.results.delete_many({"scope": self.scope})

    def append(self, record: dict) -> None:
        key = {"scope": self.scope, "email_id": record["email_id"]}
        existing = self.results.find_one(key)
        if existing and is_failed(record) and not is_failed(existing["record"]):
            # A real verdict is never traded for a later failure.
            self.results.update_one(key, {"$inc": {"attempts": 1}, "$set": {"updated_at": _now()}})
            return
        self.results.update_one(
            key,
            {"$set": {"record": record, "updated_at": _now()}, "$inc": {"attempts": 1}},
            upsert=True,
        )


class Checkpoint:
    """The file first, then MongoDB as a best-effort copy."""

    def __init__(self, file: FileCheckpoint, mirror: Optional[MongoMirror], on_error):
        self.file = file
        self.mirror = mirror
        self.on_error = on_error

    def _mirrored(self, action, *args) -> None:
        if self.mirror is None:
            return
        try:
            action(*args)
        except PyMongoError as exc:
            self.on_error(exc)

    def reset(self) -> None:
        self.file.reset()
        if self.mirror is not None:
            self._mirrored(self.mirror.reset)

    def load(self) -> tuple[dict, dict]:
        return self.file.load()

    def append(self, record: dict) -> None:
        self.file.append(record)
        if self.mirror is not None:
            self._mirrored(self.mirror.append, record)


def _clean(value):
    """Make a MongoDB document safe to send as JSON."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value).__name__ == "ObjectId":
        return str(value)
    return value


def _host(uri: str) -> str:
    """The server part of a URI, never the user name or password."""
    parts = urlsplit(uri)
    host = parts.hostname or "unknown host"
    return f"{parts.scheme}://{host}" + (f":{parts.port}" if parts.port else "")


class ResultStore:
    def __init__(self, uri: Optional[str] = None, db_name: str = "ladinglens", client=None):
        self.uri = uri
        self.db_name = db_name
        self._client = client
        self.error: Optional[str] = None  # the last MongoDB problem, in plain words

    @property
    def configured(self) -> bool:
        return bool(self.uri or self._client is not None)

    @property
    def backend(self) -> str:
        return "mongodb" if self.configured else "files"

    def _database(self):
        if self._client is None:
            self._client = MongoClient(self.uri, serverSelectionTimeoutMS=3000)
        database = self._client[self.db_name]
        database["results"].create_index(
            [("scope", ASCENDING), ("email_id", ASCENDING)], unique=True
        )
        return database

    def _note(self, exc: Exception) -> None:
        self.error = f"MongoDB: {exc.__class__.__name__}. The run continues from the file."

    # ---- writing a run
    def checkpoint(self, scope: str) -> Checkpoint:
        mirror = None
        if self.configured:
            try:
                mirror = MongoMirror(self._database(), scope)
            except PyMongoError as exc:
                self._note(exc)
        return Checkpoint(FileCheckpoint(checkpoint_file(scope)), mirror, self._note)

    def start_run(self, scope: str, limit: Optional[int], resume: bool) -> Optional[object]:
        if not self.configured:
            return None
        try:
            return self._database()["runs"].insert_one(
                {
                    "scope": scope, "started_at": _now(), "finished_at": None,
                    "limit": limit, "resume": resume, "counts": None,
                    "model": os.environ.get("LLM_MODEL"), "version": __version__,
                }
            ).inserted_id
        except PyMongoError as exc:
            self._note(exc)
            return None

    def finish_run(self, run_id, counts: dict) -> None:
        if run_id is None:
            return
        try:
            self._database()["runs"].update_one(
                {"_id": run_id}, {"$set": {"finished_at": _now(), "counts": counts}}
            )
        except PyMongoError as exc:
            self._note(exc)

    # ---- reading
    def load(self, scope: str = "full") -> tuple[dict, str]:
        """(latest record per email, where they came from)."""
        if self.configured:
            try:
                docs = self._database()["results"].find({"scope": scope})
                records = {d["email_id"]: d["record"] for d in docs}
                if records:
                    self.error = None
                    return records, "mongodb"
            except PyMongoError as exc:
                self._note(exc)
        return FileCheckpoint(checkpoint_file(scope)).records(), "files"

    def status(self) -> dict:
        info = {
            "backend": self.backend,
            "configured": self.configured,
            "connected": False,
            "database": self.db_name if self.configured else None,
            "server": _host(self.uri) if self.uri else None,
            "error": None,
            "collections": [],
        }
        if self.configured:
            try:
                database = self._database()
                self._client.admin.command("ping")
                info["connected"] = True
                info["collections"] = [
                    {"name": name, "count": database[name].count_documents({})}
                    for name in COLLECTIONS
                ]
                return info
            except PyMongoError as exc:
                self._note(exc)
                info["error"] = self.error
        info["collections"] = [
            {"name": "results", "count": sum(
                len(FileCheckpoint(checkpoint_file(s)).records()) for s in SCOPES
            ), "source": "files"},
        ]
        return info

    def documents(self, name: str, email_id: Optional[str] = None,
                  limit: int = 25, skip: int = 0) -> dict:
        """A read-only page of a collection, newest first."""
        if name not in COLLECTIONS:
            raise KeyError(name)
        limit = max(1, min(limit, MAX_PAGE))
        skip = max(0, skip)
        if self.configured and name in COLLECTIONS:
            try:
                collection = self._database()[name]
                query = {"email_id": email_id} if email_id and name == "results" else {}
                total = collection.count_documents(query)
                sort_key = "updated_at" if name == "results" else "started_at"
                cursor = collection.find(query).sort(sort_key, -1).skip(skip).limit(limit)
                return {"source": "mongodb", "total": total,
                        "items": [_clean(d) for d in cursor]}
            except PyMongoError as exc:
                self._note(exc)
        if name != "results":
            return {"source": "files", "total": 0, "items": []}
        items = []
        for scope in SCOPES:
            for eid, record in sorted(FileCheckpoint(checkpoint_file(scope)).records().items()):
                if email_id in (None, eid):
                    items.append({"scope": scope, "email_id": eid, "record": record})
        return {"source": "files", "total": len(items), "items": items[skip:skip + limit]}


_store: Optional[ResultStore] = None


def get_store() -> ResultStore:
    """The process-wide store, configured from MONGODB_URI / MONGODB_DB."""
    global _store
    if _store is None:
        _store = ResultStore(
            uri=os.environ.get("MONGODB_URI") or None,
            db_name=os.environ.get("MONGODB_DB") or "ladinglens",
        )
    return _store
