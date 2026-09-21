"""Tests for the extraction fallback ladder (extract.py) and its pieces.

OCR and both LLM calls are mocked, so these run offline, with no API quota and no
Tesseract installed. Run from the repo root:

    python -m unittest discover -s tests -v
"""
import io
import unittest
from unittest import mock

from PIL import Image

from app.llm_client import LLMUnavailableError
from app.pipeline import extract
from app.pipeline.ocr import OcrLine, Word, keyword_hits
from app.pipeline.read_document import (
    DocumentUnreadableError,
    LoadedDocument,
    load_document,
)
from app.pipeline.validate import validate_field
from app.schema import (
    EmailCategory,
    ExtractionResult,
    FieldIssue,
    FieldIssueReason,
    ReviewReason,
    ShipmentFields,
)


def line(text, conf=95.0, confs=None):
    words = text.split()
    return OcrLine([Word(w, confs[i] if confs else conf) for i, w in enumerate(words)])


def good_lines():
    return [
        line("Shipper: APRIL FAR EAST (M) SDN BHD"),
        line("Consignee: AL GURG STATIONERY LLC"),
        line("Notify: AL GURG STATIONERY LLC"),
        line("Port of Loading: NHAVA SHEVA, INDIA"),
        line("Port of Discharge: TUTICORIN, INDIA"),
        line("Containers: 6 x 40'HC"),
        line("Gross Weight: 128,544 KG"),
    ]


ALL_FIELDS = list(ShipmentFields.model_fields)


def scan():
    return LoadedDocument("attachments/x_SI.pdf", images=[(b"png", "image/png")])


class ValidateTests(unittest.TestCase):
    def test_good_values_pass(self):
        for name, value in [
            ("gross_weight_kg", "131,058 KG"),
            ("gross_weight_kg", "243588"),
            ("gross_weight_kg", "22,825 kgs"),
            ("container_count", "6 x 40'HC"),
            ("container_count", "12"),
            ("shipper", "APRIL FAR EAST (M) SDN BHD"),
            ("consignee", "AL GURG STATIONERY LLC | P.O. BOX 5069; DUBAI, UAE"),
            ("port_of_loading", "NHAVA SHEVA, INDIA"),
        ]:
            self.assertIsNone(validate_field(name, value), (name, value))

    def test_bad_values_fail(self):
        for name, value in [
            ("gross_weight_kg", "____MT"),
            ("gross_weight_kg", "N/A"),
            ("gross_weight_kg", "138 MT"),
            ("gross_weight_kg", "50 KG"),
            ("gross_weight_kg", "99,999,999 KG"),
            ("container_count", "0 x 20'GP"),
            ("container_count", "999"),
            ("container_count", "six"),
            ("shipper", ""),
            ("shipper", "   "),
            ("shipper", None),
            ("port_of_loading", "____MT"),
            ("port_of_discharge", "TBA"),
            ("port_of_discharge", "n/a"),
            ("port_of_loading", "[illegible]"),
            ("consignee", "12345"),
            ("consignee", "AL GURG~STATIONERY"),
        ]:
            self.assertIsNotNone(validate_field(name, value), (name, value))


class ConfidenceTests(unittest.TestCase):
    def test_field_confidence_is_the_minimum_not_the_average(self):
        hits = keyword_hits([line("Gross Weight: 128,544 KG", confs=[97, 97, 96, 41, 99])])
        # value words are "128,544" (96) "KG" (41)... the weakest word wins
        self.assertEqual(hits["gross_weight_kg"].confidence, 41)

    def test_label_variants_map_to_the_same_field(self):
        for text, field in [
            ("Port of Loading (POL): NANTONG", "port_of_loading"),
            ("Load Port: NANTONG", "port_of_loading"),
            ("POD: KARACHI", "port_of_discharge"),
            ("Gross Wt (kgs): 131,058 KG", "gross_weight_kg"),
            ("TOTAL Gross Weight (KG): 131,058 KG", "gross_weight_kg"),
            ("Consignee (Non-Negotiable): ACME", "consignee"),
            ("To the Order of: ACME", "consignee"),
            ("Gross Weight毛重: 5,000 KG", "gross_weight_kg"),
        ]:
            self.assertIn(field, keyword_hits([line(text)]), text)

    def test_unknown_label_and_labelless_line_are_not_found(self):
        self.assertEqual(keyword_hits([line("Vessel: NAP 914"), line("Shipper")]), {})

    def test_evidence_is_the_whole_ocr_line(self):
        hit = keyword_hits([line("Shipper: ACME LTD")])["shipper"]
        self.assertEqual(hit.evidence, "Shipper: ACME LTD")
        self.assertEqual(hit.value, "ACME LTD")


