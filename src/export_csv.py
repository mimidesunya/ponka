#!/usr/bin/env python3
"""Export OCR JSON results to csv.gz files.

This is the third stage of the current pipeline:
1. split_columns.py
2. ocr_columns.py
3. export_csv.py

The exporter performs lightweight normalization so the pipeline can already
produce a useful final csv.gz even before a richer stitching/normalization phase
is implemented.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from ponka.address_normalization import split_address_fields


CSV_HEADER = ["電話番号", "名前", "都道府県", "市区町村", "町域", "番地"]

ERA_OFFSETS = {
    "明治": 1867,
    "大正": 1911,
    "昭和": 1925,
    "平成": 1988,
    "令和": 2018,
}

PHONEBOOK_TYPE_SUFFIXES = [
    "50音別電話番号簿",
    "職業別電話番号簿",
    "電話番号簿",
]

DEFAULT_AREA_CODE = "06"
PHONE_PATTERN = r"(?:※?\d{2,4}[-()（）]?\d{1,4}[-()（）]?\d{2,4}(?:代表|代)?|※?\d{3,4}-\d{3,4}(?:代表|代)?|※?\d{3,4}(?:代表|代)?)"


def iter_ocr_book_dirs(work_root: Path) -> list[Path]:
    return sorted(
        path
        for path in work_root.iterdir()
        if path.is_dir() and any(child.suffix == ".json" and child.name.endswith(".ocr.json") for child in path.iterdir())
    )


def has_ocr_outputs(path: Path) -> bool:
    return path.exists() and any(path.glob("*.ocr.json"))


def infer_flat_book_name(ocr_root: Path) -> str:
    if ocr_root.name == "ocr_columns" and ocr_root.parent.name == "ocr":
        return ocr_root.parent.parent.name
    return ocr_root.name


def resolve_ocr_book_dirs(ocr_root: Path, book: str = "") -> list[tuple[Path, str]]:
    if book:
        if has_ocr_outputs(ocr_root):
            return [(ocr_root, book)]
        nested_book_dir = ocr_root / book
        if has_ocr_outputs(nested_book_dir):
            return [(nested_book_dir, nested_book_dir.name)]
        return [(nested_book_dir, book)]

    if has_ocr_outputs(ocr_root):
        return [(ocr_root, infer_flat_book_name(ocr_root))]

    return [(book_dir, book_dir.name) for book_dir in iter_ocr_book_dirs(ocr_root)]


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def add_default_area_code(phone: str) -> str:
    if not phone:
        return ""

    number = phone[1:] if phone.startswith("※") else phone
    if number.startswith("0"):
        return number
    return f"{DEFAULT_AREA_CODE}-{number}"


def normalize_phone(phone: str, fallback_text: str) -> str:
    candidate = normalize_text(phone or "")
    if not candidate:
        match = re.search(PHONE_PATTERN, normalize_text(fallback_text))
        candidate = match.group(0) if match else ""
    candidate = candidate.replace("(", "-").replace(")", "-")
    candidate = candidate.replace("（", "-").replace("）", "-")
    candidate = re.sub(r"\s+", "", candidate)
    candidate = re.sub(r"-+", "-", candidate).strip("-")
    candidate = re.sub(r"(?:代表|代)$", "", candidate)
    return add_default_area_code(candidate)


def normalize_phone_candidates(values: list[str], fallback_text: str) -> list[str]:
    candidates: list[str] = []
    for value in values:
        text = normalize_text(value)
        if not text:
            continue
        parts = re.split(r"[、,，/|]+", text.strip("{}"))
        for part in parts:
            matched = re.search(PHONE_PATTERN, part)
            normalized = normalize_phone(matched.group(0) if matched else part, "")
            if normalized:
                candidates.append(normalized)

    if not candidates:
        fallback = normalize_phone("", fallback_text)
        if fallback:
            candidates.append(fallback)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def normalize_string_candidates(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = normalize_text(str(value))
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def compact_address_text(address: str) -> str:
    return re.sub(r"[\s,，、・.．:：()（）{}［］\[\]「」『』]+", "", normalize_text(address))


def collapse_address_fragments(addresses: list[str]) -> list[str]:
    addresses = [address for address in addresses if address]
    if len(addresses) <= 1:
        return addresses

    compact_pairs = [(address, compact_address_text(address)) for address in addresses]
    for candidate, compact_candidate in sorted(compact_pairs, key=lambda item: len(item[1]), reverse=True):
        if not compact_candidate:
            continue
        if all(
            other == candidate
            or not compact_other
            or compact_other in compact_candidate
            for other, compact_other in compact_pairs
        ):
            return [candidate]

    return addresses


def is_blank_candidates(values: list[str]) -> bool:
    return not any(value.strip() for value in values)


def merge_address_continuation(addresses: list[str], continuations: list[str]) -> list[str]:
    continuation = "".join(address.strip() for address in continuations if address.strip())
    if not continuation:
        return addresses

    base_addresses = [address for address in addresses if address.strip()]
    if not base_addresses:
        return [continuation]
    return [f"{address}{continuation}" for address in base_addresses]


def render_csv_rows(
    phones: list[str],
    names: list[str],
    addresses: list[str],
    as_of: str | None = None,
) -> list[list[str]]:
    rendered_rows: list[list[str]] = []
    for phone, name, address in expand_candidates(phones, names, addresses):
        if not phone:
            continue
        prefecture, municipality, area, lot_number = split_address_fields(address, as_of=as_of)
        if not any([area, lot_number]):
            continue
        rendered_rows.append([phone, name, prefecture, municipality, area, lot_number])
    return rendered_rows


def normalize_indent_level(segment: dict[str, Any]) -> int:
    value = segment.get("indentLevel", 0)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def compact_name_text(name: str) -> str:
    return re.sub(r"\s+", "", normalize_text(name))


def append_name_prefix(prefix: str, name: str) -> str:
    prefix = normalize_text(prefix)
    name = normalize_text(name)
    if not prefix or not name or name.startswith(prefix):
        return name
    return f"{prefix}{name}"


def apply_indent_prefix(
    names: list[str],
    indent_level: int,
    name_stack: list[tuple[int, str]],
) -> list[str]:
    if not names:
        return names
    while name_stack and name_stack[-1][0] >= indent_level:
        name_stack.pop()

    prefix = name_stack[-1][1] if indent_level > 0 and name_stack else ""
    prefixed_names = [append_name_prefix(prefix, name) for name in names]
    if prefixed_names[0]:
        name_stack.append((indent_level, prefixed_names[0]))
    return prefixed_names


def split_base_and_subnames(names: list[str]) -> tuple[str, list[str]]:
    names = [name for name in names if name.strip()]
    if len(names) < 3:
        return "", []

    compact_names = [(name, compact_name_text(name)) for name in names]
    base = ""
    for candidate, compact_candidate in compact_names:
        if not compact_candidate:
            continue
        if any(other != candidate and compact_candidate in compact_other for other, compact_other in compact_names):
            if len(compact_candidate) > len(compact_name_text(base)):
                base = candidate

    if not base:
        return "", []

    compact_base = compact_name_text(base)
    subnames: list[str] = []
    seen: set[str] = set()
    for name, compact_name in compact_names:
        if name == base:
            continue
        subname = ""
        if compact_name.startswith(compact_base):
            subname = compact_name[len(compact_base) :]
        elif compact_name not in compact_base:
            subname = name
        subname = normalize_text(subname)
        if subname and subname not in seen:
            subnames.append(subname)
            seen.add(subname)
    return base, subnames


def phone_match_terms(phone: str) -> list[str]:
    normalized = normalize_text(phone)
    terms = [normalized]
    if normalized.startswith(f"{DEFAULT_AREA_CODE}-"):
        terms.append(normalized[len(DEFAULT_AREA_CODE) + 1 :])
    return sorted({term for term in terms if term}, key=len, reverse=True)


def find_first_position(text: str, terms: list[str], start: int = 0) -> int:
    positions = [text.find(term, start) for term in terms if term]
    positions = [position for position in positions if position >= 0]
    return min(positions) if positions else -1


def build_positioned_rows(
    clean_text: str,
    phones: list[str],
    names: list[str],
    addresses: list[str],
    as_of: str | None = None,
) -> list[list[str]]:
    if len(phones) < 2 or len(addresses) < 2:
        return []

    base_name, subnames = split_base_and_subnames(names)
    if not base_name or not subnames:
        return []

    text = normalize_text(clean_text)
    sub_positions = sorted(
        (position, subname)
        for subname in subnames
        for position in [find_first_position(text, [subname])]
        if position >= 0
    )
    address_positions = sorted(
        (position, address)
        for address in addresses
        for position in [find_first_position(text, [address])]
        if position >= 0
    )
    if not sub_positions or not address_positions:
        return []

    phone_positions: list[tuple[int, str]] = []
    search_start = 0
    for phone in phones:
        position = find_first_position(text, phone_match_terms(phone), search_start)
        if position < 0:
            return []
        phone_positions.append((position, phone))
        search_start = position + 1

    rows: list[list[str]] = []
    for index, (phone_position, phone) in enumerate(phone_positions):
        next_phone_position = phone_positions[index + 1][0] if index + 1 < len(phone_positions) else len(text)
        subname = ""
        for position, candidate in sub_positions:
            if position <= phone_position:
                subname = candidate
            else:
                break

        address = ""
        for position, candidate in address_positions:
            if phone_position <= position < next_phone_position:
                address = candidate
                break
        if not address:
            next_sub_position = next((position for position, _ in sub_positions if position > phone_position), len(text))
            for position, candidate in address_positions:
                if phone_position <= position < next_sub_position:
                    address = candidate
                    break

        name = f"{base_name} {subname}".strip() if subname else base_name
        rows.extend(render_csv_rows([phone], [name], [address], as_of=as_of))

    return rows


def is_directory_entry_segment(segment: dict[str, Any]) -> bool:
    entry_type = segment.get("entryType")
    if not isinstance(entry_type, str):
        raise ValueError("OCR segment is missing required entryType; rerun OCR with the current prompt version")
    return entry_type == "directory_entry"


def is_phone_only_segment(raw_text: str, phones: list[str]) -> bool:
    if not phones:
        return False

    text = normalize_text(raw_text)
    if not text:
        return False

    text = re.sub(
        PHONE_PATTERN,
        "",
        text,
    )
    text = re.sub(r"[\s.．\-‐ー―−–—()（）{}［］\[\]、,，/|…・:：]+", "", text)
    return not text


def split_name_and_address(name_hint: str, address_hint: str, raw_text: str) -> tuple[str, str]:
    name = normalize_text(name_hint)
    address = normalize_text(address_hint)
    if name or address:
        return name, address

    text = normalize_text(raw_text)
    phone_match = re.search(PHONE_PATTERN, text)
    if phone_match:
        text = (text[: phone_match.start()] + " " + text[phone_match.end() :]).strip()
    parts = text.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_phonebook_name(book_name: str) -> tuple[str, str, str]:
    match = re.match(r"^(明治|大正|昭和|平成|令和)(\d+)年(\d+)月(\d+)日(.+)$", book_name)
    if not match:
        return "unknown-date", book_name, "電話番号簿"

    era, year, month, day, rest = match.groups()
    iso_year = ERA_OFFSETS[era] + int(year)
    iso_date = f"{iso_year:04d}-{int(month):02d}-{int(day):02d}"

    for suffix in PHONEBOOK_TYPE_SUFFIXES:
        if rest.endswith(suffix):
            region = rest[: -len(suffix)] or "unknown-region"
            return iso_date, region, suffix

    return iso_date, rest, "電話番号簿"


def build_csv_filename(book_name: str) -> str:
    iso_date, region, book_type = parse_phonebook_name(book_name)
    safe_region = region.replace("/", "・")
    safe_type = book_type.replace("/", "・")
    return f"{iso_date}-{safe_region}-{safe_type}.csv.gz"


def extract_rows(book_dir: Path, as_of: str | None = None) -> list[list[str]]:
    rows: list[list[str]] = []
    previous_entry: tuple[list[str], list[str]] | None = None
    previous_export: dict[str, Any] | None = None
    name_stack: list[tuple[int, str]] = []
    for path in sorted(book_dir.glob("*.ocr.json")):
        payload = load_json(path)
        for segment in payload.get("segments", []):
            if segment.get("entryType") in {"ad_block", "category_heading"}:
                previous_entry = None
                previous_export = None
                name_stack = []
                continue
            if not is_directory_entry_segment(segment):
                continue

            indent_level = normalize_indent_level(segment)
            raw_text = str(segment.get("cleanText") or segment.get("rawText", "")).strip()
            hints = segment.get("entryHints", {})
            phone_candidates = normalize_phone_candidates(
                normalize_string_candidates(segment.get("phones")) or [str(hints.get("phone", ""))],
                raw_text,
            )
            name_candidates = normalize_string_candidates(segment.get("names")) or [str(hints.get("name", "")).strip()]
            address_candidates = normalize_string_candidates(segment.get("addresses")) or [str(hints.get("address", "")).strip()]
            address_candidates = collapse_address_fragments(address_candidates)

            if (
                previous_export is not None
                and is_blank_candidates(phone_candidates)
                and is_blank_candidates(name_candidates)
                and not is_blank_candidates(address_candidates)
            ):
                previous_export["addresses"] = collapse_address_fragments(
                    merge_address_continuation(previous_export["addresses"], address_candidates)
                )
                replacement_rows = render_csv_rows(
                    previous_export["phones"],
                    previous_export["names"],
                    previous_export["addresses"],
                    as_of=as_of,
                )
                row_start = previous_export["row_start"]
                row_end = previous_export["row_end"]
                rows[row_start:row_end] = replacement_rows
                previous_export["row_end"] = row_start + len(replacement_rows)
                if any(previous_export["names"]) and any(previous_export["addresses"]):
                    previous_entry = (previous_export["names"], previous_export["addresses"])
                continue

            if (
                previous_entry
                and phone_candidates
                and not any(name_candidates)
                and not any(address_candidates)
                and is_phone_only_segment(raw_text, phone_candidates)
            ):
                name_candidates, address_candidates = previous_entry
            elif not any(name_candidates) or not any(address_candidates):
                fallback_name, fallback_address = split_name_and_address(
                    str(hints.get("name", "")),
                    str(hints.get("address", "")),
                    raw_text,
                )
                if not any(name_candidates):
                    name_candidates = [fallback_name]
                if not any(address_candidates):
                    address_candidates = [fallback_address]

            name_candidates = apply_indent_prefix(name_candidates, indent_level, name_stack)

            row_start = len(rows)
            rendered_rows = build_positioned_rows(
                raw_text,
                phone_candidates,
                name_candidates,
                address_candidates,
                as_of=as_of,
            )
            if not rendered_rows:
                rendered_rows = render_csv_rows(phone_candidates, name_candidates, address_candidates, as_of=as_of)
            rows.extend(rendered_rows)

            if rendered_rows and (any(phone_candidates) or any(name_candidates)):
                previous_export = {
                    "phones": phone_candidates,
                    "names": name_candidates,
                    "addresses": address_candidates,
                    "row_start": row_start,
                    "row_end": len(rows),
                }

            if any(name_candidates) and any(address_candidates):
                previous_entry = (name_candidates, address_candidates)
    return rows


def expand_candidates(
    phones: list[str],
    names: list[str],
    addresses: list[str],
) -> list[tuple[str, str, str]]:
    phones = phones or [""]
    names = [name for name in names if name] or [""]
    addresses = [address for address in addresses if address] or [""]
    row_count = max(len(phones), len(addresses), 1)
    rows: list[tuple[str, str, str]] = []
    for index in range(row_count):
        phone = phones[index] if index < len(phones) else (phones[0] if len(phones) == 1 else "")
        name = names[index] if index < len(names) else names[0]
        address = addresses[index] if index < len(addresses) else addresses[-1]
        rows.append((phone, name, address))
    return rows


def write_csv_gz(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)


def process_book_dir(book_dir: Path, csv_root: Path, book_name: str | None = None) -> Path:
    as_of, _, _ = parse_phonebook_name(book_name or book_dir.name)
    rows = extract_rows(book_dir, as_of=as_of)
    output_path = csv_root / build_csv_filename(book_name or book_dir.name)
    write_csv_gz(output_path, rows)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR JSON を最終 csv.gz に変換します。")
    parser.add_argument(
        "--ocr-root",
        type=Path,
        default=Path("output") / "ocr_columns",
        help="ocr_columns.py の出力ルート",
    )
    parser.add_argument(
        "--csv-root",
        type=Path,
        default=Path("output") / "csv",
        help="csv.gz の出力ルート",
    )
    parser.add_argument(
        "--book",
        type=str,
        default="",
        help="特定の電話帳ディレクトリだけ変換する場合の名前",
    )
    args = parser.parse_args()

    book_dirs = resolve_ocr_book_dirs(args.ocr_root, args.book)

    if not book_dirs:
        raise FileNotFoundError(f"OCR ディレクトリが見つかりません: {args.ocr_root}")

    for book_dir, book_name in book_dirs:
        if not book_dir.exists():
            raise FileNotFoundError(f"電話帳 OCR ディレクトリが見つかりません: {book_dir}")
        output_path = process_book_dir(book_dir, args.csv_root, book_name)
        print(f"[OK] {book_name} -> {output_path}")


if __name__ == "__main__":
    main()
