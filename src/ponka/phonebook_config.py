"""Helpers for per-phonebook target configuration files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PHONEBOOK_CONFIG_FILENAME = "phonebook.config.json"


def load_phonebook_config(phonebook_dir: Path) -> dict[str, Any]:
    path = phonebook_dir / PHONEBOOK_CONFIG_FILENAME
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"電話帳設定ファイルのルートは JSON object である必要があります: {path}")
    return payload


def config_section(config: dict[str, Any], section: str) -> dict[str, Any]:
    value = config.get(section, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"電話帳設定の {section} は JSON object である必要があります")
    return value