class OcrSetupTests(unittest.TestCase):
    def test_ocr_lines_finds_tesseract_itself_instead_of_relying_on_the_caller(self):
        # Locating the executable (TESSERACT_CMD) happens in ocr_available(); a caller
        # that goes straight to ocr_lines() must still get that setup.
        from app.pipeline import ocr

        with mock.patch.object(ocr, "ocr_available", return_value=False) as available:
            with self.assertRaises(RuntimeError):
                ocr.ocr_lines(b"not an image")
        available.assert_called_once()


class ScannedLadderTests(unittest.TestCase):
    def run_ladder(self, lines, vision=None, text_llm=None, engine=True):
        vision_mock = mock.Mock(side_effect=vision if callable(vision) else None,
                                return_value=None if callable(vision) else (vision or {}))
        text_mock = mock.Mock(return_value=text_llm or ShipmentFields())
        with mock.patch.multiple(
            extract,
            ocr_available=mock.Mock(return_value=engine),
            ocr_lines=mock.Mock(return_value=lines),
            call_vision_json=vision_mock,
            extract_fields=text_mock,
        ):
            result = extract._extract_scanned(scan(), "SI")
        return result, vision_mock, text_mock

    def test_confident_and_valid_needs_no_llm_at_all(self):
        result, vision, text = self.run_ladder(good_lines())
        self.assertEqual(result.issues, [])
        self.assertEqual(set(result.sources.values()), {"ocr"})
        self.assertEqual(result.fields.gross_weight_kg, "128,544 KG")
        vision.assert_not_called()
        text.assert_not_called()

    def test_one_bad_character_sends_only_that_field_to_vision(self):
        lines = good_lines()
        lines[6] = line("Gross Weight: 128,544 KG", confs=[97, 97, 96, 42, 99])
        result, vision, text = self.run_ladder(lines, vision={"gross_weight_kg": "128,544 KG"})
        vision.assert_called_once()
        self.assertIn("gross_weight_kg", vision.call_args.args[1])
        self.assertNotIn("shipper", vision.call_args.args[1])
        text.assert_not_called()  # low confidence is NOT re-parsed from the OCR text
        self.assertEqual(result.sources["gross_weight_kg"], "vision")
        self.assertEqual(result.sources["shipper"], "ocr")
        self.assertEqual(result.issues, [])

    def test_unknown_label_on_a_clean_page_uses_the_text_llm(self):
        lines = [l for l in good_lines() if not l.text.startswith("Notify")]
        lines.append(line("Intermediate Party AL GURG STATIONERY LLC"))
        result, vision, text = self.run_ladder(
            lines, text_llm=ShipmentFields(notify_party="AL GURG STATIONERY LLC")
        )
        text.assert_called_once()
        vision.assert_not_called()
        self.assertEqual(result.sources["notify_party"], "ocr_llm")
        self.assertEqual(result.issues, [])

    def test_unknown_label_on_a_poor_page_goes_to_vision_not_the_text_llm(self):
        lines = [l for l in good_lines() if not l.text.startswith("Notify")]
        lines.append(line("smudge " * 40, conf=10.0))  # drags page quality below 80
        result, vision, text = self.run_ladder(
            lines, vision={"notify_party": "AL GURG STATIONERY LLC"}
        )
        text.assert_not_called()
        vision.assert_called_once()
        self.assertEqual(result.sources["notify_party"], "vision")

    def test_text_llm_saying_null_on_a_clean_page_is_a_not_found_issue(self):
        lines = [l for l in good_lines() if not l.text.startswith("Notify")]
        result, vision, _ = self.run_ladder(lines, text_llm=ShipmentFields())
        vision.assert_not_called()
        [issue] = result.issues
        self.assertEqual(issue.field, "notify_party")
        self.assertEqual(issue.reason, FieldIssueReason.NOT_FOUND)

    def test_text_llm_value_failing_validation_falls_to_vision(self):
        lines = [l for l in good_lines() if not l.text.startswith("Gross")]
        result, vision, _ = self.run_ladder(
            lines,
            text_llm=ShipmentFields(gross_weight_kg="____MT"),
            vision={"gross_weight_kg": "128,544 KG"},
        )
        vision.assert_called_once()
        self.assertEqual(result.sources["gross_weight_kg"], "vision")

    def test_invalid_ocr_value_goes_to_vision_even_at_high_confidence(self):
        lines = good_lines()
        lines[6] = line("Gross Weight: ____MT", conf=99.0)
        result, vision, _ = self.run_ladder(lines, vision={"gross_weight_kg": "128,544 KG"})
        vision.assert_called_once()
        self.assertEqual(result.fields.gross_weight_kg, "128,544 KG")

    def test_vision_reading_nothing_is_an_unreadable_issue_with_evidence(self):
        lines = good_lines()
        lines[6] = line("Gross Weight: ____MT", conf=99.0)
        result, _, _ = self.run_ladder(lines, vision={"gross_weight_kg": None})
        [issue] = result.issues
        self.assertEqual(issue.reason, FieldIssueReason.UNREADABLE)
        self.assertEqual(issue.evidence, "Gross Weight: ____MT")
        self.assertEqual(issue.value, "____MT")
        self.assertEqual(issue.document, "SI")
        self.assertEqual(issue.file, "attachments/x_SI.pdf")
        self.assertIsNone(result.fields.gross_weight_kg)  # never guessed

    def test_vision_value_failing_validation_is_an_invalid_value_issue(self):
        lines = good_lines()
        lines[6] = line("Gross Weight: 128,544 KG", confs=[97, 97, 96, 30, 99])
        result, _, _ = self.run_ladder(lines, vision={"gross_weight_kg": "N/A"})
        [issue] = result.issues
        self.assertEqual(issue.reason, FieldIssueReason.INVALID_VALUE)
        self.assertEqual(issue.value, "N/A")
        self.assertIn("OCR confidence 30", issue.detail)  # the route taken is recorded

    def test_no_ocr_engine_sends_every_field_to_vision_in_one_call(self):
        replies = {name: "APRIL" for name in ALL_FIELDS}
        replies.update(container_count="6 x 40'HC", gross_weight_kg="128,544 KG")
        result, vision, text = self.run_ladder([], vision=replies, engine=False)
        vision.assert_called_once()
        for name in ALL_FIELDS:
            self.assertIn(name, vision.call_args.args[1])
        text.assert_not_called()
        self.assertEqual(set(result.sources.values()), {"vision"})
        self.assertEqual(result.issues, [])

    def test_api_failure_propagates_instead_of_becoming_a_verdict(self):
        with self.assertRaises(LLMUnavailableError):
            self.run_ladder([], vision=mock.Mock(side_effect=LLMUnavailableError("429")),
                            engine=False)

    def test_confidence_threshold_is_configurable(self):
        lines = good_lines()
        lines[0] = line("Shipper: APRIL FAR EAST", conf=70.0)
        with mock.patch.dict("os.environ", {"OCR_MIN_CONFIDENCE": "60"}):
            result, vision, _ = self.run_ladder(lines)
        vision.assert_not_called()
        self.assertEqual(result.sources["shipper"], "ocr")


