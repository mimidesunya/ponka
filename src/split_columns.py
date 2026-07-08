#!/usr/bin/env python3
"""電話帳画像のカラム分割ツール。

このスクリプトは画像分割だけを担当する。
OCR、カラムまたぎの連結、住所正規化は別プログラムに分け、
各段階で中間 JSON を保持できるようにしている。

カラム数推定の既定は電話帳単位である。1 つの電話帳ディレクトリでは
同じカラム数が続く前提で、サンプルページから推定した結果をその電話帳
全体に適用する。必要な場合だけ明示的にページ単位推定へ切り替える。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ponka.phonebook_config import config_section, load_phonebook_config


COLUMN_OVERLAP_PX = 40
SUPPORTED_COLUMN_FORMATS = {"png", "webp"}
DEFAULT_COLUMN_FORMAT = "webp"
DEFAULT_RESIZE_SCALE = 0.75
DEFAULT_WEBP_QUALITY = 90
DEFAULT_WEBP_LOSSLESS = False
FATAL_SPLIT_QUALITY_FLAGS = {"uneven_column_widths"}


@dataclass(frozen=True)
class SplitOptions:
    fixed_n_cols: int | None
    column_format: str
    resize_scale: float
    webp_quality: int
    webp_lossless: bool
    skip_failed_pages: bool
    workers: int
    exclude_pages: frozenset[str]
    exclude_page_ranges: tuple[tuple[str, str], ...]


def resolve_split_options(
    phonebook_config: dict[str, object],
    fixed_n_cols: int | None = None,
    column_format: str | None = None,
    resize_scale: float | None = None,
    webp_quality: int | None = None,
    webp_lossless: bool | None = None,
    skip_failed_pages: bool | None = None,
    workers: int | None = None,
) -> SplitOptions:
    split_config = config_section(phonebook_config, "split")

    resolved_fixed_n_cols = fixed_n_cols
    if resolved_fixed_n_cols is None:
        configured = split_config.get("fixedColumnCount")
        if configured not in (None, ""):
            resolved_fixed_n_cols = int(configured)
    if resolved_fixed_n_cols is not None and resolved_fixed_n_cols not in {2, 3, 4}:
        raise ValueError("split.fixedColumnCount は 2, 3, 4 のいずれかである必要があります")

    resolved_column_format = str(column_format or split_config.get("columnFormat") or DEFAULT_COLUMN_FORMAT)
    if resolved_column_format not in SUPPORTED_COLUMN_FORMATS:
        raise ValueError(
            "split.columnFormat は "
            + ", ".join(sorted(SUPPORTED_COLUMN_FORMATS))
            + " のいずれかである必要があります"
        )

    resolved_resize_scale = (
        float(resize_scale)
        if resize_scale is not None
        else float(split_config.get("resizeScale", DEFAULT_RESIZE_SCALE))
    )
    if resolved_resize_scale <= 0:
        raise ValueError("split.resizeScale は正の数である必要があります")

    resolved_webp_quality = (
        int(webp_quality)
        if webp_quality is not None
        else int(split_config.get("webpQuality", DEFAULT_WEBP_QUALITY))
    )
    resolved_webp_quality = max(1, min(100, resolved_webp_quality))

    resolved_webp_lossless = (
        bool(webp_lossless)
        if webp_lossless is not None
        else bool(split_config.get("webpLossless", DEFAULT_WEBP_LOSSLESS))
    )
    resolved_skip_failed_pages = (
        bool(skip_failed_pages)
        if skip_failed_pages is not None
        else bool(split_config.get("skipFailedPages", True))
    )
    resolved_workers = int(workers if workers is not None else split_config.get("workers", 1))
    resolved_workers = max(1, resolved_workers)

    exclude_pages = frozenset(normalize_page_selector(item) for item in read_string_list(split_config.get("excludePages", [])))
    exclude_page_ranges = tuple(read_page_ranges(split_config.get("excludePageRanges", [])))

    return SplitOptions(
        fixed_n_cols=resolved_fixed_n_cols,
        column_format=resolved_column_format,
        resize_scale=resolved_resize_scale,
        webp_quality=resolved_webp_quality,
        webp_lossless=resolved_webp_lossless,
        skip_failed_pages=resolved_skip_failed_pages,
        workers=resolved_workers,
        exclude_pages=exclude_pages,
        exclude_page_ranges=exclude_page_ranges,
    )


def read_string_list(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("split.excludePages は JSON array である必要があります")
    return [str(item) for item in value]


def normalize_page_selector(value: str) -> str:
    return Path(value.strip()).stem


def read_page_ranges(value: object) -> list[tuple[str, str]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("split.excludePageRanges は JSON array である必要があります")
    ranges: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, str):
            if "-" not in item:
                raise ValueError("split.excludePageRanges の文字列は '0001-0005' 形式である必要があります")
            start, end = item.split("-", 1)
        elif isinstance(item, dict):
            start = str(item.get("start", ""))
            end = str(item.get("end", ""))
        else:
            raise ValueError("split.excludePageRanges の要素は string または object である必要があります")
        start = normalize_page_selector(start)
        end = normalize_page_selector(end)
        if not start or not end:
            raise ValueError("split.excludePageRanges の start/end は空にできません")
        if start > end:
            start, end = end, start
        ranges.append((start, end))
    return ranges


def is_excluded_page(path: Path, exclude_pages: frozenset[str], exclude_page_ranges: tuple[tuple[str, str], ...]) -> bool:
    stem = path.stem
    if stem in exclude_pages:
        return True
    return any(start <= stem <= end for start, end in exclude_page_ranges)


def imread_unicode(path: Path) -> np.ndarray | None:
    """Windows の日本語パスを含む画像を安全に読み込む。"""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_unicode(path: Path, image: np.ndarray) -> None:
    """Windows の日本語パスを含む画像を安全に書き出す。"""
    suffix = path.suffix or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise RuntimeError(f"画像を書き出せません: {path}")
    encoded.tofile(path)


def write_column_image(
    path: Path,
    image: np.ndarray,
    resize_scale: float = 1.0,
    webp_quality: int = 80,
    webp_lossless: bool = False,
) -> None:
    """Write a column image, optionally resized for OCR cost experiments."""
    output = image
    if resize_scale != 1.0:
        if resize_scale <= 0:
            raise ValueError("resize_scale must be positive")
        height, width = image.shape[:2]
        resized_width = max(1, int(round(width * resize_scale)))
        resized_height = max(1, int(round(height * resize_scale)))
        output = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)

    suffix = path.suffix.lower()
    if suffix == ".webp":
        if webp_lossless:
            rgb = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb)
            path.parent.mkdir(parents=True, exist_ok=True)
            pil_image.save(path, format="WEBP", lossless=True)
            return
        ok, encoded = cv2.imencode(".webp", output, [cv2.IMWRITE_WEBP_QUALITY, int(webp_quality)])
        if not ok:
            raise RuntimeError(f"画像を書き出せません: {path}")
        encoded.tofile(path)
        return

    imwrite_unicode(path, output)


def iter_phonebook_dirs(data_root: Path) -> list[Path]:
    """直下に PNG ページを持つ電話帳ディレクトリを返す。"""
    return sorted(
        path
        for path in data_root.iterdir()
        if path.is_dir() and any(child.is_file() and child.suffix.lower() == ".png" for child in path.iterdir())
    )


def iter_png_files(input_dir: Path) -> list[Path]:
    """ファイル名順を読順として PNG ページ一覧を返す。"""
    return sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".png"
    )


def clear_output_dir(output_root: Path) -> None:
    """分割出力ルートを一度消してから再作成する。"""
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def crop_border_rect(gray: np.ndarray, threshold: int = 30, margin: int = 5) -> tuple[int, int, int, int]:
    """本文領域を囲む矩形を検出し、暗いスキャン外枠を落とす。

    カラム推定は余白率に強く依存するため、周辺の影や黒枠を先に除去して
    判定を安定させる。
    """
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return 0, gray.shape[0], 0, gray.shape[1]
    x, y, w, h = cv2.boundingRect(coords)
    h_img, w_img = gray.shape
    return (
        max(0, y - margin),
        min(h_img, y + h + margin),
        max(0, x - margin),
        min(w_img, x + w + margin),
    )


def preprocess_image(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    """カラム検出用に画像を前処理する。

    返り値は、切り出し後のカラー画像、境界検出に使う二値画像、
    元画像座標系での切り出し矩形である。
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    y1, y2, x1, x2 = crop_border_rect(gray)
    cropped_gray = gray[y1:y2, x1:x2]
    cropped_color = image[y1:y2, x1:x2]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(cropped_gray)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cropped_color, binary, (y1, y2, x1, x2)


