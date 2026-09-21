"""Tests for the read-only /api routes and the served UI, over real HTTP semantics.

A temp inbox and a temp results folder are used, so nothing here touches the real
data/ or results/ folders, and no model or database is called.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mongomock
from fastapi.testclient import TestClient
from PIL import Image

from app import api, main, paths, run_state, store
from app.schema import ComparisonResult, EmailCategory
from app.store import ResultStore


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def record(email_id, category, status, reason=None, **extra):
    return {"email_id": email_id, "category": category, "status": status,
            "review_reason": reason, "confidence": 0.95, "has_defect": status == "MISMATCH",
            "defect_fields": ["consignee"] if status == "MISMATCH" else [],
            "mismatches": {}, "field_issues": [], "summary": None, "extracted": {}, **extra}


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        data, results = root / "data", root / "results"
        (data / "inbox").mkdir(parents=True)
        (data / "attachments").mkdir()
        results.mkdir()

        emails = {
            "email_001": {"subject": "Check BL", "from": "a@x.com", "body": "Please check.",
                          "attachments": ["attachments/email_001_SI.txt", "attachments/email_001_BL.txt"]},
            "email_002": {"subject": "Cheap watches", "from": "spam@x.com", "body": "Buy now", "attachments": []},
            "email_003": {"subject": "Scans", "from": "b@x.com", "body": "Scanned copies",
                          "attachments": ["attachments/email_003_SI.pdf", "attachments/email_003_BL.txt"]},
            "email_004": {"subject": "Failed one", "from": "c@x.com", "body": "x", "attachments": []},
        }
        for eid, email in emails.items():
            write_json(data / "inbox" / f"{eid}.json", {"email_id": eid, **email})
        (data / "attachments" / "email_001_SI.txt").write_text("Shipper: ACME LTD\n", encoding="utf-8")
        (data / "attachments" / "email_001_BL.txt").write_text("Shipper: ACME LIMITED\n", encoding="utf-8")
        (data / "attachments" / "email_003_BL.txt").write_text("Shipper: ACME\n", encoding="utf-8")
        Image.new("RGB", (60, 60), "white").save(data / "attachments" / "email_003_SI.pdf", "PDF")

        for patcher in (
            mock.patch.object(paths, "RESULTS_DIR", results),
            mock.patch.dict(os.environ, {"INBOX_SOURCE": str(data)}),
            mock.patch.object(store, "_store", ResultStore()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        api._email_cache.update(source=None, at=0.0, emails={})
        self.addCleanup(api._email_cache.update, source=None, at=0.0, emails={})
        self.client = TestClient(main.app)
        self.store = store._store

    def save(self, scope, *records):
        cp = self.store.checkpoint(scope)
        cp.reset()
        for r in records:
            cp.append(r)

    def full_run(self):
        self.save(
            "full",
            record("email_001", "BL_COMPARISON", "MISMATCH", summary="A BL check.",
                   mismatches={"shipper": {"si": "ACME LTD", "bl": "ACME LIMITED"}}),
            record("email_002", "SPAM", "OK", summary="Unsolicited offer."),
            record("email_003", "BL_COMPARISON", "NEEDS_REVIEW", "missing_value",
                   field_issues=[{"field": "gross_weight_kg"}]),
            record("email_004", "GENERAL", "NEEDS_REVIEW", "processing_error"),
        )


class StatusAndReportTests(ApiCase):
    def test_status_says_idle_and_names_the_version_and_storage(self):
        body = self.client.get("/api/status").json()
        self.assertEqual((body["version"], body["running"], body["storage"]), ("0.0.1", False, "files"))

    def test_status_reports_progress_while_a_run_holds_the_lock(self):
        self.save("sample", record("email_001", "SPAM", "OK"), record("email_002", "SPAM", "OK"))
        run_state.lock.acquire()
        run_state.begin("sample", 5)
        try:
            body = self.client.get("/api/status").json()
        finally:
            run_state.end()
            run_state.lock.release()
        self.assertEqual((body["running"], body["scope"], body["processed"], body["total"]),
                         (True, "sample", 2, 5))

    def test_stop_is_refused_when_nothing_is_running(self):
        self.assertEqual(self.client.post("/api/run/stop").status_code, 409)
        self.assertFalse(run_state.stop_requested())

    def test_stop_marks_the_run_as_stopping_and_the_next_run_starts_clean(self):
        run_state.lock.acquire()
        run_state.begin("full", 10)
        try:
            self.assertFalse(self.client.get("/api/status").json()["stopping"])
            self.assertEqual(self.client.post("/api/run/stop").json(), {"stopping": True})
            self.assertTrue(self.client.get("/api/status").json()["stopping"])
            run_state.begin("full", 10)  # the next run must not inherit the request
            self.assertFalse(run_state.stop_requested())
        finally:
            run_state.end()
            run_state.lock.release()
        self.assertFalse(self.client.get("/api/status").json()["stopping"])

    def test_report_has_one_light_row_per_email_and_the_totals(self):
        self.full_run()
        body = self.client.get("/api/report").json()
        self.assertEqual(body["scope"], "full")
        self.assertEqual([r["email_id"] for r in body["emails"]],
                         ["email_001", "email_002", "email_003", "email_004"])
        s = body["summary"]
        self.assertEqual((s["total"], s["inbox_total"], s["defects"]), (4, 4, 1))
        self.assertEqual(s["needs_attention"], 3)  # a mismatch, a review, a failure
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["categories"], {"BL_COMPARISON": 2, "SPAM": 1, "GENERAL": 1})
        first = body["emails"][0]
        self.assertEqual((first["subject"], first["summary"]), ("Check BL", "A BL check."))
        self.assertNotIn("body", first)
        self.assertNotIn("mismatches", first)

    def test_auto_prefers_the_full_run_then_falls_back_to_the_sample(self):
        self.save("sample", record("email_002", "SPAM", "OK"))
        self.assertEqual(self.client.get("/api/report").json()["scope"], "sample")
        self.full_run()
        self.assertEqual(self.client.get("/api/report").json()["scope"], "full")
        self.assertEqual(self.client.get("/api/report?scope=sample").json()["summary"]["total"], 1)

    def test_a_bad_scope_is_rejected(self):
        self.assertEqual(self.client.get("/api/report?scope=everything").status_code, 422)

    def test_with_no_results_the_report_is_empty_not_an_error(self):
        body = self.client.get("/api/report").json()
        self.assertEqual((body["summary"]["total"], body["emails"]), (0, []))

    def test_results_for_an_email_that_left_the_inbox_are_skipped(self):
        self.save("full", record("email_999", "SPAM", "OK"))
        self.assertEqual(self.client.get("/api/report").json()["emails"], [])

    def test_the_report_reads_from_mongodb_when_it_is_configured(self):
        s = ResultStore(uri="mongodb://h:1", client=mongomock.MongoClient())
        with mock.patch.object(store, "_store", s):
            cp = s.checkpoint("full")
            cp.reset()
            cp.append(record("email_002", "SPAM", "OK"))
            body = self.client.get("/api/report").json()
        self.assertEqual((body["source"], body["summary"]["total"]), ("mongodb", 1))


class CaseTests(ApiCase):
    def test_an_unknown_email_is_a_404(self):
        self.full_run()
        self.assertEqual(self.client.get("/api/emails/email_999").status_code, 404)

    def test_the_case_carries_the_body_the_record_and_the_document_text(self):
        self.full_run()
        body = self.client.get("/api/emails/email_001").json()
        self.assertEqual(body["email"]["body"], "Please check.")
        self.assertEqual(body["record"]["status"], "MISMATCH")
        docs = {d["role"]: d for d in body["documents"]}
        self.assertEqual((docs["SI"]["kind"], docs["SI"]["text"].strip()), ("text", "Shipper: ACME LTD"))
        self.assertEqual(docs["BL"]["file"], "attachments/email_001_BL.txt")

    def test_a_scanned_document_is_described_by_its_page_count_not_its_text(self):
        self.full_run()
        docs = {d["role"]: d for d in self.client.get("/api/emails/email_003").json()["documents"]}
        self.assertEqual((docs["SI"]["kind"], docs["SI"]["pages"], docs["SI"]["text"]), ("scan", 1, None))

    def test_an_email_with_no_attachments_has_no_documents(self):
        self.full_run()
        self.assertEqual(self.client.get("/api/emails/email_002").json()["documents"], [])


class PageImageTests(ApiCase):
    def test_a_scan_page_is_served_as_a_png(self):
        response = self.client.get("/api/emails/email_003/documents/SI/pages/1.png")
        self.assertEqual((response.status_code, response.headers["content-type"]), (200, "image/png"))
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_missing_pages_and_non_scans_are_404(self):
        for url in ("/api/emails/email_003/documents/SI/pages/2.png",
                    "/api/emails/email_003/documents/SI/pages/0.png",
                    "/api/emails/email_001/documents/SI/pages/1.png",
                    "/api/emails/email_002/documents/SI/pages/1.png",
                    "/api/emails/email_999/documents/SI/pages/1.png",
                    "/api/emails/email_003/documents/XX/pages/1.png"):
            self.assertEqual(self.client.get(url).status_code, 404, url)


class RetryTests(ApiCase):
    def test_retry_runs_one_email_again_and_saves_the_new_result(self):
        self.full_run()
        fixed = ComparisonResult(email_id="email_004", category=EmailCategory.GENERAL, summary="Fixed.")
        with mock.patch.object(api, "process_email", return_value=fixed):
            body = self.client.post("/api/emails/email_004/retry").json()
        self.assertEqual((body["status"], body["failed"], body["scope"]), ("OK", False, "full"))
        rows = {r["email_id"]: r for r in self.client.get("/api/report").json()["emails"]}
        self.assertEqual(rows["email_004"]["status"], "OK")
        self.assertEqual(self.client.get("/api/report").json()["summary"]["failed"], 0)

    def test_a_retry_that_fails_again_says_so_and_keeps_the_earlier_verdict(self):
        self.full_run()
        failed = ComparisonResult(email_id="email_001", category=EmailCategory.GENERAL,
                                  needs_review=True, review_reason="processing_error")
        with mock.patch.object(api, "process_email", return_value=failed):
            body = self.client.post("/api/emails/email_001/retry").json()
        self.assertTrue(body["failed"])
        rows = {r["email_id"]: r for r in self.client.get("/api/report").json()["emails"]}
        self.assertEqual(rows["email_001"]["status"], "MISMATCH")

    def test_retry_is_refused_while_a_run_is_in_progress(self):
        self.full_run()
        run_state.lock.acquire()
        try:
            self.assertEqual(self.client.post("/api/emails/email_004/retry").status_code, 409)
            self.assertEqual(self.client.post("/run").status_code, 409)
        finally:
            run_state.lock.release()

    def test_retrying_an_unknown_email_is_a_404_and_frees_the_lock(self):
        self.assertEqual(self.client.post("/api/emails/email_999/retry").status_code, 404)
        self.assertFalse(run_state.lock.locked())


class DatabaseTests(ApiCase):
    def test_db_status_names_the_backend(self):
        body = self.client.get("/api/db/status").json()
        self.assertEqual((body["backend"], body["connected"]), ("files", False))

    def test_a_collection_is_paged_and_an_unknown_one_is_a_404(self):
        self.full_run()
        page = self.client.get("/api/db/collections/results?limit=2").json()
        self.assertEqual((page["total"], len(page["items"])), (4, 2))
        self.assertEqual(self.client.get("/api/db/collections/results?email_id=email_002").json()["total"], 1)
        self.assertEqual(self.client.get("/api/db/collections/users").status_code, 404)
        self.assertEqual(self.client.get("/api/db/collections/results?limit=1000").status_code, 422)


class BuildReportTests(ApiCase):
    def load_builder(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("build_report", Path(main.__file__).parent.parent / "web" / "build_report.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_demo_report_has_every_row_and_a_case_for_each(self):
        self.full_run()
        report = self.load_builder().build()
        self.assertEqual({"version", "generated_at", "scope", "source", "summary", "emails", "cases"}, set(report))
        self.assertEqual(sorted(report["cases"]), [r["email_id"] for r in report["emails"]])
        case = report["cases"]["email_001"]
        self.assertEqual(case["record"]["status"], "MISMATCH")
        self.assertEqual(case["email"]["body"], "Please check.")

    def test_scans_are_described_not_embedded_and_long_text_is_capped(self):
        self.full_run()
        builder = self.load_builder()
        (Path(os.environ["INBOX_SOURCE"]) / "attachments" / "email_001_SI.txt").write_text("x" * 9000, encoding="utf-8")
        report = builder.build()
        si = {d["role"]: d for d in report["cases"]["email_001"]["documents"]}["SI"]
        self.assertEqual(len(si["text"]), builder.MAX_DOC_CHARS)
        scan = {d["role"]: d for d in report["cases"]["email_003"]["documents"]}["SI"]
        self.assertEqual((scan["kind"], scan["text"]), ("scan", None))

    def test_it_refuses_to_build_from_nothing(self):
        with self.assertRaises(SystemExit):
            self.load_builder().build()

    def test_the_sample_flag_uses_the_limited_run(self):
        self.full_run()
        self.save("sample", record("email_002", "SPAM", "OK"))
        builder = self.load_builder()
        self.assertEqual(builder.build(sample=True)["summary"]["total"], 1)
        self.assertEqual(builder.build()["summary"]["total"], 4)


class ServedFilesTests(ApiCase):
    def test_the_ui_is_served_at_the_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_the_ui_files_are_served_and_always_revalidated(self):
        for url in ("/", "/css/tokens.css", "/js/main.js"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertEqual(response.headers["cache-control"], "no-cache", url)

    def test_the_ui_folders_cannot_be_escaped(self):
        for url in ("/js/../../app/main.py", "/js/%2e%2e/%2e%2e/app/main.py", "/css/../index.html.bak"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_nothing_else_in_web_is_exposed(self):
        for url in ("/build_report.py", "/DESIGN.md", "/report.json", "/README.md", "/../.env"):
            self.assertEqual(self.client.get(url).status_code, 404, url)


if __name__ == "__main__":
    unittest.main()