class TextLadderTests(unittest.TestCase):
    CLEAN = "Shipper: ACME LTD\nGross Wt: 131,058 KG\n"

    def run_text(self, fields, text=CLEAN):
        doc = LoadedDocument("attachments/x_BL.txt", text=text)
        with mock.patch.object(extract, "extract_fields", return_value=fields), \
                mock.patch.object(extract, "call_vision_json") as vision:
            result = extract._extract_text(doc, "BL")
        vision.assert_not_called()  # a text document has no image to fall back to
        return result

    def valid(self, **overrides):
        base = dict(shipper="ACME LTD", consignee="BOB LLC", notify_party="BOB LLC",
                    port_of_loading="SINGAPORE", port_of_discharge="KARACHI",
                    container_count="6 x 40'HC", gross_weight_kg="131,058 KG")
        return ShipmentFields(**{**base, **overrides})

    def test_valid_document_is_accepted_untouched(self):
        result = self.run_text(self.valid())
        self.assertEqual(result.issues, [])
        self.assertEqual(set(result.sources.values()), {"text"})

    def test_placeholder_weight_is_an_invalid_value_issue(self):
        blank = "Shipper: ACME LTD\nGross Wt: ____MT\n"
        [issue] = self.run_text(self.valid(gross_weight_kg="____MT"), text=blank).issues
        self.assertEqual(issue.reason, FieldIssueReason.INVALID_VALUE)
        self.assertEqual(issue.field, "gross_weight_kg")
        self.assertEqual(issue.document, "BL")
        self.assertIn("____MT", issue.evidence)

    def test_missing_field_is_a_not_found_issue(self):
        [issue] = self.run_text(self.valid(notify_party=None)).issues
        self.assertEqual(issue.reason, FieldIssueReason.NOT_FOUND)

    def run_text_of(self, text, fields):
        doc = LoadedDocument("attachments/x_SI.txt", text=text)
        with mock.patch.object(extract, "extract_fields", return_value=fields):
            return extract._extract_text(doc, "SI")

    def test_model_tidying_a_blank_into_a_value_is_caught_by_the_source_line(self):
        # The model turned "____MT" into "MT", which passes validation on its own.
        text = (
            "Shipper: ACME LTD\n"
            "Port of Loading (POL): ____MT\n"
            "Port of Discharge (POD): KARACHI\n"
        )
        [issue] = self.run_text_of(text, self.valid(port_of_loading="MT")).issues
        self.assertEqual(issue.field, "port_of_loading")
        self.assertEqual(issue.reason, FieldIssueReason.INVALID_VALUE)
        self.assertEqual(issue.value, "MT")
        self.assertIn("____MT", issue.detail)
        self.assertEqual(issue.evidence, "Port of Loading (POL): ____MT")

    def test_placeholder_the_model_passed_through_is_rejected(self):
        text = "Port of Discharge (POD): TBA\n"
        [issue] = self.run_text_of(text, self.valid(port_of_discharge="TBA")).issues
        self.assertIn("placeholder", issue.detail)

    def test_not_found_evidence_is_the_fields_own_line(self):
        text = "SHIPPING INSTRUCTION\n=====\nGROSS WEIGHT: \nShipper: ACME LTD\n"
        [issue] = self.run_text_of(text, self.valid(gross_weight_kg=None)).issues
        self.assertEqual(issue.reason, FieldIssueReason.NOT_FOUND)
        self.assertEqual(issue.evidence, "GROSS WEIGHT:")

    def test_table_rows_are_cross_checked_too(self):
        # .xlsx / .docx tables are flattened to "Label | value"
        text = "Shipper | ACME LTD\nGROSS WEIGHT | ____MT\n"
        [issue] = self.run_text_of(text, self.valid(gross_weight_kg="131,058 KG")).issues
        self.assertEqual(issue.field, "gross_weight_kg")

    def test_a_label_with_its_value_on_the_next_line_is_not_a_false_alarm(self):
        text = "Shipper\nACME LTD\nGROSS WEIGHT (KG)\n131,058\n"
        self.assertEqual(self.run_text_of(text, self.valid()).issues, [])