def smooth_white_profile(binary: np.ndarray, smooth_px: int = 50) -> np.ndarray:
    """ページ幅方向の白画素率プロファイルを平滑化して求める。

    これは本文領域の左右境界推定や、明確な縦罫が弱いときの区切り候補に使う。
    """
    h, w = binary.shape
    strip = binary[int(h * 0.1):int(h * 0.9), :]
    white_ratio = np.sum(strip == 255, axis=0).astype(float) / strip.shape[0]
    pad = smooth_px // 2
    padded = np.pad(white_ratio, pad, mode="edge")
    smoothed = np.convolve(padded, np.ones(smooth_px) / smooth_px, mode="valid")
    return smoothed[:w]


def compute_ink_coverage_loss(
    binary: np.ndarray,
    spans: list[tuple[int, int]],
    left_bound: int,
    right_bound: int,
    top_ratio: float = 0.10,
    bottom_ratio: float = 0.90,
) -> float:
    """候補カラム範囲からこぼれ落ちる黒画素の割合を返す。

    2 カラム頁を誤って 3 カラムとみなすケースでは、端の本文を少し削って
    見かけ上の等幅を作ることがある。この取りこぼし量を罰則に使うと、
    2 カラム判定が安定しやすい。
    """
    y0 = int(binary.shape[0] * top_ratio)
    y1 = int(binary.shape[0] * bottom_ratio)
    if right_bound <= left_bound or y1 <= y0:
        return 0.0

    strip = binary[y0:y1, left_bound:right_bound]
    if strip.size == 0:
        return 0.0

    ink_mask = strip == 0
    total_ink = int(np.sum(ink_mask))
    if total_ink == 0:
        return 0.0

    covered = np.zeros(strip.shape[1], dtype=bool)
    for x0, x1 in spans:
        a = max(left_bound, x0) - left_bound
        b = min(right_bound, x1) - left_bound
        if b > a:
            covered[a:b] = True

    kept_ink = int(np.sum(ink_mask[:, covered]))
    return float(max(0.0, 1.0 - kept_ink / total_ink))


