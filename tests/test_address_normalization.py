import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ponka.address_normalization import split_address_fields  # noqa: E402


class AddressNormalizationTest(unittest.TestCase):
    def test_short_toyonaka_prefix(self):
        self.assertEqual(
            split_address_fields("豊,中庄内西2"),
            ("大阪府", "豊中市", "中庄内西", "2"),
        )

    def test_ward_prefix_before_comma_inside_area(self):
        self.assertEqual(
            split_address_fields("北堂島船大工、堂栄ビル"),
            ("大阪府", "大阪市北区", "堂島船大工,堂栄ビル", ""),
        )

    def test_ward_prefix_without_separator_keeps_lot_number(self):
        self.assertEqual(
            split_address_fields("北堂島中1-23"),
            ("大阪府", "大阪市北区", "堂島中", "1-23"),
        )

    def test_1968_profile_uses_higashiosaka_for_old_fuse_prefix(self):
        self.assertEqual(
            split_address_fields("布,中小阪483", as_of="1968-03-01"),
            ("大阪府", "東大阪市", "中小阪", "483"),
        )

    def test_1968_profile_uses_new_city_for_kadoma(self):
        self.assertEqual(
            split_address_fields("門真二番", as_of="1968-03-01"),
            ("大阪府", "門真市", "二番", ""),
        )


if __name__ == "__main__":
    unittest.main()
