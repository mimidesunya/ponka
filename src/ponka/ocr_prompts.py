"""Prompt text loader for OCR requests."""

from __future__ import annotations

from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().with_name("prompts")


def load_prompt(filename: str) -> str:
    return (PROMPT_DIR / filename).read_text(encoding="utf-8").strip()


OCR_SYSTEM_INSTRUCTION = load_prompt("ocr_system_standard.txt")
COMPACT_OCR_SYSTEM_INSTRUCTION = load_prompt("ocr_system_compact.txt")
OCR_PROMPT_TEMPLATE = load_prompt("ocr_standard.txt")
COMPACT_OCR_PROMPT_TEMPLATE = load_prompt("ocr_compact.txt")
SLIM_OCR_PROMPT_TEMPLATE = load_prompt("ocr_slim.txt")