class LoadDocumentTests(unittest.TestCase):
    class Inbox:
        def __init__(self, data):
            self.data = data

        def read_bytes(self, path):
            return self.data

    def image_bytes(self, fmt, frames=1):
        pages = [Image.new("RGB", (30, 30), "white") for _ in range(frames)]
        buffer = io.BytesIO()
        pages[0].save(buffer, fmt, save_all=frames > 1, append_images=pages[1:])
        return buffer.getvalue()

    def test_image_formats_are_routed_to_ocr(self):
        for suffix, fmt in [("png", "PNG"), ("jpg", "JPEG"), ("tiff", "TIFF")]:
            document = load_document(self.Inbox(self.image_bytes(fmt)), f"a/x_SI.{suffix}")
            self.assertTrue(document.scanned, suffix)
            self.assertEqual(document.text, "")

    def test_multi_page_tiff_yields_every_page(self):
        document = load_document(self.Inbox(self.image_bytes("TIFF", frames=2)), "a/x.tif")
        self.assertEqual(len(document.images), 2)

    def test_corrupt_pdf_is_unreadable(self):
        with self.assertRaises(DocumentUnreadableError):
            load_document(self.Inbox(b"%PDF-1.4 truncated"), "a/x_BL.pdf")

    def test_empty_and_unsupported_files_are_unreadable(self):
        with self.assertRaises(DocumentUnreadableError):
            load_document(self.Inbox(b"   \n"), "a/x_SI.txt")
        with self.assertRaises(DocumentUnreadableError):
            load_document(self.Inbox(b"MZ"), "a/x_SI.exe")

    def test_text_file_is_not_scanned(self):
        document = load_document(self.Inbox(b"Shipper: ACME"), "a/x_SI.txt")
        self.assertFalse(document.scanned)


