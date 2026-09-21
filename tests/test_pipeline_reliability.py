import json
import unittest
from unittest.mock import patch

from app.pipeline import run
from app.schema import ComparisonResult, EmailCategory, ReviewReason, ShipmentFields


class FakeInbox:
    def __init__(self, emails):
        self._emails = emails

    def emails(self):
        return self._emails

    def read_bytes(self, _path):
        return b"document text"


class MemoryCheckpoint:
    def __init__(self, contents=""):
        self.contents = contents

    def exists(self):
        return True

    def read_text(self):
        return self.contents

    def write_text(self, contents):
        self.contents = contents

    def open(self, mode):
        if mode != "a":
            raise ValueError("MemoryCheckpoint only supports append mode")
        checkpoint = self

        class Appender:
            def __enter__(self):
                return self

            def write(self, contents):
                checkpoint.contents += contents

            def __exit__(self, exc_type, exc, traceback):
                return False

        return Appender()


def comparison_email(email_id="email_004", suffix="txt"):
    return {
        "email_id": email_id,
        "attachments": [
            f"attachments/{email_id}_SI.{suffix}",
            f"attachments/{email_id}_BL.{suffix}",
        ],
    }


class PipelineReliabilityTests(unittest.TestCase):
    def test_one_failed_email_does_not_stop_the_next(self):
        emails = [
            {"email_id": "email_001", "attachments": []},
            {"email_id": "email_002", "attachments": []},
        ]

        def process(email, _inbox):
            if email["email_id"] == "email_001":
                raise RuntimeError("private document content")
            return ComparisonResult(
                email_id="email_002",
                category=EmailCategory.GENERAL,
            )

        with patch.object(run, "process_email", side_effect=process):
            with self.assertLogs("app.pipeline.run", level="INFO") as logs:
                submission, _cache = run.run_pipeline(
                    FakeInbox(emails),
                    concurrency=1,
                )

        self.assertEqual(list(submission), ["email_001", "email_002"])
        self.assertEqual(submission["email_001"]["status"], "NEEDS_REVIEW")
        self.assertEqual(
            submission["email_001"]["review_reason"], "processing_error"
        )
        self.assertEqual(submission["email_002"]["status"], "OK")
        self.assertEqual(set(submission["email_001"]), set(run.SUBMISSION_KEYS))
        failure_log = next(
            record for record in logs.records if record.msg == "email_stage_failed"
        )
        self.assertEqual(failure_log.email_id, "email_001")
        self.assertEqual(failure_log.processing_stage, "email_boundary")
        self.assertNotIn("private document content", "\n".join(logs.output))

    def test_malformed_classification_becomes_controlled_review(self):
        email = {"email_id": "email_003", "attachments": []}

        with patch.object(run, "classify_email", side_effect=ValueError("bad JSON")):
            result = run.process_email(email, FakeInbox([email]))

        self.assertTrue(result.needs_review)
        self.assertEqual(result.review_reason, ReviewReason.PROCESSING_ERROR)
        self.assertEqual(result.failure_stage, "classification")

    def test_provider_failure_during_classification_is_processing_error(self):
        email = {"email_id": "email_provider_classify", "attachments": []}

        with patch.object(
            run,
            "classify_email",
            side_effect=run.LLMUnavailableError("provider unavailable"),
        ):
            result = run.process_email(email, FakeInbox([email]))

        self.assertEqual(result.review_reason, ReviewReason.PROCESSING_ERROR)
        self.assertEqual(result.failure_stage, "classification")

    def test_malformed_extraction_is_not_retried_by_pipeline(self):
        email = comparison_email()

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.BL_COMPARISON, 0.9),
        ):
            with patch.object(run, "read_document", return_value="document text"):
                with patch.object(
                    run,
                    "extract_fields",
                    side_effect=ValueError("malformed model output"),
                ) as extract:
                    result = run.process_email(email, FakeInbox([email]))

        self.assertEqual(extract.call_count, 1)
        self.assertTrue(result.needs_review)
        self.assertEqual(result.review_reason, ReviewReason.UNREADABLE)
        self.assertEqual(result.failure_stage, "si_extraction")

    def test_provider_failure_during_extraction_is_processing_error(self):
        email = comparison_email("email_provider_extract")

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.BL_COMPARISON, 0.9),
        ):
            with patch.object(run, "read_document", return_value="document text"):
                with patch.object(
                    run,
                    "extract_fields",
                    side_effect=run.LLMUnavailableError("provider unavailable"),
                ) as extract:
                    result = run.process_email(email, FakeInbox([email]))

        self.assertEqual(extract.call_count, 1)
        self.assertEqual(result.review_reason, ReviewReason.PROCESSING_ERROR)
        self.assertEqual(result.failure_stage, "si_extraction")

    def test_provider_failure_during_ocr_is_processing_error(self):
        email = comparison_email("email_provider_ocr", "pdf")

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.BL_COMPARISON, 0.9),
        ):
            with patch.object(
                run,
                "read_document",
                side_effect=run.LLMUnavailableError("vision provider unavailable"),
            ) as reader:
                with patch.object(run, "extract_fields") as extract:
                    result = run.process_email(email, FakeInbox([email]))

        self.assertEqual(reader.call_count, 1)
        extract.assert_not_called()
        self.assertEqual(result.review_reason, ReviewReason.PROCESSING_ERROR)
        self.assertEqual(result.failure_stage, "si_extraction")

    def test_unsupported_document_is_unreadable_without_model_retry(self):
        email = comparison_email("unsupported", "zip")

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.BL_COMPARISON, 0.9),
        ):
            with patch.object(
                run,
                "read_document",
                side_effect=ValueError("unsupported file type"),
            ) as reader:
                with patch.object(run, "extract_fields") as extract:
                    result = run.process_email(email, FakeInbox([email]))

        self.assertEqual(reader.call_count, 1)
        extract.assert_not_called()
        self.assertEqual(result.review_reason, ReviewReason.UNREADABLE)
        self.assertEqual(result.failure_stage, "si_extraction")

    def test_missing_attachment_is_identified_before_document_read(self):
        email = {"email_id": "missing", "attachments": []}

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.BL_COMPARISON, 0.9),
        ):
            with patch.object(run, "read_document") as reader:
                result = run.process_email(email, FakeInbox([email]))

        reader.assert_not_called()
        self.assertEqual(result.review_reason, ReviewReason.MISSING_ATTACHMENT)
        self.assertEqual(result.failure_stage, "attachment_identification")

    def test_comparison_failure_becomes_controlled_review(self):
        email = comparison_email("email_compare")
        fields = ShipmentFields(
            shipper="A",
            consignee="B",
            notify_party="C",
            port_of_loading="D",
            port_of_discharge="E",
            container_count="1",
            gross_weight_kg="2",
        )

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.BL_COMPARISON, 0.9),
        ):
            with patch.object(run, "read_document", return_value="document text"):
                with patch.object(run, "extract_fields", return_value=fields):
                    with patch.object(
                        run,
                        "compare_fields",
                        side_effect=RuntimeError("private comparison detail"),
                    ):
                        result = run.process_email(email, FakeInbox([email]))

        self.assertEqual(result.review_reason, ReviewReason.PROCESSING_ERROR)
        self.assertEqual(result.failure_stage, "comparison")

    def test_missing_email_id_is_contained_at_email_boundary(self):
        malformed = {"subject": "missing id", "attachments": []}
        good = {"email_id": "email_006", "attachments": []}

        with patch.object(
            run,
            "process_email",
            return_value=ComparisonResult(
                email_id="email_006", category=EmailCategory.GENERAL
            ),
        ) as process:
            submission, _cache = run.run_pipeline(
                FakeInbox([malformed, good]), concurrency=1
            )

        self.assertEqual(submission["invalid_email_0000"]["status"], "NEEDS_REVIEW")
        self.assertEqual(submission["email_006"]["status"], "OK")
        process.assert_called_once()

    def test_non_mapping_email_is_contained_at_email_boundary(self):
        good = {"email_id": "email_008", "attachments": []}

        def process(email, _inbox):
            return ComparisonResult(
                email_id=email["email_id"], category=EmailCategory.GENERAL
            )

        with patch.object(run, "process_email", side_effect=process):
            submission, _cache = run.run_pipeline(
                FakeInbox([None, good]), concurrency=1
            )

        self.assertEqual(submission["invalid_email_0000"]["status"], "NEEDS_REVIEW")
        self.assertEqual(submission["email_008"]["status"], "OK")

    def test_blank_and_non_string_ids_are_contained_with_concurrency(self):
        emails = [
            {"email_id": "", "attachments": []},
            {"email_id": 123, "attachments": []},
            {"email_id": "email_010", "attachments": []},
        ]

        with patch.object(
            run,
            "classify_email",
            return_value=(EmailCategory.GENERAL, 0.9),
        ) as classify:
            submission, _cache = run.run_pipeline(
                FakeInbox(emails), concurrency=3
            )

        self.assertEqual(
            list(submission),
            ["invalid_email_0000", "invalid_email_0001", "email_010"],
        )
        self.assertEqual(submission["invalid_email_0000"]["status"], "NEEDS_REVIEW")
        self.assertEqual(submission["invalid_email_0001"]["status"], "NEEDS_REVIEW")
        self.assertEqual(submission["email_010"]["status"], "OK")
        self.assertEqual(classify.call_count, 1)

    def test_provider_failure_in_one_email_does_not_stop_next_email(self):
        emails = [
            {"email_id": "email_outage", "attachments": []},
            {"email_id": "email_healthy", "attachments": []},
        ]

        def classify(email):
            if email["email_id"] == "email_outage":
                raise run.LLMUnavailableError("provider unavailable")
            return EmailCategory.GENERAL, 0.9

        with patch.object(run, "classify_email", side_effect=classify):
            submission, _cache = run.run_pipeline(
                FakeInbox(emails), concurrency=2
            )

        self.assertEqual(submission["email_outage"]["status"], "NEEDS_REVIEW")
        self.assertEqual(
            submission["email_outage"]["review_reason"], "processing_error"
        )
        self.assertEqual(submission["email_healthy"]["status"], "OK")

    def test_wrong_result_email_id_cannot_break_final_assembly(self):
        email = {"email_id": "scheduled", "attachments": []}

        with patch.object(
            run,
            "process_email",
            return_value=ComparisonResult(
                email_id="wrong", category=EmailCategory.GENERAL
            ),
        ):
            submission, _cache = run.run_pipeline(FakeInbox([email]), concurrency=1)

        self.assertEqual(list(submission), ["scheduled"])
        self.assertEqual(submission["scheduled"]["status"], "NEEDS_REVIEW")

    def test_resume_skips_success_and_retries_processing_error(self):
        success = run._record(
            ComparisonResult(
                email_id="email_done",
                category=EmailCategory.GENERAL,
            )
        )
        failure = run._record(
            run._processing_error("email_retry", "classification")
        )
        checkpoint = MemoryCheckpoint(
            "\n".join((json.dumps(success), json.dumps(failure))) + "\n"
        )
        emails = [
            {"email_id": "email_done", "attachments": []},
            {"email_id": "email_retry", "attachments": []},
        ]

        with patch.object(
            run,
            "process_email",
            return_value=ComparisonResult(
                email_id="email_retry",
                category=EmailCategory.GENERAL,
            ),
        ) as process:
            submission, _cache = run.run_pipeline(
                FakeInbox(emails),
                checkpoint_path=checkpoint,
                resume=True,
                concurrency=2,
            )

        process.assert_called_once()
        self.assertEqual(process.call_args.args[0]["email_id"], "email_retry")
        self.assertEqual(submission["email_done"]["status"], "OK")
        self.assertEqual(submission["email_retry"]["status"], "OK")
        checkpoint_records = [
            json.loads(line) for line in checkpoint.contents.splitlines()
        ]
        self.assertEqual(checkpoint_records[-1]["email_id"], "email_retry")
        self.assertEqual(checkpoint_records[-1]["status"], "OK")

    def test_failure_stage_never_changes_evaluator_output_shape(self):
        result = run._processing_error("email_shape", "classification")

        self.assertEqual(set(result.to_submission()), set(run.SUBMISSION_KEYS))
        self.assertNotIn("failure_stage", result.to_submission())


if __name__ == "__main__":
    unittest.main()
