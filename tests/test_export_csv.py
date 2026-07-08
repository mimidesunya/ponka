import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from export_csv import extract_rows, normalize_phone, resolve_ocr_book_dirs  # noqa: E402


def segment(
    sequence,
    name,
    phones,
    addresses,
    *,
    indent_level=0,
    raw_text="",
):
    return {
        "segmentId": f"0001-01-{sequence:04d}",
        "sequence": sequence,
        "entryType": "directory_entry",
        "rawText": raw_text or f"{name} {' '.join(phones)} {' '.join(addresses)}",
        "cleanText": raw_text or f"{name} {' '.join(phones)} {' '.join(addresses)}",
        "indentLevel": indent_level,
        "startsMidEntry": False,
        "endsMidEntry": False,
        "entryHints": {
            "phone": phones[0] if phones else "",
            "name": name,
            "address": addresses[0] if addresses else "",
        },
        "phones": phones,
        "names": [name] if name else [],
        "addresses": addresses,
        "reviewFlags": [],
        "continuityFromPrevious": {
            "sameEntry": False,
            "previousSegmentId": "",
            "mergedCleanText": "",
            "confidence": 0.0,
            "reason": "",
        },
        "confidence": 1.0,
    }


class ExportCsvTest(unittest.TestCase):
    def test_representative_marker_is_removed(self):
        self.assertEqual(normalize_phone("761-8512代", ""), "06-761-8512")
        self.assertEqual(normalize_phone("761-8512代表", ""), "06-761-8512")

    def test_indent_prefix_and_downward_address_fill(self):
        payload = {
            "segments": [
                segment(
                    1,
                    "関目自動車学校",
                    ["931-1997", "931-3929", "951-4116"],
                    ["城別所201", "城別所200"],
                ),
                segment(
                    2,
                    "連絡所",
                    ["761-8512代"],
                    ["天清水谷西363"],
                    indent_level=1,
                ),
            ]
        }

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            book_dir = Path(directory)
            (book_dir / "0001-01.ocr.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            rows = extract_rows(book_dir)

        self.assertEqual(rows[0], ["06-931-1997", "関目自動車学校", "大阪府", "大阪市城東区", "別所", "201"])
        self.assertEqual(rows[1], ["06-931-3929", "関目自動車学校", "大阪府", "大阪市城東区", "別所", "200"])
        self.assertEqual(rows[2], ["06-951-4116", "関目自動車学校", "大阪府", "大阪市城東区", "別所", "200"])
        self.assertEqual(rows[3][0:2], ["06-761-8512", "関目自動車学校連絡所"])

    def test_entries_without_phone_are_not_exported(self):
        payload = {
            "segments": [
                segment(
                    1,
                    "番号なし商店",
                    [],
                    ["東,内淡路1-28"],
                    raw_text="番号なし商店 東,内淡路1-28",
                ),
                segment(
                    2,
                    "番号あり商店",
                    ["261-0001"],
                    ["東,内淡路1-28"],
                ),
            ]
        }

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            book_dir = Path(directory)
            (book_dir / "0001-01.ocr.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            rows = extract_rows(book_dir)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0:2], ["06-261-0001", "番号あり商店"])

    def test_indent_prefix_continues_across_column_files(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            book_dir = Path(directory)
            (book_dir / "0001-01.ocr.json").write_text(
                json.dumps(
                    {
                        "segments": [
                            segment(
                                1,
                                "朝日自動車株式",
                                [],
                                [],
                                raw_text="朝日自動車株式",
                            )
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (book_dir / "0001-02.ocr.json").write_text(
                json.dumps(
                    {
                        "segments": [
                            segment(
                                1,
                                "本社",
                                ["641-6951"],
                                ["浪大国1-47"],
                                indent_level=1,
                            )
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            rows = extract_rows(book_dir)

        self.assertEqual(rows[0][0:2], ["06-641-6951", "朝日自動車株式本社"])

    def test_resolve_ocr_book_dirs_uses_flat_ocr_root_when_json_is_direct(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            ocr_root = root / "ocr" / "ocr_columns"
            ocr_root.mkdir(parents=True)
            (ocr_root / "0001-01.ocr.json").write_text("{}", encoding="utf-8")

            book_dirs = resolve_ocr_book_dirs(ocr_root, "昭和38年2月1日大阪市50音別電話番号簿")

        self.assertEqual(book_dirs, [(ocr_root, "昭和38年2月1日大阪市50音別電話番号簿")])


if __name__ == "__main__":
    unittest.main()
