"""OpenRouter model discovery and capability-aware selection helpers."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests

from .model_catalog import (
    OPENROUTER_RECOMMENDED_MODELS,
    ModelOption,
    ProviderModeOptions,
)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_OPENROUTER_REFERER = "https://github.com/TauricResearch/TradingAgents"
DEFAULT_OPENROUTER_TITLE = "TradingAgents"
_CACHE_TTL_SECONDS = 15 * 60
_CACHE_LOCK = threading.Lock()
_CACHED_MODELS: list[dict[str, Any]] | None = None
_CACHE_EXPIRES_AT = 0.0


class OpenRouterCatalogError(RuntimeError):
    """Raised when the OpenRouter model catalog cannot be loaded."""


def get_openrouter_attribution_headers() -> dict[str, str]:
    """Return OpenRouter's optional application attribution headers."""
    headers: dict[str, str] = {}
    referer = os.environ.get(
        "OPENROUTER_HTTP_REFERER", DEFAULT_OPENROUTER_REFERER
    ).strip()
    title = os.environ.get("OPENROUTER_APP_TITLE", DEFAULT_OPENROUTER_TITLE).strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if title:
        headers["X-OpenRouter-Title"] = title
    return headers


def fetch_openrouter_models(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch and cache OpenRouter's public model metadata."""
    global _CACHED_MODELS, _CACHE_EXPIRES_AT

    now = time.monotonic()
    with _CACHE_LOCK:
        if (
            not force_refresh
            and _CACHED_MODELS is not None
            and now < _CACHE_EXPIRES_AT
        ):
            return list(_CACHED_MODELS)
        stale_models = list(_CACHED_MODELS) if _CACHED_MODELS is not None else None

    headers = get_openrouter_attribution_headers()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(
            OPENROUTER_MODELS_URL,
            headers=headers,
            params={"sort": "most-popular"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json().get("data")
        if not isinstance(data, list):
            raise ValueError("response did not contain a model list")
        models = [model for model in data if isinstance(model, dict) and model.get("id")]
    except (requests.RequestException, ValueError) as exc:
        if stale_models is not None:
            return stale_models
        raise OpenRouterCatalogError(str(exc)) from exc

    with _CACHE_LOCK:
        _CACHED_MODELS = models
        _CACHE_EXPIRES_AT = time.monotonic() + _CACHE_TTL_SECONDS
    return list(models)


def _supports_mode(model: dict[str, Any], mode: str) -> bool:
    parameters = set(model.get("supported_parameters") or [])
    architecture = model.get("architecture") or {}
    output_modalities = architecture.get("output_modalities") or []
    if output_modalities and "text" not in output_modalities:
        return False
    if mode == "quick":
        return {"tools", "structured_outputs"}.issubset(parameters)
    if mode == "deep":
        return "structured_outputs" in parameters
    raise ValueError(f"Unknown OpenRouter selection mode: {mode}")


def _format_context_length(value: Any) -> str | None:
    if not isinstance(value, int) or value <= 0:
        return None
    if value >= 1_000_000:
        binary_millions = value / (1024 * 1024)
        if abs(binary_millions - round(binary_millions)) < 0.05:
            return f"{round(binary_millions):g}M ctx"
        return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M ctx"
    if value >= 1_000:
        return f"{round(value / 1024):g}K ctx"
    return f"{value} ctx"


def _format_per_million(value: Any) -> str | None:
    try:
        price = float(value) * 1_000_000
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    if price == 0:
        return "$0"
    if price < 0.01:
        return f"${price:.4f}".rstrip("0")
    return f"${price:.2f}".rstrip("0").rstrip(".")


def _model_option(model: dict[str, Any]) -> ModelOption:
    model_id = str(model["id"])
    label = str(model.get("name") or model_id)
    details: list[str] = []

    context = _format_context_length(model.get("context_length"))
    if context:
        details.append(context)

    pricing = model.get("pricing") or {}
    prompt = _format_per_million(pricing.get("prompt"))
    completion = _format_per_million(pricing.get("completion"))
    if prompt is not None and completion is not None:
        details.append(f"{prompt}/{completion} per 1M")

    if details:
        label = f"{label} - {', '.join(details)}"
    return label, model_id


def _options_for_mode(
    models: list[dict[str, Any]], mode: str, limit: int
) -> list[ModelOption]:
    compatible = [
        _model_option(model) for model in models if _supports_mode(model, mode)
    ]
    recommended = [
        value
        for _, value in OPENROUTER_RECOMMENDED_MODELS.get(mode, [])
        if value != "custom"
    ]
    priority = {model_id: index for index, model_id in enumerate(recommended)}
    compatible.sort(key=lambda option: priority.get(option[1], len(priority)))
    return [*compatible[:limit], ("Custom model ID", "custom")]


def get_openrouter_model_options(
    mode: str, *, limit: int = 12, force_refresh: bool = False
) -> list[ModelOption]:
    """Return popular OpenRouter models compatible with a graph role."""
    return _options_for_mode(
        fetch_openrouter_models(force_refresh=force_refresh), mode, limit
    )


def get_openrouter_model_catalog(
    *, limit: int = 12, force_refresh: bool = False
) -> ProviderModeOptions:
    """Return quick/deep model options from one catalog request."""
    models = fetch_openrouter_models(force_refresh=force_refresh)
    return {
        "openrouter": {
            "quick": _options_for_mode(models, "quick", limit),
            "deep": _options_for_mode(models, "deep", limit),
        }
    }
