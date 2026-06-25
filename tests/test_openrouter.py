"""OpenRouter catalog, client, CLI, and WebUI integration tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from pydantic import BaseModel

from cli import utils as cli_utils
from tradingagents.llm_clients import openrouter_catalog
from tradingagents.llm_clients.openai_client import OpenAIClient
from webui import server as webui_server


@pytest.fixture(autouse=True)
def _reset_catalog_cache(monkeypatch):
    monkeypatch.setattr(openrouter_catalog, "_CACHED_MODELS", None)
    monkeypatch.setattr(openrouter_catalog, "_CACHE_EXPIRES_AT", 0.0)


def _model(
    model_id: str,
    *,
    parameters: list[str],
    output_modalities: list[str] | None = None,
) -> dict:
    return {
        "id": model_id,
        "name": model_id.replace("/", ": "),
        "supported_parameters": parameters,
        "architecture": {
            "output_modalities": output_modalities or ["text"],
        },
        "context_length": 131_072,
        "pricing": {
            "prompt": "0.000001",
            "completion": "0.000002",
        },
    }


def test_catalog_filters_models_by_graph_role(monkeypatch):
    models = [
        _model(
            "vendor/full",
            parameters=["tools", "structured_outputs", "response_format"],
        ),
        _model("vendor/structured", parameters=["structured_outputs"]),
        _model("vendor/tools-only", parameters=["tools"]),
        _model(
            "vendor/image-output",
            parameters=["tools", "structured_outputs"],
            output_modalities=["image"],
        ),
    ]
    monkeypatch.setattr(
        openrouter_catalog, "fetch_openrouter_models", lambda **kwargs: models
    )

    quick = openrouter_catalog.get_openrouter_model_options("quick")
    deep = openrouter_catalog.get_openrouter_model_options("deep")

    assert [value for _, value in quick] == ["vendor/full", "custom"]
    assert [value for _, value in deep] == [
        "vendor/full",
        "vendor/structured",
        "custom",
    ]
    assert "128K ctx" in quick[0][0]
    assert "$1/$2 per 1M" in quick[0][0]


def test_catalog_prioritizes_researched_openrouter_value_models(monkeypatch):
    models = [
        _model(
            "vendor/full",
            parameters=["tools", "structured_outputs", "response_format"],
        ),
        _model(
            "qwen/qwen3.7-max",
            parameters=["tools", "structured_outputs", "response_format"],
        ),
        _model(
            "qwen/qwen3.7-plus",
            parameters=["tools", "structured_outputs", "response_format"],
        ),
        _model(
            "deepseek/deepseek-v4-pro",
            parameters=["tools", "structured_outputs", "response_format"],
        ),
        _model(
            "deepseek/deepseek-v4-flash",
            parameters=["tools", "structured_outputs", "response_format"],
        ),
    ]
    monkeypatch.setattr(
        openrouter_catalog, "fetch_openrouter_models", lambda **kwargs: models
    )

    quick = openrouter_catalog.get_openrouter_model_options("quick")
    deep = openrouter_catalog.get_openrouter_model_options("deep")

    assert [value for _, value in quick[:2]] == [
        "deepseek/deepseek-v4-flash",
        "qwen/qwen3.7-plus",
    ]
    assert [value for _, value in deep[:2]] == [
        "deepseek/deepseek-v4-pro",
        "qwen/qwen3.7-max",
    ]


def test_catalog_request_uses_auth_attribution_and_cache(monkeypatch):
    response = MagicMock()
    response.json.return_value = {
        "data": [_model("vendor/full", parameters=["tools", "structured_outputs"])]
    }
    request = MagicMock(return_value=response)
    monkeypatch.setattr(openrouter_catalog.requests, "get", request)
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.test/app")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Test App")

    first = openrouter_catalog.fetch_openrouter_models()
    second = openrouter_catalog.fetch_openrouter_models()

    assert first == second
    request.assert_called_once()
    kwargs = request.call_args.kwargs
    assert kwargs["headers"] == {
        "HTTP-Referer": "https://example.test/app",
        "X-OpenRouter-Title": "Test App",
        "Authorization": "Bearer secret",
    }
    assert kwargs["params"] == {"sort": "most-popular"}


def test_catalog_uses_stale_cache_when_refresh_fails(monkeypatch):
    cached = [_model("vendor/cached", parameters=["structured_outputs"])]
    monkeypatch.setattr(openrouter_catalog, "_CACHED_MODELS", cached)
    monkeypatch.setattr(openrouter_catalog, "_CACHE_EXPIRES_AT", 0.0)
    monkeypatch.setattr(
        openrouter_catalog.requests,
        "get",
        MagicMock(side_effect=requests.ConnectionError("offline")),
    )

    assert openrouter_catalog.fetch_openrouter_models(force_refresh=True) == cached


def test_openrouter_client_sets_routing_headers_and_json_schema(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.test/app")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "Test App")

    llm = OpenAIClient(
        "vendor/model",
        provider="openrouter",
        default_headers={"X-Custom": "value"},
        extra_body={"provider": {"data_collection": "deny"}},
    ).get_llm()

    assert type(llm).__name__ == "OpenRouterChatOpenAI"
    assert str(llm.openai_api_base) == "https://openrouter.ai/api/v1"
    assert llm.default_headers == {
        "HTTP-Referer": "https://example.test/app",
        "X-OpenRouter-Title": "Test App",
        "X-Custom": "value",
    }
    assert llm.extra_body == {
        "provider": {
            "require_parameters": True,
            "data_collection": "deny",
        }
    }
    assert llm.use_responses_api is None

    class Result(BaseModel):
        answer: str

    runnable = llm.with_structured_output(Result)
    first = runnable.steps[0] if hasattr(runnable, "steps") else runnable
    assert "tool_choice" not in first.kwargs
    assert first.kwargs["ls_structured_output_format"]["kwargs"] == {
        "method": "json_schema",
        "strict": True,
    }


def test_cli_requests_role_specific_openrouter_models(monkeypatch):
    captured: dict[str, str] = {}

    def fake_fetch(mode: str):
        captured["mode"] = mode
        return [("Tool Model", "vendor/tool-model"), ("Custom model ID", "custom")]

    prompt = MagicMock()
    prompt.ask.return_value = "vendor/tool-model"
    monkeypatch.setattr(cli_utils, "_fetch_openrouter_models", fake_fetch)
    monkeypatch.setattr(cli_utils.questionary, "select", MagicMock(return_value=prompt))

    assert cli_utils.select_openrouter_model("quick") == "vendor/tool-model"
    assert captured["mode"] == "quick"


def test_cli_uses_recommended_openrouter_models_when_catalog_unavailable(monkeypatch):
    monkeypatch.setattr(
        cli_utils,
        "get_openrouter_model_options",
        MagicMock(side_effect=openrouter_catalog.OpenRouterCatalogError("offline")),
    )

    quick = cli_utils._fetch_openrouter_models("quick")
    deep = cli_utils._fetch_openrouter_models("deep")

    assert [value for _, value in quick[:2]] == [
        "deepseek/deepseek-v4-flash",
        "qwen/qwen3.7-plus",
    ]
    assert [value for _, value in deep[:2]] == [
        "deepseek/deepseek-v4-pro",
        "qwen/qwen3.7-max",
    ]


def test_webui_exposes_openrouter_models(monkeypatch):
    catalog = {
        "openrouter": {
            "quick": [("Quick", "vendor/quick"), ("Custom model ID", "custom")],
            "deep": [("Deep", "vendor/deep"), ("Custom model ID", "custom")],
        }
    }
    monkeypatch.setattr(webui_server, "get_openrouter_model_catalog", lambda: catalog)

    models = asyncio.run(webui_server.get_models())
    request = webui_server.AnalyzeRequest(
        ticker="NVDA",
        date="2020-01-10",
        analysts=["market"],
        provider="openrouter",
        quick_model="vendor/quick",
        deep_model="vendor/deep",
    )
    html = Path("webui/static/index.html").read_text(encoding="utf-8")

    assert models["openrouter"] == catalog["openrouter"]
    assert request.provider == "openrouter"
    assert '<option value="openrouter">OpenRouter</option>' in html