def compute_split_quality(binary: np.ndarray, spans: list[tuple[int, int]]) -> dict[str, object]:
    """採用したカラム分割の簡易 QC 指標を返す。

    後続 OCR の前に、空列、極端な幅のばらつき、境界で本文を切った疑いを
    JSON 上で見つけられるようにするための診断情報である。
    """
    h, w = binary.shape
    y0 = int(h * 0.05)
    y1 = int(h * 0.95)
    strip = binary[y0:y1, :]
    page_ink_ratio = float(np.mean(strip == 0)) if strip.size else 0.0

    widths = np.array([x1 - x0 for x0, x1 in spans], dtype=float)
    mean_width = float(widths.mean()) if widths.size else 0.0
    width_cv = float(widths.std() / mean_width) if mean_width > 0 else 0.0

    column_metrics: list[dict[str, object]] = []
    ink_ratios: list[float] = []
    edge_ink_ratios: list[float] = []
    edge_text_ink_ratios: list[float] = []
    for index, (x0, x1) in enumerate(spans, start=1):
        column = strip[:, x0:x1]
        width = max(0, x1 - x0)
        ink_ratio = float(np.mean(column == 0)) if column.size else 0.0
        ink_ratios.append(ink_ratio)

        edge_width = min(16, max(1, width // 25)) if width else 1
        left_edge = column[:, :edge_width] if column.size else column
        right_edge = column[:, -edge_width:] if column.size else column
        left_edge_ink = float(np.mean(left_edge == 0)) if left_edge.size else 0.0
        right_edge_ink = float(np.mean(right_edge == 0)) if right_edge.size else 0.0
        left_edge_text_ink = compute_edge_text_ink_ratio(left_edge)
        right_edge_text_ink = compute_edge_text_ink_ratio(right_edge)
        edge_ink_ratios.extend([left_edge_ink, right_edge_ink])
        edge_text_ink_ratios.extend([left_edge_text_ink, right_edge_text_ink])

        column_metrics.append(
            {
                "column": index,
                "x1": int(x0),
                "x2": int(x1),
                "width": int(width),
                "relativeWidth": round(float(width / mean_width), 4) if mean_width > 0 else 0.0,
                "inkRatio": round(ink_ratio, 5),
                "leftEdgeInkRatio": round(left_edge_ink, 5),
                "rightEdgeInkRatio": round(right_edge_ink, 5),
                "leftEdgeTextInkRatio": round(left_edge_text_ink, 5),
                "rightEdgeTextInkRatio": round(right_edge_text_ink, 5),
            }
        )

    median_ink = float(np.median(ink_ratios)) if ink_ratios else 0.0
    max_edge_ink = max(edge_ink_ratios) if edge_ink_ratios else 0.0
    max_edge_text_ink = max(edge_text_ink_ratios) if edge_text_ink_ratios else 0.0
    flags: list[str] = []
    if width_cv > 0.18:
        flags.append("uneven_column_widths")
    if median_ink > 0 and any(ink_ratio < median_ink * 0.35 for ink_ratio in ink_ratios):
        flags.append("possible_blank_or_underfilled_column")
    if page_ink_ratio > 0 and max_edge_text_ink > max(0.30, page_ink_ratio * 1.85):
        flags.append("possible_text_cut_at_column_edge")

    return {
        "pageInkRatio": round(page_ink_ratio, 5),
        "widthCoefficientOfVariation": round(width_cv, 5),
        "medianColumnInkRatio": round(median_ink, 5),
        "maxEdgeInkRatio": round(max_edge_ink, 5),
        "maxEdgeTextInkRatio": round(max_edge_text_ink, 5),
        "flags": flags,
        "columns": column_metrics,
    }


def validate_split_quality_for_output(split_quality: dict[str, object]) -> None:
    flags = {
        str(flag)
        for flag in split_quality.get("flags", [])
        if str(flag) in FATAL_SPLIT_QUALITY_FLAGS
    }
    if flags:
        raise ValueError(f"カラム幅が不均一なため電話帳本文ページではない可能性があります: {', '.join(sorted(flags))}")


def compute_edge_text_ink_ratio(edge: np.ndarray) -> float:
    """端帯の黒画素率から、長い縦罫線らしい列を除いて返す。"""
    if edge.size == 0:
        return 0.0
    ink = edge == 0
    column_ink = np.mean(ink, axis=0)
    non_rule_columns = column_ink < 0.35
    if not np.any(non_rule_columns):
        return 0.0
    return float(np.mean(ink[:, non_rule_columns]))


def count_projection_groups(mask: np.ndarray, min_width: int = 1) -> int:
    """True が連続する投影ピークのグループ数を数える。"""
    count = 0
    start: int | None = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start >= min_width:
                count += 1
            start = None
    if start is not None and len(mask) - start >= min_width:
        count += 1
    return count


def vertical_rule_projection(inv: np.ndarray, ratios: tuple[float, ...]) -> np.ndarray:
    """複数の長さの縦罫線を拾う投影を返す。

    紙面によってはカラム境界線が広告や本文ブロックで途切れるため、
    長いカーネルだけでは境界を拾えない。短めのカーネルも併用し、
    日本語本文の短い縦画より十分長い線分をセパレータ候補にする。
    """
    h = inv.shape[0]
    projection = np.zeros(inv.shape[1], dtype=float)
    for ratio in ratios:
        kernel_height = max(40, int(h * ratio))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_height))
        opened = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel)
        projection = np.maximum(projection, np.sum(opened, axis=0).astype(float))
    return projection


