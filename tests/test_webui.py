from pathlib import Path
from unittest.mock import MagicMock

from tradingagents.graph.trading_graph import TradingAgentsGraph


def _final_state():
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-10",
        "market_report": "Market report",
        "sentiment_report": "Sentiment report",
        "news_report": "News report",
        "fundamentals_report": "Fundamentals report",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "judge_decision": "",
        },
        "investment_plan": "Investment plan",
        "trader_investment_plan": "Trader plan",
        "risk_debate_state": {
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "judge_decision": "",
        },
        "final_trade_decision": "Rating: Buy",
    }


def test_propagate_stream_streams_and_persists_final_state(tmp_path):
    callbacks = [object()]
    graph = MagicMock()
    graph.config = {
        "checkpoint_enabled": False,
        "results_dir": str(tmp_path),
    }
    graph.log_states_dict = {}
    graph._checkpointer_ctx = None
    graph.memory_log.get_past_context.return_value = "prior decisions"
    graph.propagator.create_initial_state.return_value = {"initial": "state"}
    graph.propagator.get_graph_args.return_value = {
        "stream_mode": "values",
        "config": {},
    }
    graph.graph.stream.return_value = [
        {"market_report": "Market report"},
        _final_state(),
    ]

    chunks = list(
        TradingAgentsGraph.propagate_stream(
            graph, "NVDA", "2026-01-10", callbacks=callbacks
        )
    )

    assert chunks == graph.graph.stream.return_value
    graph._resolve_pending_entries.assert_called_once_with("NVDA")
    graph.memory_log.get_past_context.assert_called_once_with("NVDA")
    graph.propagator.create_initial_state.assert_called_once_with(
        "NVDA", "2026-01-10", past_context="prior decisions"
    )
    graph.propagator.get_graph_args.assert_called_once_with(callbacks=callbacks)
    graph.memory_log.store_decision.assert_called_once_with(
        ticker="NVDA",
        trade_date="2026-01-10",
        final_trade_decision="Rating: Buy",
    )
    assert graph.curr_state == _final_state()
    assert (
        tmp_path
        / "NVDA"
        / "TradingAgentsStrategy_logs"
        / "full_states_log_2026-01-10.json"
    ).exists()


def test_webui_is_installable_from_package_metadata():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '"fastapi>=' in pyproject
    assert '"uvicorn>=' in pyproject
    assert 'tradingagents-web = "webui.__main__:main"' in pyproject
    assert 'include = ["tradingagents*", "cli*", "webui*"]' in pyproject
    assert 'webui = ["static/*"]' in pyproject
