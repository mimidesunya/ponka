import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ocr_columns import (  # noqa: E402
    ColumnImage,
    PreparedOcrRequest,
    build_gcs_generate_content_request,
    normalize_segments,
    output_key_from_gcs_output,
    process_completed_batch_job,
    resolve_ocr_jobs,
    write_prepared_output,
)


class OcrColumnsTest(unittest.TestCase):
    def test_normalize_compact_segments_to_standard_shape(self):
        payload = {
            "r": [
                {
                    "t": "d",
                    "x": "アサヒスポーツ 391-1214 豊,中庄内西2",
                    "i": 1,
                    "p": ["391-1214"],
                    "n": ["アサヒスポーツ"],
                    "a": ["豊,中庄内西2"],
                    "f": [],
                }
            ]
        }

        normalized = normalize_segments(payload, page=37, column=1)

        self.assertEqual(len(normalized["segments"]), 1)
        segment = normalized["segments"][0]
        self.assertEqual(segment["segmentId"], "0037-01-0001")
        self.assertEqual(segment["entryType"], "directory_entry")
        self.assertEqual(segment["cleanText"], "アサヒスポーツ 391-1214 豊,中庄内西2")
        self.assertEqual(segment["rawText"], segment["cleanText"])
        self.assertEqual(segment["indentLevel"], 1)
        self.assertEqual(segment["entryHints"]["phone"], "391-1214")
        self.assertEqual(segment["entryHints"]["name"], "アサヒスポーツ")
        self.assertEqual(segment["entryHints"]["address"], "豊,中庄内西2")
        self.assertEqual(segment["confidence"], 1.0)

    def test_normalize_compact_segments_adds_multi_phone_flag(self):
        payload = {
            "r": [
                {
                    "t": "d",
                    "x": "関目自動車学校 931-3929 931-8445 城東,別所200",
                    "i": 0,
                    "p": ["931-3929", "931-8445"],
                    "n": ["関目自動車学校"],
                    "a": ["城東,別所200"],
                }
            ]
        }

        segment = normalize_segments(payload, page=31, column=4)["segments"][0]

        self.assertEqual(segment["phones"], ["931-3929", "931-8445"])
        self.assertIn("multi_phone", segment["reviewFlags"])

    def test_normalize_slim_segments_to_standard_shape(self):
        payload = {
            "segments": [
                {
                    "entryType": "directory_entry",
                    "cleanText": "アトリエジュン 312-2551 北,堂島船大工堂栄ビル",
                    "indentLevel": 0,
                    "phones": ["312-2551"],
                    "names": ["アトリエジュン"],
                    "addresses": ["北,堂島船大工堂栄ビル"],
                    "reviewFlags": [],
                }
            ]
        }

        segment = normalize_segments(payload, page=37, column=2)["segments"][0]

        self.assertEqual(segment["segmentId"], "0037-02-0001")
        self.assertEqual(segment["entryHints"]["phone"], "312-2551")
        self.assertEqual(segment["entryHints"]["name"], "アトリエジュン")
        self.assertEqual(segment["entryHints"]["address"], "北,堂島船大工堂栄ビル")
        self.assertEqual(segment["rawText"], "")

    def test_write_prepared_output_does_not_overwrite_existing_json(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            output_path = root / "0001-01.ocr.json"
            output_path.write_text("existing", encoding="utf-8")
            prepared = PreparedOcrRequest(
                column_image=ColumnImage(
                    book_name="book",
                    page=1,
                    column=1,
                    path=root / "0001-01.webp",
                ),
                output_path=output_path,
                image_sha256="",
                request=None,
            )

            written = write_prepared_output(prepared, {"segments": []}, "model", "compact")

            self.assertFalse(written)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing")

    def test_resolve_ocr_jobs_uses_flat_split_root_when_metadata_is_direct(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            split_root = root / "ocr" / "split"
            ocr_root = root / "ocr" / "ocr_columns"
            split_root.mkdir(parents=True)
            (split_root / "column_count.json").write_text("{}", encoding="utf-8")

            jobs = resolve_ocr_jobs(split_root, ocr_root, "昭和38年2月1日大阪市50音別電話番号簿")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].book_dir, split_root)
        self.assertEqual(jobs[0].target_dir, ocr_root)
        self.assertEqual(jobs[0].book_name, "昭和38年2月1日大阪市50音別電話番号簿")

    def test_build_gcs_generate_content_request_uses_file_data(self):
        image = ColumnImage(
            book_name="book",
            page=1,
            column=2,
            path=Path("0001-02.webp"),
        )

        request = build_gcs_generate_content_request(
            image,
            "compact",
            "gs://bucket/images/0001-02.webp",
        )

        parts = request["contents"][0]["parts"]
        self.assertEqual(parts[1]["fileData"]["fileUri"], "gs://bucket/images/0001-02.webp")
        self.assertEqual(parts[1]["fileData"]["mimeType"], "image/webp")
        self.assertEqual(request["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("systemInstruction", request)

    def test_output_key_from_gcs_output_uses_instance_file_uri(self):
        item = {
            "instance": {
                "request": {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "fileData": {
                                        "fileUri": "gs://bucket/images/0001-02.webp",
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }

        self.assertEqual(output_key_from_gcs_output(item), "0001-02.ocr.json")

    def test_process_completed_batch_job_writes_missing_outputs_only(self):
        class FakeBatches:
            def get(self, *, name):
                return type(
                    "Job",
                    (),
                    {
                        "state": "JOB_STATE_SUCCEEDED",
                        "dest": type(
                            "Dest",
                            (),
                            {
                                "inlined_responses": [
                                    {
                                        "response": {
                                            "candidates": [
                                                {
                                                    "content": {
                                                        "parts": [
                                                            {
                                                                "text": '{"r":[{"t":"d","x":"本社 641-6951 浪大国1-47","i":1,"p":["641-6951"],"n":["本社"],"a":["浪大国1-47"],"f":[]}]}'
                                                            }
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            },
                        )(),
                        "error": None,
                    },
                )()

        class FakeClient:
            batches = FakeBatches()

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            output_path = root / "0001-01.ocr.json"
            job_record = {
                "name": "batch/1",
                "requests": [
                    {
                        "outputKey": "0001-01.ocr.json",
                        "outputPath": str(output_path),
                        "image": str(root / "0001-01.webp"),
                        "imageSha256": "sha",
                        "page": 1,
                        "column": 1,
                    }
                ],
            }

            saved, skipped, errors = process_completed_batch_job(
                FakeClient(),
                job_record,
                "book",
                "model",
                "compact",
            )

            self.assertEqual((saved, skipped, errors), (1, 0, []))
            payload = output_path.read_text(encoding="utf-8")
            self.assertIn("target_image_only_batch", payload)
            self.assertIn("本社", payload)


if __name__ == "__main__":
    unittest.main()
