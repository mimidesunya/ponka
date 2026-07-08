import csv
import gzip
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from make_tel_data_csv import iter_rows, write_rows  # noqa: E402


class MakeTelDataCsvTest(unittest.TestCase):
    def test_filters_duplicates_and_sorts_by_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.csv.gz"
            output = Path(tmp) / "1963-denwa.csv.gz"
            with gzip.open(source, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(["電話番号", "名前", "都道府県", "市区町村", "町域", "番地"])
                writer.writerow(["06-202-0002", "B", "大阪府", "大阪市北区", "中之島", "3-3"])
                writer.writerow(["06-101-0001", "A", "大阪府", "大阪市東区", "道修", "4-21"])
                writer.writerow(["06-101-0001", "A", "大阪府", "大阪市東区", "道修", "4-21"])
                writer.writerow(["06-2042", "bad", "大阪府", "大阪市東区", "博労町", "2-51"])

            rows, stats = iter_rows(source)
            write_rows(output, rows)

            self.assertEqual(
                rows,
                [
                    ["06-101-0001", "A", "大阪府", "大阪市東区", "道修", "4-21"],
                    ["06-202-0002", "B", "大阪府", "大阪市北区", "中之島", "3-3"],
                ],
            )
            self.assertEqual(stats["skippedInvalidPhones"], 1)
            self.assertEqual(stats["skippedDuplicateRows"], 1)
            with gzip.open(output, "rt", encoding="utf-8", newline="") as handle:
                self.assertEqual(list(csv.reader(handle)), rows)


if __name__ == "__main__":
    unittest.main()
