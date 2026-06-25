"""Tests for presentation-only report translation."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.output_translation import (
    OutputTranslator,
    normalize_output_language,
)


@pytest.mark.unit
class TestOutputTranslator:
    def test_normalizes_vietnamese_aliases(self):
        assert normalize_output_language("vi") == "Vietnamese"
        assert normalize_output_language("vi-VN") == "Vietnamese"
        assert normalize_output_language("Tiếng Việt") == "Vietnamese"

    def test_english_is_zero_call_identity_path(self):
        llm = MagicMock()
        translator = OutputTranslator(llm, "English")
        state = {"market_report": "English report"}

        assert translator.translate_state(state) is state
        llm.invoke.assert_not_called()

    def test_translates_user_facing_copy_without_mutating_original(self):
        llm = MagicMock()
        llm.invoke.side_effect = lambda messages: MagicMock(
            content=f"VI: {messages[-1][1]}"
        )
        translator = OutputTranslator(llm, "vi")
        state = {
            "market_report": "Market report",
            "messages": [object()],
            "investment_debate_state": {
                "bull_history": "Bull case",
                "history": "Internal debate history",
            },
        }

        localized = translator.translate_state(state)

        assert localized is not state
        assert localized["market_report"] == "VI: Market report"
        assert localized["investment_debate_state"]["bull_history"] == "VI: Bull case"
        assert localized["investment_debate_state"]["history"] == "Internal debate history"
        assert localized["messages"] is state["messages"]
        assert state["market_report"] == "Market report"
        assert state["investment_debate_state"]["bull_history"] == "Bull case"

    def test_caches_identical_report_text(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Bản dịch")
        translator = OutputTranslator(llm, "Vietnamese")

        assert translator.translate_text("Report") == "Bản dịch"
        assert translator.translate_text("Report") == "Bản dịch"
        llm.invoke.assert_called_once()

    def test_translation_prompt_protects_canonical_values(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="Xếp hạng: Buy")
        translator = OutputTranslator(llm, "Vietnamese")

        translator.translate_text("Rating: Buy")

        messages = llm.invoke.call_args.args[0]
        system_prompt = messages[0][1]
        assert "Vietnamese" in system_prompt
        assert "Buy, Overweight, Hold, Underweight, Sell" in system_prompt
        assert messages[1] == ("human", "Rating: Buy")

    def test_translation_failure_returns_original(self):
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("provider unavailable")
        translator = OutputTranslator(llm, "Vietnamese")

        assert translator.translate_text("Original report") == "Original report"


@pytest.mark.unit
def test_graph_keeps_agent_config_english_and_translation_language_run_local(tmp_path):
    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "output_language": "Vietnamese",
            "results_dir": str(tmp_path / "results"),
            "data_cache_dir": str(tmp_path / "cache"),
            "memory_log_path": str(tmp_path / "memory.md"),
        }
    )
    client = MagicMock()
    client.get_llm.return_value = MagicMock()

    with (
        patch(
            "tradingagents.graph.trading_graph.create_llm_client",
            return_value=client,
        ),
        patch("tradingagents.graph.trading_graph.set_config") as set_config,
    ):
        graph = TradingAgentsGraph(selected_analysts=["market"], config=config)

    agent_config = set_config.call_args.args[0]
    assert agent_config["output_language"] == "English"
    assert graph.config["output_language"] == "Vietnamese"
    assert graph.output_translator.language == "Vietnamese"
