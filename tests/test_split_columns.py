import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from split_columns import is_excluded_page, resolve_split_options, validate_split_quality_for_output  # noqa: E402


class SplitColumnsTest(unittest.TestCase):
    def test_validate_split_quality_allows_clean_page(self):
        validate_split_quality_for_output({"flags": []})

    def test_validate_split_quality_rejects_uneven_column_widths(self):
        with self.assertRaisesRegex(ValueError, "カラム幅が不均一"):
            validate_split_quality_for_output({"flags": ["uneven_column_widths"]})

    def test_validate_split_quality_allows_non_fatal_review_flags(self):
        validate_split_quality_for_output({"flags": ["possible_text_cut_at_column_edge"]})

    def test_resolve_split_options_uses_phonebook_config(self):
        options = resolve_split_options({"split": {"fixedColumnCount": 4, "webpQuality": 95}})

        self.assertEqual(options.fixed_n_cols, 4)
        self.assertEqual(options.webp_quality, 95)

    def test_resolve_split_options_cli_overrides_config(self):
        options = resolve_split_options(
            {"split": {"fixedColumnCount": 4, "resizeScale": 0.75}},
            fixed_n_cols=3,
            resize_scale=1.0,
        )

        self.assertEqual(options.fixed_n_cols, 3)
        self.assertEqual(options.resize_scale, 1.0)

    def test_resolve_split_options_reads_workers_and_excludes(self):
        options = resolve_split_options(
            {
                "split": {
                    "workers": 4,
                    "excludePages": ["0001.png"],
                    "excludePageRanges": ["0003-0005"],
                }
            }
        )

        self.assertEqual(options.workers, 4)
        self.assertTrue(is_excluded_page(Path("0001.png"), options.exclude_pages, options.exclude_page_ranges))
        self.assertTrue(is_excluded_page(Path("0004.png"), options.exclude_pages, options.exclude_page_ranges))
        self.assertFalse(is_excluded_page(Path("0006.png"), options.exclude_pages, options.exclude_page_ranges))


if __name__ == "__main__":
    unittest.main()
