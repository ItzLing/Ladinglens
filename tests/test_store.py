"""Tests for app/store.py: the file checkpoint, and the MongoDB copy (mongomock).

mongomock is an in-memory stand-in, so these run with no database. They do not
replace one manual check against a real MongoDB server.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mongomock
from pymongo.errors import PyMongoError

from app import paths, store
from app.store import FileCheckpoint, MongoMirror, ResultStore, is_failed


def record(email_id, status="OK", reason=None, category="GENERAL"):
    return {"email_id": email_id, "status": status, "review_reason": reason,
            "category": category, "confidence": 0.9}


def failure(email_id, category="GENERAL"):
    return record(email_id, "NEEDS_REVIEW", "processing_error", category)


class TempResults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(paths, "RESULTS_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)


class FileCheckpointTests(TempResults):
    def make(self):
        return FileCheckpoint(store.checkpoint_file("full"))

    def test_append_then_load_splits_real_verdicts_from_failures(self):
        cp = self.make()
        cp.reset()
        cp.append(record("a"))
        cp.append(failure("b"))
        done, failed = cp.load()
        self.assertEqual(list(done), ["a"])
        self.assertEqual(list(failed), ["b"])

    def test_a_later_success_clears_an_earlier_failure(self):
        cp = self.make()
        cp.reset()
        cp.append(failure("a"))
        cp.append(record("a"))
        done, failed = cp.load()
        self.assertIn("a", done)
        self.assertNotIn("a", failed)

    def test_a_failure_after_a_real_verdict_does_not_replace_it(self):
        cp = self.make()
        cp.reset()
        cp.append(record("a", "MISMATCH"))
        cp.append(failure("a"))
        self.assertEqual(cp.records()["a"]["status"], "MISMATCH")

    def test_a_torn_last_line_is_ignored(self):
        cp = self.make()
        cp.reset()
        cp.append(record("a"))
        with cp.path.open("a", encoding="utf-8") as fh:
            fh.write('{"email_id": "b", "sta')
        self.assertEqual(list(cp.records()), ["a"])

    def test_the_more_informative_failure_is_kept(self):
        cp = self.make()
        cp.reset()
        cp.append(failure("a", category="BL_COMPARISON"))
        cp.append(failure("a", category="GENERAL"))
        self.assertEqual(cp.records()["a"]["category"], "BL_COMPARISON")

    def test_a_missing_file_is_just_empty(self):
        self.assertEqual(self.make().records(), {})


class FileBackendTests(TempResults):
    def test_without_a_uri_the_backend_is_files(self):
        s = ResultStore()
        self.assertEqual((s.backend, s.configured), ("files", False))
        cp = s.checkpoint("full")
        cp.reset()
        cp.append(record("a"))
        records, source = s.load("full")
        self.assertEqual((list(records), source), (["a"], "files"))
        self.assertIsNone(s.start_run("full", None, False))

    def test_status_and_documents_work_without_mongodb(self):
        s = ResultStore()
        cp = s.checkpoint("sample")
        cp.reset()
        cp.append(record("a"))
        status = s.status()
        self.assertFalse(status["connected"])
        self.assertEqual(status["collections"][0]["count"], 1)
        page = s.documents("results")
        self.assertEqual((page["source"], page["total"]), ("files", 1))
        self.assertEqual(page["items"][0]["scope"], "sample")

    def test_scopes_are_kept_apart(self):
        s = ResultStore()
        for scope, eid in (("full", "a"), ("sample", "b")):
            cp = s.checkpoint(scope)
            cp.reset()
            cp.append(record(eid))
        self.assertEqual(list(s.load("full")[0]), ["a"])
        self.assertEqual(list(s.load("sample")[0]), ["b"])


class MongoBackendTests(TempResults):
    def setUp(self):
        super().setUp()
        self.client = mongomock.MongoClient()
        self.s = ResultStore(uri="mongodb://user:secret@db.example.com:27017/x", client=self.client)
        self.results = self.client["ladinglens"]["results"]

    def test_every_record_is_written_to_the_file_and_copied_to_mongodb(self):
        cp = self.s.checkpoint("full")
        cp.reset()
        cp.append(record("a"))
        self.assertEqual(list(FileCheckpoint(store.checkpoint_file("full")).records()), ["a"])
        doc = self.results.find_one({"scope": "full", "email_id": "a"})
        self.assertEqual(doc["record"]["status"], "OK")
        self.assertEqual(self.s.load("full"), ({"a": doc["record"]}, "mongodb"))

    def test_writing_the_same_email_twice_keeps_one_document(self):
        cp = self.s.checkpoint("full")
        cp.reset()
        cp.append(record("a"))
        cp.append(record("a", "MISMATCH"))
        self.assertEqual(self.results.count_documents({"email_id": "a"}), 1)
        doc = self.results.find_one({"email_id": "a"})
        self.assertEqual((doc["record"]["status"], doc["attempts"]), ("MISMATCH", 2))

    def test_a_real_verdict_is_never_traded_for_a_later_failure(self):
        cp = self.s.checkpoint("full")
        cp.reset()
        cp.append(record("a", "MISMATCH"))
        cp.append(failure("a"))
        doc = self.results.find_one({"email_id": "a"})
        self.assertEqual(doc["record"]["status"], "MISMATCH")
        self.assertEqual(doc["attempts"], 2)

    def test_reset_clears_only_its_own_scope(self):
        for scope, eid in (("full", "a"), ("sample", "b")):
            cp = self.s.checkpoint(scope)
            cp.reset()
            cp.append(record(eid))
        self.s.checkpoint("sample").reset()
        self.assertEqual(self.results.count_documents({"scope": "full"}), 1)
        self.assertEqual(self.results.count_documents({"scope": "sample"}), 0)

    def test_a_run_is_recorded_and_finished(self):
        run_id = self.s.start_run("sample", 5, False)
        self.s.finish_run(run_id, {"OK": 4, "MISMATCH": 1})
        run = self.client["ladinglens"]["runs"].find_one({"_id": run_id})
        self.assertEqual((run["scope"], run["limit"], run["counts"]["OK"]), ("sample", 5, 4))
        self.assertIsNotNone(run["finished_at"])
        self.assertEqual(run["version"], "0.0.1")

    def test_status_shows_counts_and_never_the_credentials(self):
        cp = self.s.checkpoint("full")
        cp.reset()
        cp.append(record("a"))
        status = self.s.status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["server"], "mongodb://db.example.com:27017")
        self.assertNotIn("secret", json.dumps(status))
        self.assertNotIn("user", json.dumps(status).replace("mongodb", ""))
        self.assertEqual({c["name"]: c["count"] for c in status["collections"]},
                         {"results": 1, "runs": 0})

    def test_documents_are_json_safe_paged_filterable_and_capped(self):
        cp = self.s.checkpoint("full")
        cp.reset()
        for i in range(5):
            cp.append(record(f"e{i}"))
        page = self.s.documents("results", limit=2)
        self.assertEqual((page["source"], page["total"], len(page["items"])), ("mongodb", 5, 2))
        json.dumps(page)  # ObjectId and datetime must not leak through
        self.assertEqual(self.s.documents("results", email_id="e3")["total"], 1)
        self.assertEqual(len(self.s.documents("results", limit=10_000)["items"]), 5)

    def test_only_known_collections_can_be_read(self):
        with self.assertRaises(KeyError):
            self.s.documents("system.users")

    def test_an_empty_mongodb_falls_back_to_the_file(self):
        FileCheckpoint(store.checkpoint_file("full")).append(record("only_in_file"))
        records, source = self.s.load("full")
        self.assertEqual((list(records), source), (["only_in_file"], "files"))


class MongoFailureTests(TempResults):
    def test_a_database_that_fails_never_loses_the_run(self):
        s = ResultStore(uri="mongodb://x", client=mongomock.MongoClient())
        cp = s.checkpoint("full")
        cp.reset()
        with mock.patch.object(MongoMirror, "append", side_effect=PyMongoError("down")):
            cp.append(record("a"))
        self.assertEqual(list(FileCheckpoint(store.checkpoint_file("full")).records()), ["a"])
        self.assertIn("The run continues from the file", s.error)

    def test_reading_falls_back_to_the_file_when_mongodb_errors(self):
        s = ResultStore(uri="mongodb://x", client=mongomock.MongoClient())
        FileCheckpoint(store.checkpoint_file("full")).append(record("a"))
        with mock.patch.object(ResultStore, "_database", side_effect=PyMongoError("down")):
            records, source = s.load("full")
        self.assertEqual((list(records), source), (["a"], "files"))

    def test_status_reports_the_problem_in_plain_words(self):
        s = ResultStore(uri="mongodb://x", client=mongomock.MongoClient())
        with mock.patch.object(ResultStore, "_database", side_effect=PyMongoError("down")):
            status = s.status()
        self.assertFalse(status["connected"])
        self.assertIn("MongoDB", status["error"])


class HelperTests(unittest.TestCase):
    def test_is_failed_only_matches_processing_error(self):
        self.assertTrue(is_failed(failure("a")))
        self.assertFalse(is_failed(record("a", "NEEDS_REVIEW", "unreadable")))

    def test_get_store_reads_its_settings_from_the_environment(self):
        with mock.patch.dict("os.environ", {"MONGODB_URI": "", "MONGODB_DB": ""}):
            store._store = None
            self.assertEqual(store.get_store().backend, "files")
        with mock.patch.dict("os.environ", {"MONGODB_URI": "mongodb://h:1", "MONGODB_DB": "d"}):
            store._store = None
            s = store.get_store()
            self.assertEqual((s.backend, s.db_name), ("mongodb", "d"))
        store._store = None


if __name__ == "__main__":
    unittest.main()
