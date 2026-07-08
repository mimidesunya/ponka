import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from repair_csv_addresses import (  # noqa: E402
    LocationKey,
    address_text_reasons,
    apply_location_corrections,
    select_suspicious_locations,
)


class RepairCsvAddressesTest(unittest.TestCase):
    def test_address_text_reasons_detects_separators_and_municipality_hints(self):
        reasons = address_text_reasons(LocationKey("大阪府", "大阪市北区", "北,堂島船大工"))

        self.assertIn("area_contains_separator", reasons)
        self.assertIn("area_starts_with_municipality_hint", reasons)

    def test_select_suspicious_locations_uses_frequency_and_text_reasons(self):
        rows = []
        rows.extend(
            {
                "電話番号": f"06-000-{index:04d}",
                "名前": "common",
                "都道府県": "大阪府",
                "市区町村": "大阪市北区",
                "町域": "堂島船大工",
                "番地": str(index),
            }
            for index in range(10)
        )
        rows.append(
            {
                "電話番号": "06-999-0001",
                "名前": "rare",
                "都道府県": "大阪府",
                "市区町村": "大阪市北区",
                "町域": "北,堂島船大工",
                "番地": "1",
            }
        )

        suspicious = select_suspicious_locations(
            rows,
            rare_max_count=2,
            common_min_count=8,
            min_similarity=0.5,
            max_candidates=5,
            sample_limit=2,
            max_items=0,
        )

        self.assertEqual(len(suspicious), 1)
        self.assertIn("area_contains_separator", suspicious[0].reasons)
        self.assertEqual(suspicious[0].candidates[0]["address"]["町域"], "堂島船大工")

    def test_apply_location_corrections_preserves_lot_number(self):
        rows = [
            {
                "電話番号": "06-999-0001",
                "名前": "rare",
                "都道府県": "大阪府",
                "市区町村": "大阪市北区",
                "町域": "北,堂島船大工",
                "番地": "1-2",
            }
        ]

        repaired, changed = apply_location_corrections(
            rows,
            {
                LocationKey("大阪府", "大阪市北区", "北,堂島船大工").as_id(): LocationKey(
                    "大阪府", "大阪市北区", "堂島船大工"
                )
            },
        )

        self.assertEqual(changed, 1)
        self.assertEqual(repaired[0]["町域"], "堂島船大工")
        self.assertEqual(repaired[0]["番地"], "1-2")


if __name__ == "__main__":
    unittest.main()
