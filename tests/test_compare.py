import unittest

from app.pipeline.compare import compare_fields
from app.schema import ShipmentFields


def fields(**overrides) -> ShipmentFields:
    base = dict(
        shipper="ACME LTD",
        consignee="GLOBAL IMPORTS",
        notify_party="GLOBAL IMPORTS",
        port_of_loading="NHAVA SHEVA",
        port_of_discharge="ROTTERDAM",
        container_count="6",
        gross_weight_kg="131058 KG",
    )
    base.update(overrides)
    return ShipmentFields(**base)


class NumericFieldTests(unittest.TestCase):
    """container_count and gross_weight_kg compare as numbers, not normalized text."""

    def test_container_count_with_extra_detail_is_not_a_mismatch(self):
        si = fields(container_count="6 x 40'HC")
        bl = fields(container_count="6")
        self.assertNotIn("container_count", compare_fields(si, bl))

    def test_gross_weight_with_a_thousands_comma_and_decimal_is_not_a_mismatch(self):
        si = fields(gross_weight_kg="131,058.00 KG")
        bl = fields(gross_weight_kg="131058 KG")
        self.assertNotIn("gross_weight_kg", compare_fields(si, bl))

    def test_a_genuine_container_count_mismatch_is_still_flagged(self):
        si = fields(container_count="6 x 40'HC")
        bl = fields(container_count="5")
        mismatches = compare_fields(si, bl)
        self.assertEqual(mismatches["container_count"], {"si": "6 x 40'HC", "bl": "5"})

    def test_a_genuine_gross_weight_mismatch_is_still_flagged(self):
        si = fields(gross_weight_kg="131,058.00 KG")
        bl = fields(gross_weight_kg="140000 KG")
        mismatches = compare_fields(si, bl)
        self.assertEqual(mismatches["gross_weight_kg"], {"si": "131,058.00 KG", "bl": "140000 KG"})

    def test_a_value_that_does_not_parse_as_a_number_falls_back_to_text_comparison(self):
        si = fields(container_count="TBD")
        bl = fields(container_count="TBD")
        self.assertNotIn("container_count", compare_fields(si, bl))

    def test_one_side_unparseable_still_compares_and_can_mismatch(self):
        si = fields(gross_weight_kg="approx 131058 KG")
        bl = fields(gross_weight_kg="140000 KG")
        # "approx 131058 KG" does not match the anchored weight pattern, so this
        # falls back to normalized text comparison, which still differs.
        self.assertIn("gross_weight_kg", compare_fields(si, bl))


class ExistingNormalizationTests(unittest.TestCase):
    """Lock in the normalization behavior compare_fields already had."""

    def test_identical_fields_produce_no_mismatches(self):
        self.assertEqual(compare_fields(fields(), fields()), {})

    def test_case_and_spacing_differences_are_not_mismatches(self):
        si = fields(port_of_loading="Nhava Sheva")
        bl = fields(port_of_loading="  NHAVA   SHEVA  ")
        self.assertNotIn("port_of_loading", compare_fields(si, bl))

    def test_address_separators_do_not_count_as_a_difference(self):
        si = fields(consignee="GLOBAL IMPORTS, 1 MAIN ST; SUITE 2")
        bl = fields(consignee="GLOBAL IMPORTS | 1 MAIN ST | SUITE 2")
        self.assertNotIn("consignee", compare_fields(si, bl))

    def test_kg_unit_variants_do_not_count_as_a_difference_once_numeric(self):
        si = fields(gross_weight_kg="131058 KGS")
        bl = fields(gross_weight_kg="131058 KG")
        self.assertNotIn("gross_weight_kg", compare_fields(si, bl))

    def test_party_field_matches_when_one_side_adds_an_address(self):
        si = fields(notify_party="GLOBAL IMPORTS")
        bl = fields(notify_party="GLOBAL IMPORTS, 1 MAIN ST, ROTTERDAM")
        self.assertNotIn("notify_party", compare_fields(si, bl))

    def test_a_genuine_party_mismatch_with_no_shared_prefix_is_flagged(self):
        si = fields(consignee="GLOBAL IMPORTS")
        bl = fields(consignee="OCEAN LOGISTICS")
        self.assertIn("consignee", compare_fields(si, bl))

    def test_none_values_on_both_sides_are_not_a_mismatch(self):
        si = fields(notify_party=None)
        bl = fields(notify_party=None)
        self.assertNotIn("notify_party", compare_fields(si, bl))

    def test_a_missing_value_on_one_side_is_flagged(self):
        si = fields(port_of_discharge=None)
        bl = fields(port_of_discharge="ROTTERDAM")
        self.assertIn("port_of_discharge", compare_fields(si, bl))


if __name__ == "__main__":
    unittest.main()
