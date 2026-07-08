#!/usr/bin/env python3
"""Use address frequency and Gemini to repair suspicious CSV address fields."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ponka.address_normalization import (
    NEIGHBORING_MUNICIPALITY_ABBREVIATIONS,
    address_profile_for_date,
    OSAKA_CITY_WARD_ABBREVIATIONS,
)
from ponka.gemini_client import create_gemini_client


CSV_HEADER = ["電話番号", "名前", "都道府県", "市区町村", "町域", "番地"]

CORRECTIONS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string", "enum": ["replace", "keep"]},
                    "correctedId": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "action", "correctedId", "confidence", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["corrections"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LocationKey:
    prefecture: str
    municipality: str
    area: str

    def as_id(self) -> str:
        return "\t".join([self.prefecture, self.municipality, self.area])

    def as_dict(self) -> dict[str, str]:
        return {
            "都道府県": self.prefecture,
            "市区町村": self.municipality,
            "町域": self.area,
        }


@dataclass(frozen=True)
class SuspiciousLocation:
    id: str
    key: LocationKey
    count: int
    reasons: list[str]
    samples: list[dict[str, str]]
    candidates: list[dict[str, Any]]


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def comparable_text(value: str) -> str:
    normalized = normalize_text(value)
    return re.sub(r"[\s,、，・･.．\-‐ー―−–—()（）\[\]［］{}]+", "", normalized)


def location_key(row: dict[str, str]) -> LocationKey:
    return LocationKey(
        normalize_text(row.get("都道府県", "")),
        normalize_text(row.get("市区町村", "")),
        normalize_text(row.get("町域", "")),
    )


def resolve_as_of_date(value: str, input_csv: Path | None = None) -> str:
    if value:
        return value
    if input_csv is not None:
        match = re.search(r"(19[0-9]{2}-[0-9]{2}-[0-9]{2})", input_csv.name)
        if match:
            return match.group(1)
    return "1963-02-01"


def allowed_municipalities(as_of: str | None = None) -> list[str]:
    profile = address_profile_for_date(as_of)
    values = {"大阪市"}
    values.update(f"大阪市{ward}" for ward in profile.wards)
    values.update(profile.cities)
    values.update(profile.towns_villages.values())
    values.update(municipality for _, municipality in NEIGHBORING_MUNICIPALITY_ABBREVIATIONS.values())
    return sorted(values)


def municipality_hint_prefixes(as_of: str | None = None) -> list[str]:
    profile = address_profile_for_date(as_of)
    prefixes = set(OSAKA_CITY_WARD_ABBREVIATIONS)
    prefixes.update(profile.wards)
    prefixes.update(profile.municipality_abbreviations)
    prefixes.update(profile.cities)
    prefixes.update(profile.towns_villages)
    prefixes.update(municipality.rsplit("郡", 1)[-1] for municipality in profile.towns_villages.values())
    prefixes.update(name for name, _ in NEIGHBORING_MUNICIPALITY_ABBREVIATIONS.values())
    return sorted({prefix for prefix in prefixes if len(prefix) >= 1}, key=len, reverse=True)


def local_municipality_name(value: str) -> str:
    local_name = value.rsplit("郡", 1)[-1]
    for suffix in ("市", "町", "村", "区"):
        if local_name.endswith(suffix):
            return local_name[: -len(suffix)]
    return local_name


def address_text_reasons(key: LocationKey, as_of: str | None = None) -> list[str]:
    area = normalize_text(key.area)
    municipality = normalize_text(key.municipality)
    reasons: list[str] = []
    if any(separator in area for separator in (",", "、", "，")):
        reasons.append("area_contains_separator")
    if any(token in area for token in ("大阪府", "大阪市")):
        reasons.append("area_contains_prefecture_or_city")
    if re.search(r"[^\s]{1,12}区", area):
        reasons.append("area_contains_ward_name")
    if municipality and area.startswith(local_municipality_name(municipality)) and area != local_municipality_name(municipality):
        reasons.append("area_starts_with_own_municipality_name")
    for prefix in municipality_hint_prefixes(as_of):
        if len(prefix) == 1 and not municipality.startswith("大阪市"):
            continue
        if area.startswith(prefix) and area != prefix:
            reasons.append("area_starts_with_municipality_hint")
            break
    return sorted(set(reasons))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in CSV_HEADER if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV header lacks required columns: {', '.join(missing)}")
        return [{column: row.get(column, "") for column in CSV_HEADER} for row in reader]


def write_csv_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def location_counts(rows: list[dict[str, str]]) -> Counter[LocationKey]:
    return Counter(location_key(row) for row in rows if location_key(row).area)


def sample_rows(rows_by_location: dict[LocationKey, list[dict[str, str]]], key: LocationKey, limit: int) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for row in rows_by_location.get(key, [])[:limit]:
        samples.append(
            {
                "電話番号": row.get("電話番号", ""),
                "名前": row.get("名前", ""),
                "番地": row.get("番地", ""),
            }
        )
    return samples


def similarity(left: LocationKey, right: LocationKey) -> float:
    left_area = comparable_text(left.area)
    right_area = comparable_text(right.area)
    if not left_area or not right_area:
        return 0.0
    area_score = SequenceMatcher(None, left_area, right_area).ratio()
    municipality_score = 1.0 if left.municipality == right.municipality else 0.82
    return area_score * municipality_score


def build_common_candidates(
    key: LocationKey,
    counts: Counter[LocationKey],
    common_min_count: int,
    min_similarity: float,
    max_candidates: int,
    candidate_pool: list[tuple[LocationKey, int]] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, LocationKey, int]] = []
    for candidate, count in candidate_pool or list(counts.items()):
        if candidate == key or count < common_min_count or not candidate.area:
            continue
        if candidate.prefecture != key.prefecture:
            continue
        score = similarity(key, candidate)
        if score < min_similarity:
            continue
        candidates.append((score, candidate, count))

    candidates.sort(key=lambda item: (item[0], item[2]), reverse=True)
    return [
        {
            "id": candidate.as_id(),
            "count": count,
            "similarity": round(score, 4),
            "address": candidate.as_dict(),
        }
        for score, candidate, count in candidates[:max_candidates]
    ]


def fallback_common_candidates(
    key: LocationKey,
    counts: Counter[LocationKey],
    common_min_count: int,
    max_candidates: int,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, LocationKey]] = []
    key_area = comparable_text(key.area)
    for candidate, count in counts.items():
        if candidate == key or count < common_min_count or not candidate.area:
            continue
        if candidate.prefecture != key.prefecture:
            continue
        if candidate.municipality != key.municipality:
            continue
        candidate_area = comparable_text(candidate.area)
        if key_area and candidate_area and key_area[0] != candidate_area[0]:
            continue
        candidates.append((count, candidate))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": candidate.as_id(),
            "count": count,
            "similarity": round(similarity(key, candidate), 4),
            "address": candidate.as_dict(),
        }
        for count, candidate in candidates[:max_candidates]
    ]


def select_suspicious_locations(
    rows: list[dict[str, str]],
    rare_max_count: int,
    common_min_count: int,
    min_similarity: float,
    max_candidates: int,
    sample_limit: int,
    max_items: int,
    as_of: str | None = None,
) -> list[SuspiciousLocation]:
    counts = location_counts(rows)
    common_by_prefecture_initial: dict[tuple[str, str], list[tuple[LocationKey, int]]] = defaultdict(list)
    common_by_prefecture_municipality: dict[tuple[str, str], list[tuple[LocationKey, int]]] = defaultdict(list)
    for candidate, count in counts.items():
        candidate_area = comparable_text(candidate.area)
        if count < common_min_count or not candidate_area:
            continue
        common_by_prefecture_initial[(candidate.prefecture, candidate_area[0])].append((candidate, count))
        common_by_prefecture_municipality[(candidate.prefecture, candidate.municipality)].append((candidate, count))

    rows_by_location: dict[LocationKey, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = location_key(row)
        if key.area:
            rows_by_location[key].append(row)

    suspicious: list[SuspiciousLocation] = []
    for key, count in sorted(counts.items(), key=lambda item: (item[1], item[0].as_id())):
        reasons = address_text_reasons(key, as_of=as_of)
        if count <= rare_max_count:
            reasons.append("rare_location")
        reasons = sorted(set(reasons))
        if not reasons:
            continue
        key_area = comparable_text(key.area)
        candidate_pool = list(common_by_prefecture_municipality.get((key.prefecture, key.municipality), []))
        if key_area:
            candidate_pool.extend(common_by_prefecture_initial.get((key.prefecture, key_area[0]), []))
        if not candidate_pool:
            candidate_pool = list(common_by_prefecture_municipality.get((key.prefecture, key.municipality), []))
        candidates = build_common_candidates(
            key=key,
            counts=counts,
            common_min_count=common_min_count,
            min_similarity=min_similarity,
            max_candidates=max_candidates,
            candidate_pool=list(dict(candidate_pool).items()),
        )
        if not candidates and any(reason != "rare_location" for reason in reasons):
            candidates = fallback_common_candidates(
                key=key,
                counts=counts,
                common_min_count=common_min_count,
                max_candidates=max_candidates,
            )
        if not candidates:
            continue
        suspicious.append(
            SuspiciousLocation(
                id=key.as_id(),
                key=key,
                count=count,
                reasons=reasons,
                samples=sample_rows(rows_by_location, key, sample_limit),
                candidates=candidates,
            )
        )
        if max_items and len(suspicious) >= max_items:
            break
    return suspicious


def historical_context_rules(as_of: str | None = None) -> list[str]:
    if as_of and as_of >= "1968-03-01":
        return [
            "This phonebook is dated 1968-03-01. Use Osaka City's historical wards as of that date.",
            "Do not normalize old Higashi-ku/Minami-ku to Chuo-ku.",
            "Do not normalize old Kita-ku/Oyodo-ku to present-day Kita-ku.",
            "Do not use Yodogawa-ku, Tsurumi-ku, Suminoe-ku, or Hirano-ku for Osaka City addresses in this book.",
            "Fuse-shi, Kawachi-shi, and Hiraoka-shi had already become Higashiosaka-shi by 1968-03-01.",
        ]
    return [
        "This phonebook uses historical Osaka-area municipalities for its publication date.",
    ]


def build_gemini_prompt(items: list[SuspiciousLocation], as_of: str | None = None) -> str:
    payload = {
        "task": "Historical Japanese phonebook CSV address repair",
        "asOfDate": as_of or "1963-02-01",
        "rules": [
            "Each item is a rare location group from a CSV: 都道府県, 市区町村, 町域.",
            "Choose action=replace only when the rare 町域 is very likely an OCR/read normalization error of one of the candidates.",
            "Choose action=keep for real rare addresses, ambiguous cases, official references, or when the candidate is only vaguely similar.",
            "If replacing, correctedId must exactly match one candidate id. Do not invent new addresses.",
            "番地 is not included in the decision and will be preserved by the program.",
        ]
        + historical_context_rules(as_of),
        "allowedMunicipalities": allowed_municipalities(as_of),
        "items": [
            {
                "id": item.id,
                "count": item.count,
                "suspiciousReasons": item.reasons,
                "address": item.key.as_dict(),
                "samples": item.samples,
                "candidates": item.candidates,
            }
            for item in items
        ],
        "outputSchema": {
            "corrections": [
                {
                    "id": "same as item id",
                    "action": "replace or keep",
                    "correctedId": "candidate id when action=replace, otherwise empty",
                    "confidence": 0.0,
                    "reason": "short Japanese reason",
                }
            ]
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def suspicious_location_from_report(item: dict[str, Any]) -> SuspiciousLocation:
    address = item.get("address", {})
    if not isinstance(address, dict):
        address = {}
    return SuspiciousLocation(
        id=str(item.get("id", "")),
        key=LocationKey(
            str(address.get("都道府県", "")),
            str(address.get("市区町村", "")),
            str(address.get("町域", "")),
        ),
        count=int(item.get("count", 0)),
        reasons=[str(reason) for reason in item.get("suspiciousReasons", []) if str(reason)],
        samples=[sample for sample in item.get("samples", []) if isinstance(sample, dict)],
        candidates=[candidate for candidate in item.get("candidates", []) if isinstance(candidate, dict)],
    )


def load_suspicious_locations(path: Path) -> list[SuspiciousLocation]:
    payload = load_config(path)
    items = payload.get("suspiciousLocations", [])
    if not isinstance(items, list):
        raise ValueError("--candidates-json must contain suspiciousLocations array")
    return [suspicious_location_from_report(item) for item in items if isinstance(item, dict)]


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


def extract_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    candidates = getattr(response, "candidates", None)
    if not isinstance(candidates, list):
        raise ValueError("Gemini response did not contain candidates")
    parts_text: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None)
        if not isinstance(parts, list):
            continue
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str):
                parts_text.append(part_text)
    joined = "".join(parts_text).strip()
    if not joined:
        raise ValueError("Gemini response text was empty")
    return joined


def load_config(config_path: Path) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_model(gemini_cfg: dict[str, Any], override: str = "") -> str:
    aliases = {
        "gemini-3.1-flash-preview": "gemini-3-flash-preview",
        "models/gemini-3.1-flash-preview": "gemini-3-flash-preview",
        "gemini-3.1-flash": "gemini-3-flash-preview",
        "models/gemini-3.1-flash": "gemini-3-flash-preview",
    }
    configured = override or gemini_cfg.get("addressRepairModel") or gemini_cfg.get("textModel") or gemini_cfg.get("ocrModel") or "gemini-2.5-flash"
    return aliases.get(str(configured), str(configured))


def resolve_openai_model(openai_cfg: dict[str, Any], override: str = "") -> str:
    return str(override or openai_cfg.get("chatModel") or "gpt-5.5")


def progress_model_label(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def normalize_chunk_corrections(
    payload: dict[str, Any],
    chunk: list[SuspiciousLocation],
    progress_path: Path | None,
) -> list[dict[str, Any]]:
    chunk_corrections = payload.get("corrections", [])
    if not isinstance(chunk_corrections, list):
        raise ValueError("AI response corrections must be an array")
    valid_chunk_corrections = [item for item in chunk_corrections if isinstance(item, dict)]
    returned_ids = {str(item.get("id", "")) for item in valid_chunk_corrections}
    missing_keep_decisions = [
        {
            "id": item.id,
            "action": "keep",
            "correctedId": "",
            "confidence": 0.0,
            "reason": "AI response omitted this item; kept conservatively",
        }
        for item in chunk
        if item.id not in returned_ids
    ]
    if len(missing_keep_decisions) > max(3, len(chunk) // 10):
        write_json(
            (progress_path or Path("address_repair_decisions.partial.json")).with_suffix(".last_response.json"),
            {
                "missingCount": len(missing_keep_decisions),
                "chunkSize": len(chunk),
                "response": payload,
            },
        )
        raise RuntimeError(
            f"AI omitted too many correction decisions: missing={len(missing_keep_decisions)} chunk={len(chunk)}"
        )
    if missing_keep_decisions:
        print(f"[AI] filled missing keep decisions={len(missing_keep_decisions)}")
    return valid_chunk_corrections + missing_keep_decisions


def append_progress_decisions(
    corrections: list[dict[str, Any]],
    progress_path: Path | None,
    provider: str,
    model: str,
) -> None:
    if progress_path is None:
        return
    write_json(
        progress_path,
        {
            "provider": provider,
            "model": model,
            "decisionCount": len(corrections),
            "decisions": corrections,
        },
    )


def remaining_items(items: list[SuspiciousLocation], corrections: list[dict[str, Any]]) -> list[SuspiciousLocation]:
    decided_ids = {str(decision.get("id", "")) for decision in corrections if isinstance(decision, dict)}
    remaining = [item for item in items if item.id not in decided_ids]
    if decided_ids:
        print(f"[AI] resume decisions={len(decided_ids)} remaining={len(remaining)}")
    return remaining


def deterministic_area_variants(item: SuspiciousLocation, as_of: str | None = None) -> set[str]:
    area = normalize_text(item.key.area)
    if not any(separator in area for separator in (",", "、", "，")) and not any(
        token in area for token in ("大阪府", "大阪市")
    ):
        return set()
    variants = {comparable_text(area)}
    if any(separator in area for separator in (",", "、", "，")):
        variants.add(comparable_text(area.replace(",", "").replace("、", "").replace("，", "")))
    for prefix in municipality_hint_prefixes(as_of):
        if len(prefix) == 1:
            continue
        if area.startswith(prefix) and area != prefix:
            variants.add(comparable_text(area[len(prefix) :].lstrip(",、，")))
    return {variant for variant in variants if variant}


def deterministic_decisions(
    items: list[SuspiciousLocation],
    existing_decisions: list[dict[str, Any]],
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    decided_ids = {str(decision.get("id", "")) for decision in existing_decisions if isinstance(decision, dict)}
    decisions: list[dict[str, Any]] = []
    for item in items:
        if item.id in decided_ids:
            continue
        variants = deterministic_area_variants(item, as_of)
        exact_candidates = [
            candidate
            for candidate in item.candidates
            if comparable_text(str(candidate.get("address", {}).get("町域", ""))) in variants
        ]
        if len(exact_candidates) != 1:
            continue
        candidate = exact_candidates[0]
        decisions.append(
            {
                "id": item.id,
                "action": "replace",
                "correctedId": str(candidate.get("id", "")),
                "confidence": 0.99,
                "reason": "決定的補正: 区切り記号または自治体略記を除くと頻出候補と完全一致",
            }
        )
    if decisions:
        print(f"[AUTO] deterministic decisions={len(decisions)}")
    return decisions


def run_gemini_corrections(
    items: list[SuspiciousLocation],
    config_path: Path,
    model_override: str,
    chunk_size: int,
    existing_decisions: list[dict[str, Any]] | None = None,
    progress_path: Path | None = None,
    as_of: str | None = None,
    max_retries: int = 6,
    retry_base_seconds: int = 30,
) -> list[dict[str, Any]]:
    config = load_config(config_path)
    gemini_cfg = config.get("gemini")

    from google.genai import types

    client = create_gemini_client(gemini_cfg)
    model = resolve_model(gemini_cfg, model_override)

    corrections: list[dict[str, Any]] = list(existing_decisions or [])
    remaining = remaining_items(items, corrections)

    for offset in range(0, len(remaining), chunk_size):
        chunk = remaining[offset : offset + chunk_size]
        for attempt in range(max(1, max_retries)):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=build_gemini_prompt(chunk, as_of=as_of),
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You repair OCR-derived historical Japanese address groups. "
                            "Return JSON only. Prefer keep unless a candidate is clearly the intended address. "
                            + " ".join(historical_context_rules(as_of))
                        ),
                        response_mime_type="application/json",
                        response_schema=types.Schema.model_validate(CORRECTIONS_JSON_SCHEMA),
                    ),
                )
                break
            except Exception as exc:
                retryable_status = any(status in str(exc) for status in ("429", "500", "502", "503", "504"))
                if not retryable_status or attempt == max(1, max_retries) - 1:
                    raise
                sleep_seconds = min(900, max(1, retry_base_seconds) * (2**attempt))
                print(f"[AI] retryable Gemini error; retrying in {sleep_seconds}s: {exc}")
                time.sleep(sleep_seconds)
        payload = extract_json_object(extract_response_text(response))
        corrections.extend(normalize_chunk_corrections(payload, chunk, progress_path))
        append_progress_decisions(corrections, progress_path, "gemini", model)
        print(f"[AI] corrected decisions {len(corrections)}/{len(items)}")
    return corrections


def post_openai_chat_completion(openai_cfg: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    base_url = str(openai_cfg.get("baseUrl") or "https://api.openai.com/v1/chat/completions")
    api_key = str(openai_cfg.get("apiKey") or "")
    timeout_seconds = max(30, int(openai_cfg.get("timeoutMs", 300_000)) // 1000)
    max_retries = max(1, int(openai_cfg.get("maxRetries", 3)))
    if not api_key:
        raise RuntimeError("config.json に openai.apiKey が必要です。")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(max_retries):
        request = urllib.request.Request(
            base_url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if attempt == max_retries - 1:
                raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            if attempt == max_retries - 1:
                raise RuntimeError(f"OpenAI API request failed: {exc}") from exc
        time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def extract_openai_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI response did not contain choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        joined = "".join(part for part in parts if isinstance(part, str)).strip()
        if joined:
            return joined
    raise ValueError("OpenAI response text was empty")


def run_openai_corrections(
    items: list[SuspiciousLocation],
    config_path: Path,
    model_override: str,
    chunk_size: int,
    existing_decisions: list[dict[str, Any]] | None = None,
    progress_path: Path | None = None,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    config = load_config(config_path)
    openai_cfg = config.get("openai")
    if not isinstance(openai_cfg, dict):
        raise RuntimeError("config.json に openai 設定が必要です。")
    model = resolve_openai_model(openai_cfg, model_override)

    corrections: list[dict[str, Any]] = list(existing_decisions or [])
    remaining = remaining_items(items, corrections)
    for offset in range(0, len(remaining), chunk_size):
        chunk = remaining[offset : offset + chunk_size]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You repair OCR-derived historical Japanese address groups. "
                        "Return JSON only. Prefer keep unless a candidate is clearly the intended address. "
                        + " ".join(historical_context_rules(as_of))
                    ),
                },
                {"role": "user", "content": build_gemini_prompt(chunk, as_of=as_of)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "address_repair_corrections",
                    "strict": True,
                    "schema": CORRECTIONS_JSON_SCHEMA,
                },
            },
            "max_completion_tokens": int(openai_cfg.get("maxCompletionTokens", 24_000)),
        }
        response = post_openai_chat_completion(openai_cfg, payload)
        response_payload = extract_json_object(extract_openai_response_text(response))
        corrections.extend(normalize_chunk_corrections(response_payload, chunk, progress_path))
        append_progress_decisions(corrections, progress_path, "openai", model)
        print(f"[AI] corrected decisions {len(corrections)}/{len(items)}")
    return corrections


def validate_corrections(
    items: list[SuspiciousLocation],
    decisions: list[dict[str, Any]],
    min_confidence: float,
    allow_municipality_change: bool = False,
) -> dict[str, LocationKey]:
    item_by_id = {item.id: item for item in items}
    corrections: dict[str, LocationKey] = {}
    for decision in decisions:
        item_id = str(decision.get("id", ""))
        action = str(decision.get("action", "keep"))
        if action != "replace" or item_id not in item_by_id:
            continue
        confidence = float(decision.get("confidence", 0.0))
        if confidence < min_confidence:
            continue
        corrected_id = str(decision.get("correctedId", ""))
        candidate_ids = {str(candidate["id"]): candidate for candidate in item_by_id[item_id].candidates}
        candidate = candidate_ids.get(corrected_id)
        if candidate is None:
            continue
        address = candidate["address"]
        if not allow_municipality_change and (
            str(address["都道府県"]) != item_by_id[item_id].key.prefecture
            or str(address["市区町村"]) != item_by_id[item_id].key.municipality
        ):
            continue
        corrections[item_id] = LocationKey(
            str(address["都道府県"]),
            str(address["市区町村"]),
            str(address["町域"]),
        )
    return corrections


def apply_location_corrections(rows: list[dict[str, str]], corrections: dict[str, LocationKey]) -> tuple[list[dict[str, str]], int]:
    repaired: list[dict[str, str]] = []
    changed = 0
    for row in rows:
        updated = dict(row)
        corrected = corrections.get(location_key(row).as_id())
        if corrected is not None:
            updated["都道府県"] = corrected.prefecture
            updated["市区町村"] = corrected.municipality
            updated["町域"] = corrected.area
            changed += 1
        repaired.append(updated)
    return repaired, changed


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV の住所出現頻度から疑わしい町域を AI で補正して再出力します。")
    parser.add_argument("--input-csv", type=Path, required=True, help="入力 csv または csv.gz")
    parser.add_argument("--output-csv", type=Path, required=True, help="補正後 csv または csv.gz")
    parser.add_argument("--report-json", type=Path, required=True, help="候補・AI判断・適用件数の JSON")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="AI API 設定を含む config.json")
    parser.add_argument("--provider", choices=("auto", "openai", "gemini"), default="auto", help="住所補正に使う AI provider。auto は openai 設定を優先")
    parser.add_argument("--model", type=str, default="", help="住所補正に使う model")
    parser.add_argument("--rare-max-count", type=int, default=2, help="この件数以下の町域を疑わしい候補にする")
    parser.add_argument("--common-min-count", type=int, default=8, help="補正候補として採用する町域の最小件数")
    parser.add_argument("--min-similarity", type=float, default=0.72, help="候補町域との最低類似度")
    parser.add_argument("--max-candidates", type=int, default=8, help="疑わしい町域ごとの候補数")
    parser.add_argument("--sample-limit", type=int, default=5, help="AI に渡すサンプル行数")
    parser.add_argument("--max-items", type=int, default=0, help="AI 判定する疑わしい町域の最大数。0なら全件")
    parser.add_argument("--chunk-size", type=int, default=200, help="1回の AI 呼び出しに含める疑わしい町域数")
    parser.add_argument("--min-confidence", type=float, default=0.75, help="適用する AI 補正の最低 confidence")
    parser.add_argument("--allow-municipality-change", action="store_true", help="AI補正で市区町村の変更も許可する")
    parser.add_argument("--as-of-date", type=str, default="", help="住所辞書の基準日。未指定なら入力CSV名から推定")
    parser.add_argument("--ai-max-retries", type=int, default=6, help="一時的なAI APIエラーの再試行回数")
    parser.add_argument("--ai-retry-base-seconds", type=int, default=30, help="AI API再試行の初期待ち秒数")
    parser.add_argument("--disable-deterministic", action="store_true", help="AI前の決定的な完全一致補正を無効化する")
    parser.add_argument("--decisions-json", type=Path, default=None, help="既存の AI 判断 JSON を使う場合の入力")
    parser.add_argument("--candidates-json", type=Path, default=None, help="既存の候補レポート JSON を使い、候補抽出を省略する")
    parser.add_argument("--decisions-progress-json", type=Path, default=None, help="AI 判断をチャンクごとに保存する JSON")
    parser.add_argument("--candidates-only", action="store_true", help="AI を呼ばず、疑わしい住所候補リストだけ作る")
    parser.add_argument("--dry-run", action="store_true", help="CSV は書かず report だけ出力する")
    args = parser.parse_args()

    as_of = resolve_as_of_date(args.as_of_date, args.input_csv)
    rows = read_csv_rows(args.input_csv)
    if args.candidates_json:
        suspicious = load_suspicious_locations(args.candidates_json)
        if args.max_items:
            suspicious = suspicious[: args.max_items]
    else:
        suspicious = select_suspicious_locations(
            rows=rows,
            rare_max_count=args.rare_max_count,
            common_min_count=args.common_min_count,
            min_similarity=args.min_similarity,
            max_candidates=args.max_candidates,
            sample_limit=args.sample_limit,
            max_items=args.max_items,
            as_of=as_of,
        )
    print(f"[INFO] rows={len(rows)} suspiciousLocations={len(suspicious)} asOf={as_of}")

    selected_provider = ""
    selected_model = ""

    if args.decisions_json:
        decisions_payload = load_config(args.decisions_json)
        decisions = decisions_payload.get("decisions", [])
        if not isinstance(decisions, list):
            raise ValueError("--decisions-json must contain decisions array")
        selected_provider = str(decisions_payload.get("provider") or "")
        selected_model = str(decisions_payload.get("model") or "")
    elif args.candidates_only:
        decisions = []
    elif suspicious:
        progress_path = args.decisions_progress_json or args.report_json.with_name(
            args.report_json.stem + ".decisions.partial.json"
        )
        existing_decisions = []
        if progress_path.exists():
            progress_payload = load_config(progress_path)
            progress_decisions = progress_payload.get("decisions", [])
            if isinstance(progress_decisions, list):
                existing_decisions = [item for item in progress_decisions if isinstance(item, dict)]
        if not args.disable_deterministic:
            existing_decisions.extend(deterministic_decisions(suspicious, existing_decisions, as_of))
            append_progress_decisions(existing_decisions, progress_path, selected_provider or "auto", selected_model)
        config = load_config(args.config)
        provider = args.provider
        if provider == "auto":
            provider = "openai" if isinstance(config.get("openai"), dict) else "gemini"
        selected_provider = provider
        if provider == "openai":
            openai_cfg = config.get("openai")
            if isinstance(openai_cfg, dict):
                selected_model = resolve_openai_model(openai_cfg, args.model)
            decisions = run_openai_corrections(
                suspicious,
                config_path=args.config,
                model_override=args.model,
                chunk_size=max(1, args.chunk_size),
                existing_decisions=existing_decisions,
                progress_path=progress_path,
                as_of=as_of,
                max_retries=args.ai_max_retries,
                retry_base_seconds=args.ai_retry_base_seconds,
            )
        else:
            gemini_cfg = config.get("gemini")
            if isinstance(gemini_cfg, dict):
                selected_model = resolve_model(gemini_cfg, args.model)
            decisions = run_gemini_corrections(
                suspicious,
                config_path=args.config,
                model_override=args.model,
                chunk_size=max(1, args.chunk_size),
                existing_decisions=existing_decisions,
                progress_path=progress_path,
                as_of=as_of,
            )
    else:
        decisions = []

    corrections = validate_corrections(
        suspicious,
        decisions,
        min_confidence=args.min_confidence,
        allow_municipality_change=args.allow_municipality_change,
    )
    repaired_rows, changed_row_count = apply_location_corrections(rows, corrections)

    report = {
        "inputCsv": str(args.input_csv),
        "outputCsv": str(args.output_csv),
        "asOfDate": as_of,
        "rowCount": len(rows),
        "rareMaxCount": args.rare_max_count,
        "commonMinCount": args.common_min_count,
        "minSimilarity": args.min_similarity,
        "allowMunicipalityChange": args.allow_municipality_change,
        "provider": selected_provider,
        "model": selected_model,
        "suspiciousLocationCount": len(suspicious),
        "appliedCorrectionCount": len(corrections),
        "changedRowCount": changed_row_count,
        "suspiciousLocations": [
            {
                "id": item.id,
                "count": item.count,
                "suspiciousReasons": item.reasons,
                "address": item.key.as_dict(),
                "samples": item.samples,
                "candidates": item.candidates,
            }
            for item in suspicious
        ],
        "decisions": decisions,
        "appliedCorrections": {
            source_id: correction.as_dict()
            for source_id, correction in sorted(corrections.items())
        },
    }
    write_json(args.report_json, report)

    if not args.dry_run:
        write_csv_rows(args.output_csv, repaired_rows)
        print(f"[OK] wrote {args.output_csv} changedRows={changed_row_count}")
    else:
        print(f"[DRY] wrote report only: {args.report_json}")


if __name__ == "__main__":
    main()
