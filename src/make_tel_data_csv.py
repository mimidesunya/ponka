#!/usr/bin/env python3
"""Convert exported phonebook CSV into TEL/DATA csv.gz format.

The TEL/DATA files are gzip-compressed UTF-8 CSV files without a header.  The
source exported by this project has the same first six columns with a header.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import itertools
import os
import re
import unicodedata
from pathlib import Path
from typing import TextIO


COLUMNS = ["電話番号", "名前", "都道府県", "市区町村", "町域", "番地"]
CANONICAL_PHONE_PATTERN = re.compile(r"^06-\d{3}-\d{4}$")
PHONE_DASHES = str.maketrans({
    "－": "-",
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "ー": "-",
})


class ClosingTextIOWrapper(io.TextIOWrapper):
    def __init__(self, buffer: gzip.GzipFile, raw_file: TextIO, **kwargs: object) -> None:
        super().__init__(buffer, **kwargs)
        self._raw_file = raw_file

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._raw_file.close()


def open_text(path: Path, mode: str) -> TextIO:
    if ".gz" in path.suffixes:
        if "r" in mode:
            return gzip.open(path, mode, encoding="utf-8", newline="")
        binary_mode = mode.replace("t", "").replace("b", "") + "b"
        raw = open(path, binary_mode)
        try:
            gzip_file = gzip.GzipFile(filename="", mode=binary_mode, fileobj=raw)
            return ClosingTextIOWrapper(gzip_file, raw, encoding="utf-8", newline="")
        except Exception:
            raw.close()
            raise
    return open(path, mode, encoding="utf-8", newline="")


def normalize_text(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalize_phone(value: object) -> str:
    phone = normalize_text(value).translate(PHONE_DASHES)
    phone = re.sub(r"\s+", "", phone)
    phone = re.sub(r"-+", "-", phone).strip("-")
    phone = re.sub(r"(?:代表|代)$", "", phone)
    return phone


def phone_sort_key(row: list[str]) -> tuple[int, int]:
    _, exchange, subscriber = row[0].split("-")
    return int(exchange), int(subscriber)


def iter_rows(path: Path) -> tuple[list[list[str]], dict[str, int]]:
    rows: list[list[str]] = []
    stats = {
        "skippedBlankRows": 0,
        "skippedInvalidPhones": 0,
        "skippedDuplicateRows": 0,
    }
    seen: set[tuple[str, ...]] = set()
    with open_text(path, "rt") as handle:
        reader = csv.reader(handle)
        first = next(reader, None)
        if first is None:
            return rows, stats
        if first[: len(COLUMNS)] != COLUMNS:
            reader = itertools.chain([first], reader)
        for row in reader:
            if not row:
                stats["skippedBlankRows"] += 1
                continue
            values = list(row[: len(COLUMNS)])
            if len(values) < len(COLUMNS):
                values.extend([""] * (len(COLUMNS) - len(values)))
            values = [normalize_text(value) for value in values]
            values[0] = normalize_phone(values[0])
            if not CANONICAL_PHONE_PATTERN.fullmatch(values[0]):
                stats["skippedInvalidPhones"] += 1
                continue
            key = tuple(values)
            if key in seen:
                stats["skippedDuplicateRows"] += 1
                continue
            seen.add(key)
            rows.append(values)
    rows.sort(key=phone_sort_key)
    return rows, stats


def write_rows(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with open_text(temp_path, "wt") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)
    os.replace(temp_path, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create TEL/DATA csv.gz from exported phonebook CSV")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    rows, stats = iter_rows(args.input_csv)
    write_rows(args.output_csv, rows)
    print(
        f"[OK] wrote {args.output_csv} rows={len(rows)} "
        f"skippedBlankRows={stats['skippedBlankRows']} "
        f"skippedInvalidPhones={stats['skippedInvalidPhones']} "
        f"skippedDuplicateRows={stats['skippedDuplicateRows']}"
    )


if __name__ == "__main__":
    main()
