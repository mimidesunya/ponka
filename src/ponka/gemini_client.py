"""Gemini client construction helpers."""

from __future__ import annotations

import os
from typing import Any


ADC_AUTH_VALUES = {
    "adc",
    "application_default_credentials",
    "application-default-credentials",
    "vertex",
    "vertexai",
    "vertex_ai",
}


def resolve_http_timeout_ms(gemini_cfg: dict[str, Any]) -> int:
    timeout_ms = int(gemini_cfg.get("httpTimeoutMs", 300_000))
    return max(30_000, timeout_ms)


def should_use_vertex_ai(gemini_cfg: dict[str, Any]) -> bool:
    auth = str(gemini_cfg.get("auth", "")).strip().lower()
    if auth in ADC_AUTH_VALUES:
        return True
    for key in ("vertexAi", "vertexai", "useVertexAi", "useVertexAI"):
        if gemini_cfg.get(key) is True:
            return True
    return not gemini_cfg.get("apiKey")


def _optional_config_value(gemini_cfg: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = gemini_cfg.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def create_gemini_client(gemini_cfg: dict[str, Any]) -> Any:
    """Create a google-genai client from local config.

    API key auth is kept for existing local runs. When Vertex AI is selected,
    the SDK uses Application Default Credentials unless explicit credentials
    are supplied by the caller's environment.
    """
    if not isinstance(gemini_cfg, dict):
        raise RuntimeError("config.json に gemini 設定が必要です。")

    from google import genai

    http_options: dict[str, Any] = {"timeout": resolve_http_timeout_ms(gemini_cfg)}
    api_version = _optional_config_value(gemini_cfg, "apiVersion")
    if api_version:
        http_options["api_version"] = api_version

    if should_use_vertex_ai(gemini_cfg):
        project = _optional_config_value(
            gemini_cfg,
            "project",
            "cloudProject",
            "googleCloudProject",
        )
        location = _optional_config_value(
            gemini_cfg,
            "location",
            "cloudLocation",
            "googleCloudLocation",
        )
        client_kwargs: dict[str, Any] = {
            "vertexai": True,
            "http_options": http_options,
        }
        if project:
            client_kwargs["project"] = project
        if location:
            client_kwargs["location"] = location
        return genai.Client(**client_kwargs)

    api_key = _optional_config_value(gemini_cfg, "apiKey")
    if not api_key:
        raise RuntimeError(
            "config.json に gemini.apiKey を設定するか、gemini.auth を \"adc\" にしてください。"
        )
    return genai.Client(api_key=api_key, http_options=http_options)


def gemini_auth_label(gemini_cfg: dict[str, Any]) -> str:
    if should_use_vertex_ai(gemini_cfg):
        project = _optional_config_value(gemini_cfg, "project") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        location = _optional_config_value(gemini_cfg, "location") or os.environ.get("GOOGLE_CLOUD_LOCATION", "")
        suffix = " ".join(part for part in (project, location) if part)
        return f"vertex-ai-adc {suffix}".strip()
    return "api-key"
