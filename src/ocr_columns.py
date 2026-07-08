#!/usr/bin/env python3
"""Gemini を使って分割済み電話帳カラムを OCR する。

この段階は output/split の対象カラム画像と、直前カラム OCR の末尾だけを
読み取り、JSON を output/ocr_columns に書き出す。直前カラムの文脈は
先頭 fragment の継続判定だけに使い、対象画像外の文字は転記しない。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ponka.gemini_client import create_gemini_client, gemini_auth_label
from ponka.ocr_prompts import (
    COMPACT_OCR_PROMPT_TEMPLATE,
    COMPACT_OCR_SYSTEM_INSTRUCTION,
    OCR_PROMPT_TEMPLATE,
    OCR_SYSTEM_INSTRUCTION,
    SLIM_OCR_PROMPT_TEMPLATE,
)
from ponka.ocr_schemas import (
    COMPACT_OCR_RESPONSE_SCHEMA,
    OCR_RESPONSE_SCHEMA,
    SLIM_OCR_RESPONSE_SCHEMA,
)

PROMPT_VERSION = "ocr-target-image-with-prev-tail-address-hints-braces-layout-indent-v6"
OCR_OUTPUT_SCHEMAS = {"standard", "slim", "compact"}
DEFAULT_OCR_OUTPUT_SCHEMA = "compact"
GCS_BATCH_REQUESTS_NAME = "requests.jsonl"


@dataclass(frozen=True)
class ColumnImage:
    book_name: str
    page: int
    column: int
    path: Path

    @property
    def stem_key(self) -> str:
        return f"{self.page:04d}-{self.column:02d}"

    @property
    def output_key(self) -> str:
        return f"{self.stem_key}.ocr.json"


@dataclass(frozen=True)
class PreparedOcrRequest:
    column_image: ColumnImage
    output_path: Path
    image_sha256: str
    request: Any


@dataclass(frozen=True)
class OcrJob:
    book_dir: Path
    target_dir: Path
    book_name: str


def load_config(config_path: Path) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_gemini_model(gemini_cfg: dict[str, Any]) -> str:
    """Choose the OCR model from config.

    For OCR we want a multimodal text model. Prefer the explicit ocrModel key.
    textModel is accepted only as a legacy fallback.
    """
    aliases = {
        "gemini-3.1-flash-preview": "gemini-3-flash-preview",
        "models/gemini-3.1-flash-preview": "gemini-3-flash-preview",
        "gemini-3.1-flash": "gemini-3-flash-preview",
        "models/gemini-3.1-flash": "gemini-3-flash-preview",
        "gemini-pro": "gemini-2.5-pro",
        "models/gemini-pro": "gemini-2.5-pro",
    }
    configured = (
        gemini_cfg.get("ocrModel")
        or gemini_cfg.get("textModel")
        or "gemini-2.5-flash"
    )
    return aliases.get(configured, configured)


def iter_book_dirs(split_root: Path) -> list[Path]:
    return sorted(
        path
        for path in split_root.iterdir()
        if path.is_dir() and (path / "column_count.json").exists()
    )


def has_split_metadata(path: Path) -> bool:
    return (path / "column_count.json").exists()


def infer_flat_book_name(split_root: Path) -> str:
    if split_root.name == "split" and split_root.parent.name == "ocr":
        return split_root.parent.parent.name
    return split_root.name


def resolve_ocr_jobs(split_root: Path, ocr_root: Path, book: str = "") -> list[OcrJob]:
    if book:
        if has_split_metadata(split_root):
            return [OcrJob(book_dir=split_root, target_dir=ocr_root, book_name=book)]
        nested_book_dir = split_root / book
        if has_split_metadata(nested_book_dir):
            return [
                OcrJob(
                    book_dir=nested_book_dir,
                    target_dir=ocr_root / nested_book_dir.name,
                    book_name=nested_book_dir.name,
                )
            ]
        return [OcrJob(book_dir=nested_book_dir, target_dir=ocr_root / book, book_name=book)]

    if has_split_metadata(split_root):
        return [
            OcrJob(
                book_dir=split_root,
                target_dir=ocr_root,
                book_name=infer_flat_book_name(split_root),
            )
        ]

    return [
        OcrJob(book_dir=book_dir, target_dir=ocr_root / book_dir.name, book_name=book_dir.name)
        for book_dir in iter_book_dirs(split_root)
    ]


def parse_column_image(path: Path, book_name: str) -> ColumnImage | None:
    match = re.fullmatch(r"(\d+)-(\d+)\.(?:png|webp)", path.name, flags=re.IGNORECASE)
    if match is None:
        return None
    return ColumnImage(
        book_name=book_name,
        page=int(match.group(1)),
        column=int(match.group(2)),
        path=path,
    )


def list_column_images(book_dir: Path, book_name: str | None = None) -> list[ColumnImage]:
    images: list[ColumnImage] = []
    for path in sorted(child for child in book_dir.iterdir() if child.is_file()):
        if path.suffix.lower() not in {".png", ".webp"}:
            continue
        parsed = parse_column_image(path, book_name or book_dir.name)
        if parsed is not None:
            images.append(parsed)
    return images


def open_pil_image(path: Path) -> Any:
    from PIL import Image

    with open(path, "rb") as handle:
        return Image.open(io.BytesIO(handle.read())).copy()


def image_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            payload, _ = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("Gemini response did not contain a JSON object")


def require_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be boolean, got {type(value).__name__}")


def require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be number, got {type(value).__name__}")
    return float(value)


def require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be integer, got {type(value).__name__}")
    return value


def require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be string, got {type(value).__name__}")
    return value.strip()


def require_visible_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be string, got {type(value).__name__}")
    return value.rstrip()


def require_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    normalized: list[str] = []
    for index, item in enumerate(value):
        normalized.append(require_string(item, f"{field_name}[{index}]"))
    return [item for item in normalized if item]


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def normalize_continuity_from_previous(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    confidence = require_number(value.get("confidence", 0.0), f"{field_name}.confidence")
    return {
        "sameEntry": require_bool(value.get("sameEntry", False), f"{field_name}.sameEntry"),
        "previousSegmentId": require_string(value.get("previousSegmentId", ""), f"{field_name}.previousSegmentId"),
        "mergedCleanText": require_string(value.get("mergedCleanText", ""), f"{field_name}.mergedCleanText"),
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": require_string(value.get("reason", ""), f"{field_name}.reason"),
    }


def normalize_compact_segments(payload: dict[str, Any], page: int, column: int) -> dict[str, Any]:
    rows = payload.get("r", [])
    if not isinstance(rows, list):
        raise ValueError("r must be an array")

    type_map = {
        "d": "directory_entry",
        "a": "ad_block",
        "h": "category_heading",
    }
    segments: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"r[{index}] must be an object")
        short_type = require_string(row.get("t"), f"r[{index}].t")
        entry_type = type_map.get(short_type)
        if entry_type is None:
            raise ValueError(f"r[{index}].t is invalid: {short_type}")
        clean_text = require_visible_text(row.get("x", ""), f"r[{index}].x")
        indent_level = require_int(row.get("i", 0), f"r[{index}].i")
        phones = unique_preserving_order(require_string_list(row.get("p", []), f"r[{index}].p"))
        names = unique_preserving_order(require_string_list(row.get("n", []), f"r[{index}].n"))
        addresses = unique_preserving_order(require_string_list(row.get("a", []), f"r[{index}].a"))
        review_flags = unique_preserving_order(require_string_list(row.get("f", []), f"r[{index}].f"))
        starts_mid_entry = row.get("s", False)
        ends_mid_entry = row.get("e", False)
        if not isinstance(starts_mid_entry, bool):
            starts_mid_entry = False
        if not isinstance(ends_mid_entry, bool):
            ends_mid_entry = False
        if starts_mid_entry and "starts_mid_entry" not in review_flags:
            review_flags.append("starts_mid_entry")
        if ends_mid_entry and "ends_mid_entry" not in review_flags:
            review_flags.append("ends_mid_entry")
        if len(phones) > 1 and "multi_phone" not in review_flags:
            review_flags.append("multi_phone")
        if len(addresses) > 1 and "multi_address" not in review_flags:
            review_flags.append("multi_address")
        segments.append(
            {
                "segmentId": f"{page:04d}-{column:02d}-{index:04d}",
                "sequence": index,
                "entryType": entry_type,
                "rawText": clean_text,
                "cleanText": clean_text,
                "indentLevel": max(0, indent_level),
                "startsMidEntry": starts_mid_entry,
                "endsMidEntry": ends_mid_entry,
                "entryHints": {
                    "phone": phones[0] if phones else "",
                    "name": names[0] if names else "",
                    "address": addresses[0] if addresses else "",
                },
                "phones": phones,
                "names": names,
                "addresses": addresses,
                "reviewFlags": review_flags,
                "continuityFromPrevious": {
                    "sameEntry": False,
                    "previousSegmentId": "",
                    "mergedCleanText": "",
                    "confidence": 0.0,
                    "reason": "",
                },
                "confidence": 1.0,
            }
        )
    return {"segments": segments}


def normalize_segments(payload: dict[str, Any], page: int, column: int) -> dict[str, Any]:
    if "segments" not in payload and "r" in payload:
        return normalize_compact_segments(payload, page=page, column=column)

    segments = payload.get("segments", [])
    if not isinstance(segments, list):
        raise ValueError("segments must be an array")

    normalized_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ValueError(f"segments[{index}] must be an object")
        entry_hints = segment.get("entryHints", {})
        if not isinstance(entry_hints, dict):
            raise ValueError(f"segments[{index}].entryHints must be an object")
        entry_type = require_string(segment.get("entryType"), f"segments[{index}].entryType")
        if entry_type not in {"directory_entry", "ad_block", "category_heading"}:
            raise ValueError(f"segments[{index}].entryType is invalid: {entry_type}")
        confidence_default = 1.0 if "confidence" not in segment else segment.get("confidence", 0.0)
        confidence = require_number(confidence_default, f"segments[{index}].confidence")
        indent_level = require_int(segment.get("indentLevel", 0), f"segments[{index}].indentLevel")
        hint_phone = require_string(entry_hints.get("phone", ""), f"segments[{index}].entryHints.phone")
        hint_name = require_string(entry_hints.get("name", ""), f"segments[{index}].entryHints.name")
        hint_address = require_string(entry_hints.get("address", ""), f"segments[{index}].entryHints.address")
        phones = unique_preserving_order(require_string_list(segment.get("phones", []), f"segments[{index}].phones"))
        names = unique_preserving_order(require_string_list(segment.get("names", []), f"segments[{index}].names"))
        addresses = unique_preserving_order(require_string_list(segment.get("addresses", []), f"segments[{index}].addresses"))
        hint_phone = hint_phone or (phones[0] if phones else "")
        hint_name = hint_name or (names[0] if names else "")
        hint_address = hint_address or (addresses[0] if addresses else "")
        review_flags = unique_preserving_order(
            require_string_list(segment.get("reviewFlags", []), f"segments[{index}].reviewFlags")
        )
        continuity = normalize_continuity_from_previous(
            segment.get("continuityFromPrevious"), f"segments[{index}].continuityFromPrevious"
        )
        starts_mid_entry = require_bool(segment.get("startsMidEntry", False), f"segments[{index}].startsMidEntry")
        ends_mid_entry = require_bool(segment.get("endsMidEntry", False), f"segments[{index}].endsMidEntry")
        if continuity["sameEntry"] and index != 1:
            continuity = {
                "sameEntry": False,
                "previousSegmentId": "",
                "mergedCleanText": "",
                "confidence": 0.0,
                "reason": "continuity is only valid for the first segment",
            }
        if continuity["sameEntry"]:
            starts_mid_entry = True
        if starts_mid_entry and "starts_mid_entry" not in review_flags:
            review_flags.append("starts_mid_entry")
        if ends_mid_entry and "ends_mid_entry" not in review_flags:
            review_flags.append("ends_mid_entry")
        if continuity["sameEntry"] and "continued_from_previous" not in review_flags:
            review_flags.append("continued_from_previous")
        if hint_phone and hint_phone not in phones:
            phones.insert(0, hint_phone)
        if hint_name and hint_name not in names:
            names.insert(0, hint_name)
        if hint_address and hint_address not in addresses:
            addresses.insert(0, hint_address)
        if len(phones) > 1 and "multi_phone" not in review_flags:
            review_flags.append("multi_phone")
        if len(addresses) > 1 and "multi_address" not in review_flags:
            review_flags.append("multi_address")
        normalized_segments.append(
            {
                "segmentId": segment.get("segmentId") or f"{page:04d}-{column:02d}-{index:04d}",
                "sequence": require_int(segment.get("sequence", index), f"segments[{index}].sequence"),
                "entryType": entry_type,
                "rawText": require_visible_text(segment.get("rawText", ""), f"segments[{index}].rawText"),
                "cleanText": require_string(segment.get("cleanText", ""), f"segments[{index}].cleanText"),
                "indentLevel": max(0, indent_level),
                "startsMidEntry": starts_mid_entry,
                "endsMidEntry": ends_mid_entry,
                "entryHints": {
                    "phone": hint_phone,
                    "name": hint_name,
                    "address": hint_address,
                },
                "phones": phones,
                "names": names,
                "addresses": addresses,
                "reviewFlags": review_flags,
                "continuityFromPrevious": continuity,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    return {"segments": normalized_segments}


def build_generate_content_request(
    column_image: ColumnImage,
    output_schema: str,
) -> Any:
    from google.genai import types

    prompt, response_schema, system_instruction = build_prompt_config(column_image, output_schema)

    with open(column_image.path, "rb") as handle:
        image_bytes = handle.read()

    return types.InlinedRequest(
        metadata={
            "outputKey": column_image.output_key,
            "page": str(column_image.page),
            "column": str(column_image.column),
        },
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part(text=prompt),
                    types.Part(
                        inline_data=types.Blob(
                            data=image_bytes,
                            mime_type=image_mime_type(column_image.path),
                        )
                    ),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=types.Schema.model_validate(response_schema),
        ),
    )


def build_prompt_config(
    column_image: ColumnImage,
    output_schema: str,
) -> tuple[str, dict[str, Any], str]:
    if output_schema == "compact":
        prompt_template = COMPACT_OCR_PROMPT_TEMPLATE
        response_schema = COMPACT_OCR_RESPONSE_SCHEMA
        system_instruction = COMPACT_OCR_SYSTEM_INSTRUCTION
    elif output_schema == "slim":
        prompt_template = SLIM_OCR_PROMPT_TEMPLATE
        response_schema = SLIM_OCR_RESPONSE_SCHEMA
        system_instruction = OCR_SYSTEM_INSTRUCTION
    else:
        prompt_template = OCR_PROMPT_TEMPLATE
        response_schema = OCR_RESPONSE_SCHEMA
        system_instruction = OCR_SYSTEM_INSTRUCTION

    prompt = prompt_template.format(
        book_name=column_image.book_name,
        page=column_image.page,
        column=column_image.column,
    )
    return prompt, response_schema, system_instruction


def build_gcs_generate_content_request(
    column_image: ColumnImage,
    output_schema: str,
    image_gcs_uri: str,
) -> dict[str, Any]:
    from google.genai import types

    prompt, response_schema, system_instruction = build_prompt_config(column_image, output_schema)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=types.Schema.model_validate(response_schema),
    ).model_dump(by_alias=True, exclude_none=True, mode="json")
    system_instruction_value = config.pop("systemInstruction", None)
    request: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "fileData": {
                            "fileUri": image_gcs_uri,
                            "mimeType": image_mime_type(column_image.path),
                        }
                    },
                ],
            }
        ],
        "generationConfig": config,
    }
    if system_instruction_value is not None:
        if isinstance(system_instruction_value, str):
            request["systemInstruction"] = {"parts": [{"text": system_instruction_value}]}
        else:
            request["systemInstruction"] = system_instruction_value
    return request


def extract_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    if isinstance(response, dict):
        direct_text = response.get("text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text
        candidates = response.get("candidates")
    else:
        candidates = getattr(response, "candidates", None)

    if not isinstance(candidates, list):
        raise ValueError("Gemini response did not contain candidates")

    parts_text: list[str] = []
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else getattr(candidate, "content", None)
        parts = content.get("parts") if isinstance(content, dict) else getattr(content, "parts", None)
        if not isinstance(parts, list):
            continue
        for part in parts:
            part_text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if isinstance(part_text, str):
                parts_text.append(part_text)

    joined = "".join(parts_text).strip()
    if not joined:
        raise ValueError("Gemini response text was empty")
    return joined


def build_output_payload(
    column_image: ColumnImage,
    payload: dict[str, Any],
    model: str,
    output_schema: str,
    image_sha256: str,
    process_mode: str = "batch",
) -> dict[str, Any]:
    return {
        "book": column_image.book_name,
        "page": column_image.page,
        "column": column_image.column,
        "image": str(column_image.path).replace("\\", "/"),
        "imageSha256": image_sha256,
        "promptVersion": PROMPT_VERSION,
        "ocrOutputSchema": output_schema,
        "context": {
            "mode": f"target_image_only_{process_mode}",
            "previousOcrJson": "",
            "previousOcrSha256": "",
            "previousOcrTail": {},
            "nextImage": "",
        },
        "model": model,
        "segments": payload["segments"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def lock_path(target_dir: Path) -> Path:
    return target_dir / "ocr_columns.lock"


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def lock_pid(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    try:
        return int(payload.get("pid", 0))
    except Exception:
        return 0


@contextmanager
def single_process_lock(target_dir: Path) -> Any:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = lock_path(target_dir)
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = lock_pid(path)
            if process_is_alive(pid):
                raise RuntimeError(f"OCR monitor is already running for {target_dir} (pid={pid})")
            path.unlink(missing_ok=True)
            continue
        break

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": os.getpid(),
                "createdAt": utc_now_iso(),
                "targetDir": str(target_dir),
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    try:
        yield
    finally:
        if lock_pid(path) == os.getpid():
            path.unlink(missing_ok=True)


def prepare_ocr_request(
    image: ColumnImage,
    target_dir: Path,
    output_schema: str,
) -> PreparedOcrRequest:
    out_path = target_dir / f"{image.stem_key}.ocr.json"
    image_sha256 = file_sha256(image.path)

    return PreparedOcrRequest(
        column_image=image,
        output_path=out_path,
        image_sha256=image_sha256,
        request=build_generate_content_request(image, output_schema),
    )


def state_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    if isinstance(raw, str):
        return raw
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)



def write_prepared_output(
    prepared: PreparedOcrRequest,
    payload: dict[str, Any],
    model: str,
    output_schema: str,
    process_mode: str = "batch",
) -> bool:
    if prepared.output_path.exists():
        return False
    write_json(
        prepared.output_path,
        build_output_payload(
            column_image=prepared.column_image,
            payload=payload,
            model=model,
            output_schema=output_schema,
            image_sha256=prepared.image_sha256,
            process_mode=process_mode,
        ),
    )
    return True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def manifest_path(target_dir: Path) -> Path:
    return target_dir / "batch_manifest.json"


def request_manifest_item(prepared: PreparedOcrRequest) -> dict[str, Any]:
    image = prepared.column_image
    return {
        "outputKey": image.output_key,
        "outputPath": str(prepared.output_path).replace("\\", "/"),
        "image": str(image.path).replace("\\", "/"),
        "imageSha256": prepared.image_sha256,
        "page": image.page,
        "column": image.column,
    }


def image_gcs_uri(gcs_images_uri: str, image: ColumnImage) -> str:
    return f"{gcs_images_uri.rstrip('/')}/{image.path.name}"


def gcs_join(base_uri: str, *parts: str) -> str:
    return "/".join([base_uri.rstrip("/"), *(part.strip("/") for part in parts if part)])


def resolve_gcs_work_uri(gemini_cfg: dict[str, Any], override: str = "") -> str:
    value = str(override or gemini_cfg.get("gcsWorkUri") or "").strip()
    if not value:
        raise RuntimeError("GCS Batch には config.json の gemini.gcsWorkUri または --gcs-work-uri が必要です。")
    if not value.startswith("gs://"):
        raise ValueError("gcsWorkUri must start with gs://")
    return value.rstrip("/")


def resolve_gcloud_path(gemini_cfg: dict[str, Any]) -> str:
    configured = str(gemini_cfg.get("gcloudPath") or "").strip()
    if configured:
        return configured
    found = shutil.which("gcloud")
    if found:
        return found
    local_appdata = Path(str(Path.home() / "AppData" / "Local"))
    candidate = local_appdata / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
    if candidate.exists():
        return str(candidate)
    return "gcloud"


def run_gcloud(gcloud_path: str, args: list[str]) -> None:
    subprocess.run([gcloud_path, *args], check=True)


def gcloud_path_has_objects(gcloud_path: str, gcs_uri: str) -> bool:
    result = subprocess.run(
        [gcloud_path, "storage", "ls", gcs_uri.rstrip("/") + "/**"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def gcs_batch_workspace(target_dir: Path) -> Path:
    return target_dir / "gcs_batch"


def write_gcs_batch_requests(
    prepared: list[PreparedOcrRequest],
    output_schema: str,
    gcs_images_uri: str,
    workspace: Path,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    request_path = workspace / GCS_BATCH_REQUESTS_NAME
    with open(request_path, "w", encoding="utf-8") as handle:
        for item in prepared:
            image_uri = image_gcs_uri(gcs_images_uri, item.column_image)
            line = {
                "request": build_gcs_generate_content_request(
                    item.column_image,
                    output_schema,
                    image_uri,
                )
            }
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    return request_path


def extract_file_uri_from_instance(value: Any) -> str:
    if isinstance(value, dict):
        file_data = value.get("fileData") or value.get("file_data")
        if isinstance(file_data, dict):
            file_uri = file_data.get("fileUri") or file_data.get("file_uri")
            if isinstance(file_uri, str) and file_uri:
                return file_uri
        for nested in value.values():
            found = extract_file_uri_from_instance(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = extract_file_uri_from_instance(nested)
            if found:
                return found
    return ""


def output_key_from_gcs_output(item: dict[str, Any]) -> str:
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        output_key = metadata.get("outputKey") or metadata.get("output_key")
        if isinstance(output_key, str) and output_key:
            return output_key
    instance = item.get("instance") or item.get("request")
    file_uri = extract_file_uri_from_instance(instance)
    if file_uri:
        return f"{file_uri.rsplit('/', 1)[-1].rsplit('.', 1)[0]}.ocr.json"
    return ""


def prediction_from_gcs_output(item: dict[str, Any]) -> Any:
    return item.get("response") or item.get("prediction") or item.get("predictions") or item


def iter_gcs_output_jsonl_files(path: Path) -> list[Path]:
    return sorted(
        file
        for file in path.rglob("*")
        if file.is_file() and (file.suffix.lower() == ".jsonl" or file.name.startswith("prediction.results-"))
    )


def download_gcs_batch_outputs(gcloud_path: str, gcs_output_uri: str, workspace: Path) -> Path:
    output_dir = workspace / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_gcloud(gcloud_path, ["storage", "cp", "--recursive", gcs_output_uri.rstrip("/") + "/*", str(output_dir)])
    return output_dir


def prepared_from_manifest_item(item: dict[str, Any], book_name: str) -> PreparedOcrRequest:
    page = int(item["page"])
    column = int(item["column"])
    image = ColumnImage(
        book_name=book_name,
        page=page,
        column=column,
        path=Path(str(item["image"])),
    )
    return PreparedOcrRequest(
        column_image=image,
        output_path=Path(str(item["outputPath"])),
        image_sha256=str(item.get("imageSha256", "")),
        request=None,
    )


def load_batch_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return load_config(path)


def is_terminal_job_state(state: str) -> bool:
    return state in {
        "JOB_STATE_SUCCEEDED",
        "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED",
        "JOB_STATE_EXPIRED",
        "JOB_STATE_PARTIALLY_SUCCEEDED",
    }


def is_success_job_state(state: str) -> bool:
    return state in {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}


def batch_job_status_payload(job: Any, job_record: dict[str, Any]) -> dict[str, Any]:
    stats = getattr(job, "completion_stats", None)
    error = getattr(job, "error", None)
    return {
        "name": job_record.get("name") or getattr(job, "name", ""),
        "state": state_name(getattr(job, "state", "")),
        "checkedAt": utc_now_iso(),
        "completionStats": {
            "successfulCount": getattr(stats, "successful_count", None),
            "failedCount": getattr(stats, "failed_count", None),
            "incompleteCount": getattr(stats, "incomplete_count", None),
        },
        "error": getattr(error, "message", None) if error is not None else None,
    }


def update_job_record_from_status(job_record: dict[str, Any], status: dict[str, Any]) -> None:
    job_record["state"] = str(status.get("state") or "")
    job_record["checkedAt"] = str(status.get("checkedAt") or utc_now_iso())
    job_record["completionStats"] = status.get("completionStats", {})
    if status.get("error"):
        job_record["error"] = status["error"]


def chunked(values: list[PreparedOcrRequest], size: int) -> list[list[PreparedOcrRequest]]:
    if size <= 0:
        raise ValueError("--batch-size must be greater than 0")
    return [values[index : index + size] for index in range(0, len(values), size)]


def submit_batch_jobs(
    client: Any,
    model: str,
    prepared: list[PreparedOcrRequest],
    target_dir: Path,
    book_name: str,
    output_schema: str,
    batch_size: int,
) -> dict[str, Any]:
    from google.genai import types

    jobs: list[dict[str, Any]] = []
    for chunk_index, requests in enumerate(chunked(prepared, batch_size), start=1):
        batch_job = client.batches.create(
            model=model,
            src=[request.request for request in requests],
            config=types.CreateBatchJobConfig(
                display_name=f"ponka-{book_name}-{chunk_index:04d}",
            ),
        )
        jobs.append(
            {
                "name": batch_job.name,
                "state": state_name(batch_job.state),
                "submittedAt": utc_now_iso(),
                "requestCount": len(requests),
                "requests": [request_manifest_item(request) for request in requests],
            }
        )
        print(f"[BATCH] submitted {batch_job.name} requests={len(requests)}")

    manifest = {
        "book": book_name,
        "model": model,
        "promptVersion": PROMPT_VERSION,
        "ocrOutputSchema": output_schema,
        "ocrInputMode": "target_image_only",
        "processMode": "batch",
        "createdAt": utc_now_iso(),
        "jobs": jobs,
    }
    write_json(manifest_path(target_dir), manifest)
    return manifest


def submit_gcs_batch_job(
    client: Any,
    model: str,
    prepared: list[PreparedOcrRequest],
    target_dir: Path,
    book_dir: Path,
    book_name: str,
    output_schema: str,
    gcs_work_uri: str,
    gcloud_path: str,
) -> dict[str, Any]:
    from google.genai import types

    workspace = gcs_batch_workspace(target_dir)
    gcs_images_uri = gcs_join(gcs_work_uri, "images")
    gcs_requests_uri = gcs_join(gcs_work_uri, "requests", GCS_BATCH_REQUESTS_NAME)
    gcs_output_uri = gcs_join(gcs_work_uri, "results")

    print(f"[GCS] upload images -> {gcs_images_uri}")
    run_gcloud(
        gcloud_path,
        ["storage", "cp", str(book_dir / "*.webp"), gcs_images_uri + "/"],
    )

    request_path = write_gcs_batch_requests(
        prepared=prepared,
        output_schema=output_schema,
        gcs_images_uri=gcs_images_uri,
        workspace=workspace,
    )
    print(f"[GCS] upload requests -> {gcs_requests_uri}")
    run_gcloud(gcloud_path, ["storage", "cp", str(request_path), gcs_requests_uri])

    batch_job = client.batches.create(
        model=model,
        src=gcs_requests_uri,
        config=types.CreateBatchJobConfig(
            display_name=f"ponka-{book_name}",
            dest=gcs_output_uri,
        ),
    )
    manifest = {
        "book": book_name,
        "model": model,
        "promptVersion": PROMPT_VERSION,
        "ocrOutputSchema": output_schema,
        "ocrInputMode": "target_image_only",
        "processMode": "gcs-batch",
        "createdAt": utc_now_iso(),
        "gcsWorkUri": gcs_work_uri,
        "gcsImagesUri": gcs_images_uri,
        "gcsRequestsUri": gcs_requests_uri,
        "gcsOutputUri": gcs_output_uri,
        "jobs": [
            {
                "name": batch_job.name,
                "state": state_name(batch_job.state),
                "submittedAt": utc_now_iso(),
                "requestCount": len(prepared),
                "requests": [request_manifest_item(request) for request in prepared],
            }
        ],
    }
    write_json(manifest_path(target_dir), manifest)
    print(f"[BATCH] submitted {batch_job.name} requests={len(prepared)}")
    return manifest


def get_batch_responses(client: Any, job: Any) -> list[Any]:
    dest = getattr(job, "dest", None)
    if dest is None:
        return []

    inlined_responses = getattr(dest, "inlined_responses", None)
    if isinstance(inlined_responses, list):
        return inlined_responses

    file_name = getattr(dest, "file_name", None)
    if isinstance(file_name, str) and file_name:
        raw = client.files.download(file=file_name).decode("utf-8")
        responses: list[Any] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            responses.append(json.loads(line))
        return responses

    return []


def response_error_message(inlined_response: Any) -> str:
    error = inlined_response.get("error") if isinstance(inlined_response, dict) else getattr(inlined_response, "error", None)
    if error is None:
        return ""
    if isinstance(error, dict):
        return str(error.get("message") or error)
    message = getattr(error, "message", None)
    return str(message or error)


def response_payload(inlined_response: Any) -> Any:
    if isinstance(inlined_response, dict):
        return inlined_response.get("response", inlined_response)
    return getattr(inlined_response, "response", inlined_response)


def process_completed_batch_job(
    client: Any,
    job_record: dict[str, Any],
    book_name: str,
    model: str,
    output_schema: str,
) -> tuple[int, int, list[dict[str, Any]]]:
    job = client.batches.get(name=str(job_record["name"]))
    state = state_name(job.state)
    job_record["state"] = state
    job_record["checkedAt"] = utc_now_iso()
    if not is_success_job_state(state):
        message = getattr(getattr(job, "error", None), "message", "")
        raise RuntimeError(f"Batch job failed: {job_record['name']} state={state} {message}")

    responses = get_batch_responses(client, job)
    requests = job_record.get("requests", [])
    if len(responses) != len(requests):
        raise RuntimeError(
            f"Batch response count mismatch for {job_record['name']}: responses={len(responses)} requests={len(requests)}"
        )

    success_count = 0
    skipped_count = 0
    errors: list[dict[str, Any]] = []
    for index, (item, inlined_response) in enumerate(zip(requests, responses), start=1):
        prepared = prepared_from_manifest_item(item, book_name)
        if prepared.output_path.exists():
            skipped_count += 1
            continue

        error_message = response_error_message(inlined_response)
        if error_message:
            errors.append({"index": index, "outputKey": item.get("outputKey"), "error": error_message})
            continue

        try:
            payload = extract_json_object(extract_response_text(response_payload(inlined_response)))
            normalized = normalize_segments(
                payload,
                page=prepared.column_image.page,
                column=prepared.column_image.column,
            )
        except Exception as exc:
            errors.append({"index": index, "outputKey": item.get("outputKey"), "error": str(exc)})
            continue

        if write_prepared_output(prepared, normalized, model, output_schema):
            success_count += 1
            print(f"[OK] {prepared.column_image.path.name} -> {prepared.output_path}")
        else:
            skipped_count += 1

    job_record["processedAt"] = utc_now_iso()
    job_record["savedCount"] = success_count
    job_record["skippedCount"] = skipped_count
    job_record["errorCount"] = len(errors)
    return success_count, skipped_count, errors


def process_gcs_batch_outputs(
    job_record: dict[str, Any],
    target_dir: Path,
    book_name: str,
    model: str,
    output_schema: str,
    gcloud_path: str,
    gcs_output_uri: str,
    require_all: bool,
) -> tuple[int, int, list[dict[str, Any]]]:
    workspace = gcs_batch_workspace(target_dir)
    if not gcloud_path_has_objects(gcloud_path, gcs_output_uri):
        return 0, 0, []
    output_dir = download_gcs_batch_outputs(gcloud_path, gcs_output_uri, workspace)
    requests_by_output_key = {
        str(item.get("outputKey", "")): item
        for item in job_record.get("requests", [])
        if isinstance(item, dict)
    }
    success_count = 0
    skipped_count = 0
    errors: list[dict[str, Any]] = []
    seen_output_keys: set[str] = set()

    for path in iter_gcs_output_jsonl_files(output_dir):
        with open(path, "r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append({"file": str(path), "line": line_number, "error": str(exc)})
                    continue
                if not isinstance(item, dict):
                    errors.append({"file": str(path), "line": line_number, "error": "output line must be an object"})
                    continue

                output_key = output_key_from_gcs_output(item)
                request_item = requests_by_output_key.get(output_key)
                if request_item is None:
                    errors.append(
                        {
                            "file": str(path),
                            "line": line_number,
                            "outputKey": output_key,
                            "error": "could not match GCS batch response to request",
                        }
                    )
                    continue
                seen_output_keys.add(output_key)
                prepared = prepared_from_manifest_item(request_item, book_name)
                if prepared.output_path.exists():
                    skipped_count += 1
                    continue

                error_payload = item.get("error") or item.get("status")
                if error_payload:
                    errors.append({"outputKey": output_key, "error": str(error_payload)})
                    continue

                try:
                    payload = extract_json_object(extract_response_text(prediction_from_gcs_output(item)))
                    normalized = normalize_segments(
                        payload,
                        page=prepared.column_image.page,
                        column=prepared.column_image.column,
                    )
                except Exception as exc:
                    errors.append({"outputKey": output_key, "error": str(exc)})
                    continue

                if write_prepared_output(prepared, normalized, model, output_schema, process_mode="gcs_batch"):
                    success_count += 1
                    print(f"[OK] {prepared.column_image.path.name} -> {prepared.output_path}")
                else:
                    skipped_count += 1

    if require_all:
        missing_keys = sorted(set(requests_by_output_key) - seen_output_keys)
        for output_key in missing_keys[:100]:
            errors.append({"outputKey": output_key, "error": "missing GCS batch response"})
        if len(missing_keys) > 100:
            errors.append({"error": f"missing {len(missing_keys) - 100} additional GCS batch responses"})

    job_record["gcsHarvestedAt"] = utc_now_iso()
    job_record["gcsHarvestSavedCount"] = success_count
    job_record["gcsHarvestSkippedCount"] = skipped_count
    job_record["gcsHarvestErrorCount"] = len(errors)
    return success_count, skipped_count, errors


def process_completed_gcs_batch_job(
    client: Any,
    job_record: dict[str, Any],
    target_dir: Path,
    book_name: str,
    model: str,
    output_schema: str,
    gcloud_path: str,
    gcs_output_uri: str,
) -> tuple[int, int, list[dict[str, Any]]]:
    job = client.batches.get(name=str(job_record["name"]))
    status = batch_job_status_payload(job, job_record)
    update_job_record_from_status(job_record, status)
    state = str(status["state"])
    if not is_success_job_state(state):
        raise RuntimeError(f"GCS Batch job failed: {job_record['name']} state={state} {status.get('error') or ''}")

    success_count, skipped_count, errors = process_gcs_batch_outputs(
        job_record=job_record,
        target_dir=target_dir,
        book_name=book_name,
        model=model,
        output_schema=output_schema,
        gcloud_path=gcloud_path,
        gcs_output_uri=gcs_output_uri,
        require_all=True,
    )
    job_record["processedAt"] = utc_now_iso()
    job_record["savedCount"] = success_count
    job_record["skippedCount"] = skipped_count
    job_record["errorCount"] = len(errors)
    return success_count, skipped_count, errors


def sync_progress_path(target_dir: Path) -> Path:
    return target_dir / "sync_progress.json"


def sync_errors_path(target_dir: Path) -> Path:
    return target_dir / "sync_errors.json"


def generate_content_sync(client: Any, model: str, prepared: PreparedOcrRequest) -> Any:
    request = prepared.request
    return client.models.generate_content(
        model=model,
        contents=getattr(request, "contents"),
        config=getattr(request, "config"),
    )


def process_sync_ocr(
    client: Any,
    model: str,
    images: list[ColumnImage],
    target_dir: Path,
    output_schema: str,
    max_retries: int,
) -> tuple[int, int]:
    success_count = 0
    skipped_count = 0
    errors: list[dict[str, Any]] = []
    consecutive_api_errors = 0
    max_retries = max(1, max_retries)

    for index, image in enumerate(images, start=1):
        output_path = target_dir / image.output_key
        if output_path.exists():
            skipped_count += 1
            continue

        prepared = prepare_ocr_request(image, target_dir, output_schema)
        response = None
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                response = generate_content_sync(client, model, prepared)
                last_error = None
                consecutive_api_errors = 0
                break
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(min(30, 2 * attempt))

        if last_error is not None:
            consecutive_api_errors += 1
            errors.append(
                {
                    "outputKey": image.output_key,
                    "image": str(image.path).replace("\\", "/"),
                    "error": str(last_error),
                }
            )
            write_json(
                sync_errors_path(target_dir),
                {"errorCount": len(errors), "errors": errors},
            )
            if consecutive_api_errors >= 3:
                raise RuntimeError(
                    f"Sync OCR had {consecutive_api_errors} consecutive API errors; see {sync_errors_path(target_dir)}"
                )
            continue

        try:
            payload = extract_json_object(extract_response_text(response))
            normalized = normalize_segments(
                payload,
                page=prepared.column_image.page,
                column=prepared.column_image.column,
            )
        except Exception as exc:
            errors.append(
                {
                    "outputKey": image.output_key,
                    "image": str(image.path).replace("\\", "/"),
                    "error": str(exc),
                }
            )
            write_json(
                sync_errors_path(target_dir),
                {"errorCount": len(errors), "errors": errors},
            )
            continue

        if write_prepared_output(prepared, normalized, model, output_schema, process_mode="sync"):
            success_count += 1
            print(f"[OK] {image.path.name} -> {prepared.output_path} ({index}/{len(images)})")
        else:
            skipped_count += 1

        if success_count % 25 == 0:
            write_json(
                sync_progress_path(target_dir),
                {
                    "model": model,
                    "ocrOutputSchema": output_schema,
                    "processedAt": utc_now_iso(),
                    "imageCount": len(images),
                    "savedCount": success_count,
                    "skippedCount": skipped_count,
                    "errorCount": len(errors),
                },
            )

    write_json(
        sync_progress_path(target_dir),
        {
            "model": model,
            "ocrOutputSchema": output_schema,
            "processedAt": utc_now_iso(),
            "imageCount": len(images),
            "savedCount": success_count,
            "skippedCount": skipped_count,
            "errorCount": len(errors),
        },
    )
    if errors:
        write_json(
            sync_errors_path(target_dir),
            {"errorCount": len(errors), "errors": errors},
        )
        raise RuntimeError(f"Sync OCR had {len(errors)} failed responses; see {sync_errors_path(target_dir)}")
    return success_count, skipped_count


def wait_for_batch_job(
    client: Any,
    job_record: dict[str, Any],
    poll_interval_seconds: int,
    status_path: Path | None = None,
    on_poll: Any = None,
) -> str:
    while True:
        job = client.batches.get(name=str(job_record["name"]))
        status = batch_job_status_payload(job, job_record)
        update_job_record_from_status(job_record, status)
        if status_path is not None:
            write_json(status_path, status)
        state = str(status["state"])
        stats = status.get("completionStats", {})
        print(
            "[BATCH] "
            f"{job_record['name']} state={state} "
            f"ok={stats.get('successfulCount')} "
            f"failed={stats.get('failedCount')} "
            f"incomplete={stats.get('incompleteCount')}"
        )
        if on_poll is not None:
            on_poll()
        if is_terminal_job_state(state):
            return state
        time.sleep(poll_interval_seconds)


def build_ocr_quality_summary(target_dir: Path, output_schema: str) -> dict[str, Any]:
    files = sorted(target_dir.glob("*.ocr.json"))
    columns: list[dict[str, Any]] = []
    total_segments = 0
    empty_columns = 0
    no_phone_segments = 0
    low_confidence_segments = 0
    multi_phone_segments = 0
    mid_entry_segments = 0
    continued_from_previous_segments = 0
    flagged_segments = 0
    for path in files:
        payload = load_config(path)
        segments = payload.get("segments", [])
        if not isinstance(segments, list):
            segments = []
        segment_count = len(segments)
        total_segments += segment_count
        if segment_count == 0:
            empty_columns += 1

        column_no_phone = 0
        column_low_confidence = 0
        column_multi_phone = 0
        column_mid_entry = 0
        column_continued_from_previous = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            hints = segment.get("entryHints", {})
            phone = str(hints.get("phone", "")).strip() if isinstance(hints, dict) else ""
            phones = segment.get("phones", [])
            confidence = segment.get("confidence", 0.0)
            if not phone:
                no_phone_segments += 1
                column_no_phone += 1
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and confidence < 0.60:
                low_confidence_segments += 1
                column_low_confidence += 1
            if isinstance(phones, list) and len([item for item in phones if str(item).strip()]) > 1:
                multi_phone_segments += 1
                column_multi_phone += 1
            if segment.get("startsMidEntry") is True or segment.get("endsMidEntry") is True:
                mid_entry_segments += 1
                column_mid_entry += 1
            continuity = segment.get("continuityFromPrevious")
            if isinstance(continuity, dict) and continuity.get("sameEntry") is True:
                continued_from_previous_segments += 1
                column_continued_from_previous += 1
            if isinstance(segment.get("reviewFlags"), list) and segment.get("reviewFlags"):
                flagged_segments += 1

        flags: list[str] = []
        if segment_count == 0:
            flags.append("empty_segments")
        if segment_count > 0 and column_no_phone / segment_count > 0.50:
            flags.append("many_segments_without_phone")
        if column_low_confidence:
            flags.append("low_confidence_segments")
        if column_mid_entry:
            flags.append("mid_entry_segments")
        if column_continued_from_previous:
            flags.append("continued_from_previous_segments")

        columns.append(
            {
                "file": path.name,
                "page": payload.get("page"),
                "column": payload.get("column"),
                "segmentCount": segment_count,
                "segmentsWithoutPhone": column_no_phone,
                "lowConfidenceSegments": column_low_confidence,
                "multiPhoneSegments": column_multi_phone,
                "midEntrySegments": column_mid_entry,
                "continuedFromPreviousSegments": column_continued_from_previous,
                "flags": flags,
            }
        )

    suspicious_columns = [column for column in columns if column["flags"]]
    return {
        "promptVersion": PROMPT_VERSION,
        "ocrOutputSchema": output_schema,
        "columnCount": len(files),
        "segmentCount": total_segments,
        "emptyColumnCount": empty_columns,
        "segmentsWithoutPhone": no_phone_segments,
        "lowConfidenceSegments": low_confidence_segments,
        "multiPhoneSegments": multi_phone_segments,
        "midEntrySegments": mid_entry_segments,
        "continuedFromPreviousSegments": continued_from_previous_segments,
        "flaggedSegments": flagged_segments,
        "suspiciousColumnCount": len(suspicious_columns),
        "suspiciousColumns": suspicious_columns,
        "columns": columns,
    }


def process_book_dir(
    book_dir: Path,
    target_dir: Path,
    book_name: str,
    client: Any,
    model: str,
    output_schema: str,
    batch_size: int,
    poll_interval_seconds: int,
    process_mode: str,
    max_retries: int,
    gcs_work_uri: str,
    gcloud_path: str,
) -> tuple[int, int]:
    images = list_column_images(book_dir, book_name)
    if not images:
        return 0, 0

    target_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "book": book_name,
        "splitDir": str(book_dir).replace("\\", "/"),
        "model": model,
        "promptVersion": PROMPT_VERSION,
        "ocrOutputSchema": output_schema,
        "ocrInputMode": "target_image_only",
        "processMode": process_mode,
        "columnCountMetadata": str((book_dir / "column_count.json")).replace("\\", "/"),
        "imageCount": len(images),
    }
    write_json(target_dir / "manifest.json", manifest)

    if process_mode == "sync":
        success_count, skipped_count = process_sync_ocr(
            client=client,
            model=model,
            images=images,
            target_dir=target_dir,
            output_schema=output_schema,
            max_retries=max_retries,
        )
        write_json(target_dir / "ocr_quality.json", build_ocr_quality_summary(target_dir, output_schema))
        return success_count, skipped_count

    pending: list[PreparedOcrRequest] = []
    skipped_existing = 0
    for image in images:
        output_path = target_dir / image.output_key
        if output_path.exists():
            skipped_existing += 1
            continue
        pending.append(prepare_ocr_request(image, target_dir, output_schema))

    if process_mode == "gcs-batch":
        batch_manifest = load_batch_manifest(manifest_path(target_dir))
        if batch_manifest is None:
            if pending:
                batch_manifest = submit_gcs_batch_job(
                    client=client,
                    model=model,
                    prepared=pending,
                    target_dir=target_dir,
                    book_dir=book_dir,
                    book_name=book_name,
                    output_schema=output_schema,
                    gcs_work_uri=gcs_work_uri,
                    gcloud_path=gcloud_path,
                )
            else:
                write_json(target_dir / "ocr_quality.json", build_ocr_quality_summary(target_dir, output_schema))
                return 0, skipped_existing
        else:
            print(f"[BATCH] resume manifest: {manifest_path(target_dir)}")

        success_count = 0
        skipped_count = skipped_existing
        all_errors: list[dict[str, Any]] = []
        gcs_output_uri = str(batch_manifest.get("gcsOutputUri") or gcs_join(gcs_work_uri, "results"))
        for job_record in batch_manifest.get("jobs", []):
            job_requests = job_record.get("requests", [])
            if job_requests and all(Path(str(item.get("outputPath", ""))).exists() for item in job_requests):
                job_record["state"] = str(job_record.get("state") or "OUTPUTS_ALREADY_EXIST")
                job_record["processedAt"] = job_record.get("processedAt") or utc_now_iso()
                continue

            state = str(job_record.get("state", ""))
            if not is_terminal_job_state(state):
                def harvest_partial_outputs() -> None:
                    saved, skipped, errors = process_gcs_batch_outputs(
                        job_record=job_record,
                        target_dir=target_dir,
                        book_name=book_name,
                        model=model,
                        output_schema=output_schema,
                        gcloud_path=gcloud_path,
                        gcs_output_uri=gcs_output_uri,
                        require_all=False,
                    )
                    if saved or skipped or errors:
                        write_json(manifest_path(target_dir), batch_manifest)
                        if errors:
                            write_json(
                                target_dir / "batch_partial_errors.json",
                                {
                                    "book": book_name,
                                    "errorCount": len(errors),
                                    "errors": errors,
                                },
                            )

                state = wait_for_batch_job(
                    client,
                    job_record,
                    poll_interval_seconds,
                    target_dir / "batch_status.json",
                    harvest_partial_outputs,
                )
                write_json(manifest_path(target_dir), batch_manifest)

            if is_success_job_state(state):
                saved, skipped, errors = process_completed_gcs_batch_job(
                    client=client,
                    job_record=job_record,
                    target_dir=target_dir,
                    book_name=book_name,
                    model=model,
                    output_schema=output_schema,
                    gcloud_path=gcloud_path,
                    gcs_output_uri=gcs_output_uri,
                )
                success_count += saved
                skipped_count += skipped
                all_errors.extend(errors)
                write_json(manifest_path(target_dir), batch_manifest)
            else:
                raise RuntimeError(f"GCS Batch job did not succeed: {job_record.get('name')} state={state}")

        if all_errors:
            write_json(
                target_dir / "batch_errors.json",
                {
                    "book": book_name,
                    "errorCount": len(all_errors),
                    "errors": all_errors,
                },
            )
            raise RuntimeError(f"GCS Batch OCR had {len(all_errors)} failed responses; see {target_dir / 'batch_errors.json'}")

        write_json(target_dir / "ocr_quality.json", build_ocr_quality_summary(target_dir, output_schema))
        return success_count, skipped_count

    batch_manifest = load_batch_manifest(manifest_path(target_dir))
    if batch_manifest is None:
        if pending:
            batch_manifest = submit_batch_jobs(
                client=client,
                model=model,
                prepared=pending,
                target_dir=target_dir,
                book_name=book_name,
                output_schema=output_schema,
                batch_size=batch_size,
            )
        else:
            write_json(target_dir / "ocr_quality.json", build_ocr_quality_summary(target_dir, output_schema))
            return 0, skipped_existing
    else:
        print(f"[BATCH] resume manifest: {manifest_path(target_dir)}")

    success_count = 0
    skipped_count = skipped_existing
    all_errors: list[dict[str, Any]] = []
    for job_record in batch_manifest.get("jobs", []):
        job_requests = job_record.get("requests", [])
        if job_requests and all(Path(str(item.get("outputPath", ""))).exists() for item in job_requests):
            job_record["state"] = str(job_record.get("state") or "OUTPUTS_ALREADY_EXIST")
            job_record["processedAt"] = job_record.get("processedAt") or utc_now_iso()
            continue

        state = str(job_record.get("state", ""))
        if not is_terminal_job_state(state):
            state = wait_for_batch_job(client, job_record, poll_interval_seconds, target_dir / "batch_status.json")
            write_json(manifest_path(target_dir), batch_manifest)

        if is_success_job_state(state):
            saved, skipped, errors = process_completed_batch_job(
                client=client,
                job_record=job_record,
                book_name=book_name,
                model=model,
                output_schema=output_schema,
            )
            success_count += saved
            skipped_count += skipped
            all_errors.extend(errors)
            write_json(manifest_path(target_dir), batch_manifest)
        else:
            raise RuntimeError(f"Batch job did not succeed: {job_record.get('name')} state={state}")

    if all_errors:
        write_json(
            target_dir / "batch_errors.json",
            {
                "book": book_name,
                "errorCount": len(all_errors),
                "errors": all_errors,
            },
        )
        raise RuntimeError(f"Batch OCR had {len(all_errors)} failed responses; see {target_dir / 'batch_errors.json'}")

    write_json(target_dir / "ocr_quality.json", build_ocr_quality_summary(target_dir, output_schema))
    return success_count, skipped_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split 済みカラム画像を Gemini で OCR して JSON に保存します。"
    )
    parser.add_argument(
        "--split-root",
        type=Path,
        default=Path("output") / "split",
        help="split_columns.py の出力ルート",
    )
    parser.add_argument(
        "--ocr-root",
        type=Path,
        default=Path("output") / "ocr_columns",
        help="OCR JSON の出力ルート",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Gemini 設定を含む config.json のパス",
    )
    parser.add_argument(
        "--book",
        type=str,
        default="",
        help="特定の電話帳ディレクトリだけ処理する場合の名前",
    )
    parser.add_argument(
        "--schema",
        choices=sorted(OCR_OUTPUT_SCHEMAS),
        default=DEFAULT_OCR_OUTPUT_SCHEMA,
        help="compact はAPI出力を短いJSONにして保存時に従来形式へ展開する。standard は従来の詳細JSON",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="",
        help="config.json の gemini.ocrModel を一時的に上書きする",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="1つの Gemini Batch job に入れるカラム数。0なら config.json の gemini.batchSize または 100",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=int,
        default=60,
        help="Batch job 完了待ちの確認間隔",
    )
    parser.add_argument(
        "--process-mode",
        choices=("batch", "gcs-batch", "sync"),
        default="batch",
        help="OCR の実行方式。Agent Platform/Vertex AI の Batch は gcs-batch を使う",
    )
    parser.add_argument(
        "--gcs-work-uri",
        type=str,
        default="",
        help="gcs-batch の作業 GCS prefix。例: gs://bucket/path",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    gemini_cfg = config.get("gemini")
    client = create_gemini_client(gemini_cfg)
    model = args.model or resolve_gemini_model(gemini_cfg)
    batch_size = args.batch_size or int(gemini_cfg.get("batchSize", 100))
    max_retries = int(gemini_cfg.get("maxRetries", 3))
    gcs_work_uri = resolve_gcs_work_uri(gemini_cfg, args.gcs_work_uri) if args.process_mode == "gcs-batch" else ""
    gcloud_path = resolve_gcloud_path(gemini_cfg) if args.process_mode == "gcs-batch" else ""
    print(f"[INFO] Gemini auth={gemini_auth_label(gemini_cfg)} model={model} mode={args.process_mode}")

    jobs = resolve_ocr_jobs(args.split_root, args.ocr_root, args.book)

    total_success = 0
    total_skipped = 0
    for job in jobs:
        if not job.book_dir.exists():
            raise FileNotFoundError(f"電話帳ディレクトリが見つかりません: {job.book_dir}")
        print(f"\n=== OCR {job.book_name} ===")
        if args.process_mode == "gcs-batch":
            with single_process_lock(job.target_dir):
                success_count, skipped_count = process_book_dir(
                    book_dir=job.book_dir,
                    target_dir=job.target_dir,
                    book_name=job.book_name,
                    client=client,
                    model=model,
                    output_schema=args.schema,
                    batch_size=batch_size,
                    poll_interval_seconds=max(5, args.poll_interval_seconds),
                    process_mode=args.process_mode,
                    max_retries=max_retries,
                    gcs_work_uri=gcs_work_uri,
                    gcloud_path=gcloud_path,
                )
        else:
            success_count, skipped_count = process_book_dir(
                book_dir=job.book_dir,
                target_dir=job.target_dir,
                book_name=job.book_name,
                client=client,
                model=model,
                output_schema=args.schema,
                batch_size=batch_size,
                poll_interval_seconds=max(5, args.poll_interval_seconds),
                process_mode=args.process_mode,
                max_retries=max_retries,
                gcs_work_uri=gcs_work_uri,
                gcloud_path=gcloud_path,
            )
        total_success += success_count
        total_skipped += skipped_count
        print(f"saved={success_count}, skipped={skipped_count}")

    print(f"\nCompleted. saved={total_success}, skipped={total_skipped}")


if __name__ == "__main__":
    main()