def detect_column_boundaries(
    binary: np.ndarray,
    n_cols: int,
    overlap: int = COLUMN_OVERLAP_PX,
) -> tuple[list[tuple[int, int]], dict[str, object]]:
    """固定した候補カラム数に対して各カラム範囲を求める。

    内部境界は縦罫線だけを根拠にする。電話帳本文ではカラム境界に縦罫線が
    あるため、これが検出できないページは分割不能としてスキップする。

    ここで返す指標は 2、3、4 カラム候補の採点にも再利用する。
    """
    h, w = binary.shape
    inv = cv2.bitwise_not(binary)
    edge = int(w * 0.03)
    smooth_white = smooth_white_profile(binary)

    # ほぼ空白の左余白から本文へ移る最初の変化点を左境界候補にする。
    left_bound = int(w * 0.05)
    for x in range(w):
        if smooth_white[x] < 0.88:
            left_bound = max(0, x - 25)
            break

    # 右境界は構造的な手掛かりを優先し、索引帯や余白を本文領域から外す。
    right_bound = None
    for h_ratio, _cov_ratio in ((0.45, 0.25), (0.30, 0.15)):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * h_ratio)))
        proj = np.sum(cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel), axis=0).astype(float)
        proj[:edge] = 0
        proj[w - edge:] = 0
        search_start = int(w * 0.60)
        peaks = np.where(proj[search_start:] > h * 0.10 * 255)[0] + search_start
        for candidate in sorted(peaks, reverse=True):
            check_end = min(w, candidate + 200)
            if check_end > candidate + 50:
                right_white = float(np.mean(smooth_white[candidate:check_end]))
                if right_white >= 0.90 and candidate - left_bound >= w * 0.40:
                    right_bound = int(candidate)
                    break
        if right_bound is not None:
            break

    if right_bound is None:
        skip_right = int(w * 0.05)
        for x in range(w - 1 - skip_right, -1, -1):
            if smooth_white[x] < 0.88:
                right_bound = min(w - skip_right, x + 25)
                break

    if right_bound is None or right_bound - left_bound < w * 0.40:
        right_bound = int(w * 0.94)

    # 内部の区切りはページ境界より弱いことが多いので、等幅想定の中心付近を
    # 探索する。ただし縦罫だけを採用し、空白帯は境界とみなさない。
    v_proj = vertical_rule_projection(inv, ratios=(0.25, 0.12, 0.06))
    v_proj[:left_bound + 5] = 0
    v_proj[right_bound - 5:] = 0
    internal_margin = max(40, int(w * 0.015))
    separator_mask = np.zeros_like(v_proj, dtype=bool)
    separator_mask[left_bound + internal_margin:right_bound - internal_margin] = (
        v_proj[left_bound + internal_margin:right_bound - internal_margin] > h * 0.035 * 255
    )
    observed_separator_count = count_projection_groups(separator_mask)
    if observed_separator_count < n_cols - 1:
        raise RuntimeError(
            f"縦罫線数が不足しています: detected={observed_separator_count}, required={n_cols - 1}"
        )

    content_w = right_bound - left_bound
    if content_w <= 0:
        raise RuntimeError("本文領域の検出に失敗しました。")

    segment_w = content_w // n_cols
    search_half = max(40, segment_w * 2 // 5)

    split_xs = [left_bound]
    separator_scores: list[float] = []
    vertical_rule_threshold = h * 0.035 * 255
    for i in range(1, n_cols):
        center = left_bound + i * segment_w
        lo = max(left_bound + 10, center - search_half)
        hi = min(right_bound - 10, center + search_half)

        zone_v = v_proj[lo:hi]
        vertical_strength = float(zone_v.max() / (255.0 * h)) if len(zone_v) > 0 else 0.0
        if len(zone_v) > 0 and zone_v.max() > vertical_rule_threshold:
            local_peak = int(np.argmax(zone_v) + lo)
        else:
            raise RuntimeError(
                f"縦罫線によるカラム境界を検出できません: boundary={i}/{n_cols - 1}"
            )

        separator_scores.append(vertical_strength)
        split_xs.append(local_peak)
    split_xs.append(right_bound)

    spans: list[tuple[int, int]] = []
    widths: list[int] = []
    for i in range(n_cols):
        x0 = 0 if i == 0 else max(0, split_xs[i] - overlap)
        x1 = w if i == n_cols - 1 else min(w, split_xs[i + 1] + overlap)
        if x1 <= x0:
            raise RuntimeError("カラム幅が不正です。")
        spans.append((x0, x1))
        widths.append(x1 - x0)

    ink_loss = compute_ink_coverage_loss(binary, spans, left_bound=left_bound, right_bound=right_bound)

    return spans, {
        "left_bound": int(left_bound),
        "right_bound": int(right_bound),
        "widths": widths,
        "separator_scores": separator_scores,
        "inkCoverageLoss": float(ink_loss),
        "observedInternalSeparators": int(observed_separator_count),
    }


def score_layout(metrics: dict[str, object], page_width: int, n_cols: int) -> float:
    """2、3、4 カラム候補のもっともらしさを採点する。

    スコアは高いほど良い。区切りの強さと幅の安定性を評価し、幅のばらつき
    が大きい候補には罰則を与える。

    さらに、ページ端の本文黒画素を取りこぼす候補にも罰則を与える。これは
    索引帯のある 2 カラム頁を誤って 3 カラムとみなす誤判定を抑えるための
    重要な補正である。
    """
    widths = np.array(metrics["widths"], dtype=float)
    mean_width = float(widths.mean())
    if mean_width <= 0:
        return float("-inf")

    cv = float(widths.std() / mean_width)
    min_ratio = float(widths.min() / mean_width)
    max_ratio = float(widths.max() / mean_width)
    separator_scores = metrics["separator_scores"]
    separator_score = float(np.mean(separator_scores)) if separator_scores else 0.0
    content_ratio = float((metrics["right_bound"] - metrics["left_bound"]) / page_width)
    ink_loss = float(metrics.get("inkCoverageLoss", 0.0))
    observed_internal_separators = int(metrics.get("observedInternalSeparators", 0))

    score = 0.0
    score += separator_score * 3.0
    score += content_ratio
    score -= cv * 2.5
    score -= max(0.0, 0.55 - min_ratio) * 3.0
    score -= max(0.0, max_ratio - 1.6) * 2.0

    # 微小な切り落としノイズは無視しつつ、実際の端本文を落とす候補には
    # 罰則を与える。2 カラム頁の 3 カラム誤判定ではこの値が大きくなりやすい。
    score -= max(0.0, ink_loss - 0.03) * 4.0
    score -= max(0, observed_internal_separators + 1 - n_cols) * 0.30

    if n_cols == 2:
        score -= 0.05
    elif n_cols == 4:
        score -= 0.02

    return score


def infer_n_cols_for_page(
    binary: np.ndarray,
    candidates: tuple[int, ...] = (2, 3, 4),
) -> tuple[int, list[tuple[int, int]], dict[str, object], dict[str, object]]:
    """単一ページに対して最適なカラム数を推定する。"""
    candidate_scores: dict[int, float] = {}
    candidate_details: dict[int, dict[str, object]] = {}

    for candidate in candidates:
        spans, metrics = detect_column_boundaries(binary, n_cols=candidate)
        score = score_layout(metrics, page_width=binary.shape[1], n_cols=candidate)
        candidate_scores[candidate] = float(score)
        candidate_details[candidate] = {
            "spans": spans,
            "metrics": metrics,
        }

    best_n_cols = max(candidate_scores, key=candidate_scores.get)
    best_detail = candidate_details[best_n_cols]
    page_meta = {
        "inferredColumnCount": int(best_n_cols),
        "candidateScores": {str(key): round(value, 4) for key, value in candidate_scores.items()},
        "candidateInkCoverageLoss": {
            str(key): round(float(candidate_details[key]["metrics"].get("inkCoverageLoss", 0.0)), 4)
            for key in candidates
        },
    }
    return best_n_cols, best_detail["spans"], best_detail["metrics"], page_meta


def draw_debug(cropped_image: np.ndarray, spans: list[tuple[int, int]]) -> np.ndarray:
    """最終的に採用したカラム範囲を重ね描きしたデバッグ画像を作る。"""
    debug_image = cropped_image.copy()
    h = debug_image.shape[0]
    for idx, (x0, x1) in enumerate(spans, start=1):
        cv2.rectangle(debug_image, (x0, 0), (x1, h - 1), (0, 255, 0), 2)
        cv2.putText(
            debug_image,
            f"C{idx}",
            (x0 + 8, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 180, 0),
            2,
            cv2.LINE_AA,
        )
    return debug_image


def split_phonebook_page(
    input_path: Path,
    output_dir: Path,
    fixed_n_cols: int | None = None,
    debug: bool = False,
    column_format: str = DEFAULT_COLUMN_FORMAT,
    resize_scale: float = DEFAULT_RESIZE_SCALE,
    webp_quality: int = DEFAULT_WEBP_QUALITY,
    webp_lossless: bool = DEFAULT_WEBP_LOSSLESS,
) -> dict[str, object]:
    """1 ページをカラム画像へ分割し、ページ単位メタ情報も保存する。

    後段の OCR や連結処理で元の切り出し矩形やカラム位置が必要になるため、
    ページメタ情報はやや冗長に保持する。
    """
    image = imread_unicode(input_path)
    if image is None:
        raise FileNotFoundError(f"画像を開けません: {input_path}")

    cropped_color, binary, crop_rect = preprocess_image(image)

    if fixed_n_cols is None:
        page_n_cols, spans, _metrics, inference_detail = infer_n_cols_for_page(binary)
        inference_meta = {
            "mode": "page",
            **inference_detail,
        }
    else:
        page_n_cols = fixed_n_cols
        spans, _metrics = detect_column_boundaries(binary, n_cols=page_n_cols)
        inference_meta = {
            "mode": "fixed",
            "inferredColumnCount": int(page_n_cols),
        }

    split_quality = compute_split_quality(binary, spans)
    validate_split_quality_for_output(split_quality)
    saved_files: list[Path] = []
    boxes: list[dict[str, int]] = []
    extension = f".{column_format}"
    for idx, (x0, x1) in enumerate(spans, start=1):
        column_image = cropped_color[:, x0:x1].copy()
        out_path = output_dir / f"{input_path.stem}-{idx:02d}{extension}"
        write_column_image(
            out_path,
            column_image,
            resize_scale=resize_scale,
            webp_quality=webp_quality,
            webp_lossless=webp_lossless,
        )
        saved_files.append(out_path)
        boxes.append({"x1": int(x0), "y1": 0, "x2": int(x1), "y2": int(cropped_color.shape[0])})

    page_meta = {
        "input": str(input_path),
        "cropRect": {
            "y1": int(crop_rect[0]),
            "y2": int(crop_rect[1]),
            "x1": int(crop_rect[2]),
            "x2": int(crop_rect[3]),
        },
        "columnCount": int(page_n_cols),
        "columns": boxes,
        "inference": inference_meta,
        "quality": split_quality,
    }
    with open(output_dir / f"{input_path.stem}.columns.json", "w", encoding="utf-8") as handle:
        json.dump(page_meta, handle, ensure_ascii=False, indent=2)

    if debug:
        imwrite_unicode(output_dir / f"{input_path.stem}-debug_overlay.png", draw_debug(cropped_color, spans))

    return {
        "page": input_path.name,
        "columnCount": int(page_n_cols),
        "savedFiles": [str(path) for path in saved_files],
        "inference": inference_meta,
        "quality": split_quality,
    }


def split_phonebook_page_safe(
    input_path: Path,
    output_dir: Path,
    fixed_n_cols: int | None = None,
    debug: bool = False,
    column_format: str = DEFAULT_COLUMN_FORMAT,
    resize_scale: float = DEFAULT_RESIZE_SCALE,
    webp_quality: int = DEFAULT_WEBP_QUALITY,
    webp_lossless: bool = DEFAULT_WEBP_LOSSLESS,
) -> tuple[Path, dict[str, object] | None, Exception | None]:
    """並列実行用ラッパー。失敗時もページパスを失わないようにする。"""
    try:
        page_result = split_phonebook_page(
            input_path=input_path,
            output_dir=output_dir,
            fixed_n_cols=fixed_n_cols,
            debug=debug,
            column_format=column_format,
            resize_scale=resize_scale,
            webp_quality=webp_quality,
            webp_lossless=webp_lossless,
        )
        return input_path, page_result, None
    except Exception as exc:
        return input_path, None, exc


def load_existing_page_result(output_dir: Path, input_path: Path) -> dict[str, object] | None:
    metadata_path = output_dir / f"{input_path.stem}.columns.json"
    if not metadata_path.exists():
        return None
    with open(metadata_path, "r", encoding="utf-8") as handle:
        page_meta = json.load(handle)
    if not isinstance(page_meta, dict):
        return None

    columns = page_meta.get("columns", [])
    if not isinstance(columns, list) or not columns:
        return None

    saved_files = sorted(
        path
        for path in output_dir.glob(f"{input_path.stem}-*.*")
        if path.suffix.lower().lstrip(".") in SUPPORTED_COLUMN_FORMATS
    )
    if len(saved_files) < len(columns):
        return None

    return {
        "page": input_path.name,
        "columnCount": int(page_meta.get("columnCount", len(columns))),
        "savedFiles": [str(path) for path in saved_files],
        "inference": page_meta.get("inference", {}),
        "quality": page_meta.get("quality", {}),
    }


def build_split_quality_summary(
    page_results: list[dict[str, object]],
    skipped_pages: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """電話帳単位で分割 QC の集計を作る。"""
    skipped_pages = skipped_pages or []
    flag_counts: Counter[str] = Counter()
    pages: list[dict[str, object]] = []
    for result in sorted(page_results, key=lambda item: str(item["page"])):
        quality = result.get("quality", {})
        if not isinstance(quality, dict):
            quality = {}
        flags = [str(flag) for flag in quality.get("flags", [])]
        flag_counts.update(flags)
        pages.append(
            {
                "page": result["page"],
                "columnCount": result["columnCount"],
                "flags": flags,
                "pageInkRatio": quality.get("pageInkRatio", 0.0),
                "widthCoefficientOfVariation": quality.get("widthCoefficientOfVariation", 0.0),
                "medianColumnInkRatio": quality.get("medianColumnInkRatio", 0.0),
                "maxEdgeInkRatio": quality.get("maxEdgeInkRatio", 0.0),
                "maxEdgeTextInkRatio": quality.get("maxEdgeTextInkRatio", 0.0),
            }
        )

    suspicious_pages = [page for page in pages if page["flags"]]
    return {
        "pageCount": len(pages),
        "skippedPageCount": len(skipped_pages),
        "skippedPages": sorted(skipped_pages, key=lambda item: item["page"]),
        "suspiciousPageCount": len(suspicious_pages),
        "flagCounts": {flag: int(count) for flag, count in sorted(flag_counts.items())},
        "suspiciousPages": suspicious_pages,
        "pages": pages,
    }


def process_phonebook_dir(
    phonebook_dir: Path,
    output_dir: Path,
    debug: bool = False,
    fixed_n_cols: int | None = None,
    column_format: str = DEFAULT_COLUMN_FORMAT,
    resize_scale: float = DEFAULT_RESIZE_SCALE,
    webp_quality: int = DEFAULT_WEBP_QUALITY,
    webp_lossless: bool = DEFAULT_WEBP_LOSSLESS,
    skip_failed_pages: bool = True,
    resume: bool = False,
    workers: int = 1,
    exclude_pages: frozenset[str] = frozenset(),
    exclude_page_ranges: tuple[tuple[str, str], ...] = (),
) -> tuple[int, int, list[tuple[Path, Exception]]]:
    """1 つの電話帳ディレクトリを最後まで処理する。"""
    png_files = iter_png_files(phonebook_dir)
    if not png_files:
        raise FileNotFoundError(f"PNG が見つかりません: {phonebook_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = output_dir / "column_count.json"

    success_count = 0
    errors: list[tuple[Path, Exception]] = []
    skipped_pages: list[dict[str, str]] = []
    page_results: list[dict[str, object]] = []

    pending_paths: list[Path] = []
    for input_path in png_files:
        if is_excluded_page(input_path, exclude_pages, exclude_page_ranges):
            skipped_pages.append({"page": input_path.name, "reason": "configured_exclude"})
            print(f"[SKIP] {input_path.name}: configured_exclude")
            continue
        if resume:
            existing_result = load_existing_page_result(output_dir, input_path)
            if existing_result is not None:
                success_count += 1
                page_results.append(existing_result)
                print(f"[EXISTS] {input_path.name} -> {output_dir} ({existing_result['columnCount']} cols)")
                continue
        pending_paths.append(input_path)

    def handle_page_result(input_path: Path, page_result: dict[str, object] | None, exc: Exception | None) -> None:
        nonlocal success_count
        if exc is None and page_result is not None:
            success_count += 1
            page_results.append(page_result)
            print(f"[OK] {input_path.name} -> {output_dir} ({page_result['columnCount']} cols)")
        elif skip_failed_pages:
            reason = str(exc or RuntimeError("不明なエラー"))
            skipped_pages.append({"page": input_path.name, "reason": reason})
            print(f"[SKIP] {input_path.name}: {reason}")
        else:
            errors.append((input_path, exc or RuntimeError("不明なエラー")))
            print(f"[ERROR] {input_path.name}: {exc}")

    if workers <= 1 or len(pending_paths) <= 1:
        for input_path in pending_paths:
            result_path, page_result, exc = split_phonebook_page_safe(
                input_path,
                output_dir,
                fixed_n_cols,
                debug,
                column_format,
                resize_scale,
                webp_quality,
                webp_lossless,
            )
            handle_page_result(result_path, page_result, exc)
    else:
        effective_workers = min(workers, len(pending_paths), os.cpu_count() or workers)
        print(f"[INFO] split workers={effective_workers}")
        with ProcessPoolExecutor(max_workers=effective_workers) as executor:
            futures = [
                executor.submit(
                    split_phonebook_page_safe,
                    input_path,
                    output_dir,
                    fixed_n_cols,
                    debug,
                    column_format,
                    resize_scale,
                    webp_quality,
                    webp_lossless,
                )
                for input_path in pending_paths
            ]
            for future in as_completed(futures):
                result_path, page_result, exc = future.result()
                handle_page_result(result_path, page_result, exc)

    histogram = Counter(result["columnCount"] for result in page_results)
    summary = {
        "layoutScope": "page",
        "columnImageFormat": column_format,
        "columnImageResizeScale": resize_scale,
        "webpQuality": webp_quality if column_format == "webp" else None,
        "webpLossless": webp_lossless if column_format == "webp" else None,
        "pageCount": len(page_results),
        "columnCountHistogram": {str(key): histogram.get(key, 0) for key in sorted(histogram)},
        "pages": sorted(page_results, key=lambda item: item["page"]),
    }
    if histogram:
        summary["mostCommonColumnCount"] = int(histogram.most_common(1)[0][0])
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    quality_summary = build_split_quality_summary(page_results, skipped_pages)
    with open(output_dir / "split_quality.json", "w", encoding="utf-8") as handle:
        json.dump(quality_summary, handle, ensure_ascii=False, indent=2)

    return success_count, len(skipped_pages), errors


def process_all_phonebooks(
    data_root: Path,
    output_root: Path,
    debug: bool = False,
    book: str = "",
    fixed_n_cols: int | None = None,
    column_format: str | None = None,
    resize_scale: float | None = None,
    webp_quality: int | None = None,
    webp_lossless: bool | None = None,
    skip_failed_pages: bool | None = None,
    resume: bool = False,
    workers: int | None = None,
) -> tuple[int, int, int]:
    """`data` 配下で見つかった電話帳ディレクトリをすべて処理する。"""
    phonebook_dirs = [data_root / book] if book else iter_phonebook_dirs(data_root)
    if not phonebook_dirs:
        raise FileNotFoundError(f"PNG を含む電話帳ディレクトリが見つかりません: {data_root}")

    total_success = 0
    total_skipped = 0
    total_failed = 0
    for phonebook_dir in phonebook_dirs:
        phonebook_output_dir = output_root if book else output_root / phonebook_dir.name
        phonebook_config = load_phonebook_config(phonebook_dir)
        split_options = resolve_split_options(
            phonebook_config,
            fixed_n_cols=fixed_n_cols,
            column_format=column_format,
            resize_scale=resize_scale,
            webp_quality=webp_quality,
            webp_lossless=webp_lossless,
            skip_failed_pages=skip_failed_pages,
            workers=workers,
        )
        print(f"\n=== {phonebook_dir.name} ===")
        success_count, skipped_count, errors = process_phonebook_dir(
            phonebook_dir=phonebook_dir,
            output_dir=phonebook_output_dir,
            debug=debug,
            fixed_n_cols=split_options.fixed_n_cols,
            column_format=split_options.column_format,
            resize_scale=split_options.resize_scale,
            webp_quality=split_options.webp_quality,
            webp_lossless=split_options.webp_lossless,
            skip_failed_pages=split_options.skip_failed_pages,
            resume=resume,
            workers=split_options.workers,
            exclude_pages=split_options.exclude_pages,
            exclude_page_ranges=split_options.exclude_page_ranges,
        )
        total_success += success_count
        total_skipped += skipped_count
        total_failed += len(errors)
        print(f"Saved {success_count} pages into: {phonebook_output_dir}")
        if skipped_count:
            print(f"Skipped: {skipped_count}")
        if errors:
            print(f"Failed: {len(errors)}")

    return total_success, total_skipped, total_failed


def main() -> None:
    """分割専用バッチ実行の CLI エントリポイント。"""
    parser = argparse.ArgumentParser(
        description="output/split をクリアして data 配下の電話帳 PNG をカラム分割します。"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="電話帳ディレクトリを含む入力ルート",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output") / "split",
        help="分割画像の出力ルート",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="検出結果のオーバーレイ画像を保存する",
    )
    parser.add_argument(
        "--book",
        type=str,
        default="",
        help="特定の電話帳ディレクトリだけ分割する場合の名前",
    )
    parser.add_argument(
        "--columns",
        type=int,
        choices=(2, 3, 4),
        default=0,
        help="カラム数が既知の場合に固定する。例: 昭和38年大阪市50音別は 4",
    )
    parser.add_argument(
        "--column-format",
        choices=sorted(SUPPORTED_COLUMN_FORMATS),
        default=None,
        help="分割カラム画像の保存形式。未指定なら phonebook.config.json の split.columnFormat または既定値",
    )
    parser.add_argument(
        "--resize-scale",
        type=float,
        default=None,
        help="分割カラム画像の出力倍率。例: 0.5 で 50%% 縮小。未指定なら電話帳設定または既定値",
    )
    parser.add_argument(
        "--webp-quality",
        type=int,
        default=None,
        help="WebP 出力時の品質 1-100。未指定なら電話帳設定または既定値",
    )
    parser.add_argument(
        "--webp-lossless",
        action="store_true",
        default=None,
        help="WebP 出力をロスレスにする。この場合 --webp-quality は記録のみ",
    )
    parser.add_argument(
        "--fail-on-split-error",
        action="store_true",
        help="カラム分割できないページをスキップせず、エラーとして集計する",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="ページ単位の並列分割プロセス数。未指定なら phonebook.config.json の split.workers または 1",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="既存の <page>.columns.json とカラム画像があるページは再分割せずに続行する",
    )
    args = parser.parse_args()

    if args.resume:
        args.output_root.mkdir(parents=True, exist_ok=True)
    else:
        clear_output_dir(args.output_root)
    total_success, total_skipped, total_failed = process_all_phonebooks(
        data_root=args.data_root,
        output_root=args.output_root,
        debug=args.debug,
        book=args.book,
        fixed_n_cols=args.columns or None,
        column_format=args.column_format,
        resize_scale=args.resize_scale,
        webp_quality=args.webp_quality,
        webp_lossless=args.webp_lossless,
        skip_failed_pages=False if args.fail_on_split_error else None,
        resume=args.resume,
        workers=args.workers,
    )
    print(f"\nCompleted. success={total_success}, skipped={total_skipped}, failed={total_failed}")


if __name__ == "__main__":
    main()