class RunIntegrationTests(unittest.TestCase):
    def process(self, si, bl):
        from app.pipeline import run

        email = {"email_id": "email_1", "attachments": ["a/e_SI.pdf", "a/e_BL.pdf"]}
        with mock.patch.object(run, "classify_email",
                               return_value=(EmailCategory.BL_COMPARISON, 0.9)), \
                mock.patch.object(run, "extract_document", side_effect=[si, bl]):
            return run, run.process_email(email, inbox=None)

    def fields(self, **overrides):
        base = dict(shipper="ACME", consignee="BOB", notify_party="BOB",
                    port_of_loading="SG", port_of_discharge="KHI",
                    container_count="6 x 40'HC", gross_weight_kg="131,058 KG")
        return ShipmentFields(**{**base, **overrides})

    def test_unresolved_field_sends_the_email_to_review_with_its_evidence(self):
        issue = FieldIssue(document="BL", file="a/e_BL.pdf", field="gross_weight_kg",
                           reason=FieldIssueReason.UNREADABLE, detail="d", source="vision",
                           value="____MT", evidence="Gross Weight: ____MT")
        si = ExtractionResult(file="a/e_SI.pdf", fields=self.fields())
        bl = ExtractionResult(file="a/e_BL.pdf", fields=self.fields(gross_weight_kg=None),
                              issues=[issue])
        run, result = self.process(si, bl)
        self.assertTrue(result.needs_review)
        self.assertEqual(result.review_reason, ReviewReason.MISSING_VALUE)
        self.assertEqual(result.field_issues, [issue])
        record = run._record(result)
        self.assertEqual(record["status"], "NEEDS_REVIEW")
        self.assertEqual(record["field_issues"][0]["evidence"], "Gross Weight: ____MT")
        # the submission keeps the hackathon shape: evidence stays out of it
        self.assertEqual(set(result.to_submission()), set(run.SUBMISSION_KEYS))

    def test_all_resolved_goes_on_to_compare(self):
        si = ExtractionResult(file="a", fields=self.fields())
        bl = ExtractionResult(file="b", fields=self.fields(gross_weight_kg="131,059 KG"))
        _, result = self.process(si, bl)
        self.assertFalse(result.needs_review)
        self.assertTrue(result.mismatch_found)
        self.assertEqual(list(result.mismatches), ["gross_weight_kg"])


if __name__ == "__main__":
    unittest.main()
