import asyncio
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tradingagents.graph.trading_graph import TradingAgentsGraph
from webui import server as webui_server


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
    graph._log_state.side_effect = lambda trade_date, final_state: (
        TradingAgentsGraph._log_state(graph, trade_date, final_state)
    )
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
    graph.localize_output.side_effect = lambda state: state

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


def test_propagate_stream_localizes_yielded_copy_but_persists_canonical_state(tmp_path):
    canonical_state = _final_state()
    localized_state = dict(canonical_state)
    localized_state["market_report"] = "Báo cáo thị trường"

    graph = MagicMock()
    graph.config = {
        "checkpoint_enabled": False,
        "results_dir": str(tmp_path),
    }
    graph.log_states_dict = {}
    graph._log_state.side_effect = lambda trade_date, final_state: (
        TradingAgentsGraph._log_state(graph, trade_date, final_state)
    )
    graph._checkpointer_ctx = None
    graph.memory_log.get_past_context.return_value = ""
    graph.propagator.create_initial_state.return_value = {"initial": "state"}
    graph.propagator.get_graph_args.return_value = {
        "stream_mode": "values",
        "config": {},
    }
    graph.graph.stream.return_value = [canonical_state]
    graph.localize_output.return_value = localized_state

    chunks = list(
        TradingAgentsGraph.propagate_stream(graph, "NVDA", "2026-01-10")
    )

    assert chunks == [localized_state]
    assert graph.curr_state == canonical_state
    graph.memory_log.store_decision.assert_called_once_with(
        ticker="NVDA",
        trade_date="2026-01-10",
        final_trade_decision="Rating: Buy",
    )


def test_analyze_request_normalizes_ticker_analysts_and_independent_rounds():
    request = webui_server.AnalyzeRequest(
        ticker=" btc ",
        date="2020-01-10",
        analysts=["news", "market", "news"],
        provider="openai",
        quick_model="gpt-5.4-mini",
        deep_model="gpt-5.4",
        max_debate_rounds=2,
        max_risk_discuss_rounds=4,
    )

    assert request.ticker == "BTC"
    assert request.analysts == ["market", "news"]
    assert request.max_debate_rounds == 2
    assert request.max_risk_discuss_rounds == 4


def test_analyze_request_rejects_future_date_and_unknown_provider():
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(ValidationError):
        webui_server.AnalyzeRequest(
            ticker="NVDA",
            date=future,
            analysts=["market"],
            provider="not-a-provider",
        )


def test_stage_events_are_deduplicated_and_report_completes_related_stages():
    run_state = webui_server.RunState()

    webui_server._push_stage(run_state, "bull", "running")
    webui_server._push_stage(run_state, "bull", "running")
    webui_server._finish_stage_for_report(run_state, "investment_plan")

    events = []
    while not run_state.queue.empty():
        events.append(run_state.queue.get_nowait())

    assert events == [
        {"type": "stage", "stage": "bull", "status": "running"},
        {"type": "stage", "stage": "bull", "status": "done"},
        {"type": "stage", "stage": "bear", "status": "done"},
        {"type": "stage", "stage": "research_mgr", "status": "done"},
    ]


def test_stage_start_finishes_previous_running_stage_without_report():
    run_state = webui_server.RunState()
    selected_analysts = {"market"}

    for stage in webui_server._PIPELINE_STAGES:
        status = "queued"
        if stage in webui_server._ANALYST_STAGES and stage not in selected_analysts:
            status = "skipped"
        webui_server._push_stage(run_state, stage, status)

    webui_server._start_stage(run_state, "market")
    webui_server._start_stage(run_state, "bull")
    webui_server._finish_stage_for_report(run_state, "investment_plan")
    webui_server._finish_stage_for_report(run_state, "trader_investment_plan")
    webui_server._finish_stage_for_report(run_state, "final_trade_decision")

    assert run_state.stage_status["market"] == "done"
    assert run_state.stage_status["social"] == "skipped"
    assert run_state.stage_status["news"] == "skipped"
    assert run_state.stage_status["fundamentals"] == "skipped"
    assert not any(status == "running" for status in run_state.stage_status.values())
    assert sum(status == "done" for status in run_state.stage_status.values()) == 9


def test_stage_start_does_not_reopen_skipped_or_failed_stages():
    run_state = webui_server.RunState()

    webui_server._push_stage(run_state, "social", "skipped")
    webui_server._push_stage(run_state, "news", "error")

    webui_server._start_stage(run_state, "social")
    webui_server._push_stage(run_state, "news", "running")

    assert run_state.stage_status["social"] == "skipped"
    assert run_state.stage_status["news"] == "error"


def test_start_analysis_applies_risk_rounds_independently(monkeypatch):
    captured = {}
    monkeypatch.setitem(webui_server.DEFAULT_CONFIG, "analysis_history_enabled", False)

    class FakeTradingAgentsGraph:
        def __init__(self, selected_analysts, debug, config, callbacks):
            captured["config"] = config
            self.curr_state = {"final_trade_decision": "Rating: Hold"}

        def propagate_stream(self, ticker, trade_date, callbacks):
            yield {"final_trade_decision": "Rating: Hold"}

        def process_signal(self, decision):
            return "Hold"

    monkeypatch.setattr(webui_server, "TradingAgentsGraph", FakeTradingAgentsGraph)
    request = webui_server.AnalyzeRequest(
        ticker="NVDA",
        date="2020-01-10",
        analysts=["market"],
        provider="openai",
        max_debate_rounds=2,
        max_risk_discuss_rounds=5,
    )

    result = asyncio.run(webui_server.start_analysis(request))
    run_state = webui_server._runs[result["run_id"]]
    while run_state.queue.get(timeout=2) is not None:
        pass
    webui_server._runs.pop(result["run_id"], None)

    assert captured["config"]["max_debate_rounds"] == 2
    assert captured["config"]["max_risk_discuss_rounds"] == 5


def test_start_analysis_advances_stage_on_downstream_start_without_report(monkeypatch):
    monkeypatch.setitem(webui_server.DEFAULT_CONFIG, "analysis_history_enabled", False)

    class FakeTradingAgentsGraph:
        def __init__(self, selected_analysts, debug, config, callbacks):
            self.curr_state = {"final_trade_decision": "Rating: Hold"}

        def propagate_stream(self, ticker, trade_date, callbacks):
            callback = callbacks[0]
            callback.on_chain_start(
                {},
                {},
                metadata={"langgraph_node": "Market Analyst"},
            )
            yield {}
            callback.on_chain_start(
                {},
                {},
                metadata={"langgraph_node": "Bull Researcher"},
            )
            yield {"investment_plan": "Investment plan"}
            callback.on_chain_start(
                {},
                {},
                metadata={"langgraph_node": "Trader"},
            )
            yield {"trader_investment_plan": "Trader plan"}
            callback.on_chain_start(
                {},
                {},
                metadata={"langgraph_node": "Portfolio Manager"},
            )
            yield {"final_trade_decision": "Rating: Hold"}

        def process_signal(self, decision):
            return "Hold"

    monkeypatch.setattr(webui_server, "TradingAgentsGraph", FakeTradingAgentsGraph)
    request = webui_server.AnalyzeRequest(
        ticker="NVDA",
        date="2020-01-10",
        analysts=["market"],
        provider="openai",
    )

    result = asyncio.run(webui_server.start_analysis(request))
    run_state = webui_server._runs[result["run_id"]]
    events = []
    try:
        while True:
            event = run_state.queue.get(timeout=2)
            if event is None:
                break
            events.append(event)
    finally:
        webui_server._runs.pop(result["run_id"], None)

    stage_events = [event for event in events if event["type"] == "stage"]
    assert {"type": "stage", "stage": "market", "status": "done"} in stage_events
    assert run_state.stage_status["market"] == "done"
    assert not any(status == "running" for status in run_state.stage_status.values())


def test_start_analysis_records_server_side_history(monkeypatch, tmp_path):
    monkeypatch.setitem(webui_server.DEFAULT_CONFIG, "analysis_history_enabled", True)
    monkeypatch.setitem(
        webui_server.DEFAULT_CONFIG,
        "analysis_history_dir",
        str(tmp_path / "history"),
    )
    monkeypatch.setitem(webui_server.DEFAULT_CONFIG, "results_dir", str(tmp_path / "results"))

    class FakeTradingAgentsGraph:
        def __init__(self, selected_analysts, debug, config, callbacks):
            self.curr_state = None

        def propagate_stream(self, ticker, trade_date, callbacks):
            yield {"market_report": "Market report"}
            self.curr_state = _final_state()
            yield self.curr_state

        def process_signal(self, decision):
            return "Buy"

    monkeypatch.setattr(webui_server, "TradingAgentsGraph", FakeTradingAgentsGraph)
    request = webui_server.AnalyzeRequest(
        ticker="NVDA",
        date="2020-01-10",
        analysts=["market"],
        provider="openai",
        quick_model="gpt-5.4-mini",
        deep_model="gpt-5.4",
    )

    result = asyncio.run(webui_server.start_analysis(request))
    run_id = result["run_id"]
    run_state = webui_server._runs[run_id]
    while run_state.queue.get(timeout=2) is not None:
        pass
    webui_server._runs.pop(run_id, None)

    history = asyncio.run(webui_server.get_history())
    run = asyncio.run(webui_server.get_history_run(run_id))
    reports = asyncio.run(webui_server.get_history_reports(run_id))
    report = asyncio.run(webui_server.get_history_report(run_id, "market_report"))

    assert history[0]["run_id"] == run_id
    assert run["status"] == "completed"
    assert run["decision"] == "Buy"
    assert run["payload"]["ticker"] == "NVDA"
    assert {item["field"] for item in reports} >= {
        "market_report",
        "final_trade_decision",
    }
    assert report["content"] == "Market report"
    assert (tmp_path / "history" / "runs" / run_id / "final_state.json").exists()


def test_cancel_analysis_sets_cooperative_cancel_event():
    run_id = "cancel-test"
    run_state = webui_server.RunState()
    webui_server._runs[run_id] = run_state

    try:
        result = asyncio.run(webui_server.cancel_analysis(run_id))
        event = run_state.queue.get_nowait()
    finally:
        webui_server._runs.pop(run_id, None)

    assert result == {"status": "cancelling"}
    assert run_state.cancel_event.is_set()
    assert event == {"type": "status", "message": "Cancelling analysis"}


def test_webui_page_is_self_contained_and_exposes_accessible_run_controls():
    page = Path("webui/static/index.html").read_text(encoding="utf-8")

    assert "cdn.tailwindcss.com" not in page
    assert "cdn.jsdelivr.net" not in page
    assert 'role="tablist"' in page
    assert 'aria-live="assertive"' in page
    assert "max_risk_discuss_rounds: riskRounds" in page
    assert 'fetch(`/api/cancel/${currentRunId}`' in page
    assert 'fetch("/api/history?limit=100")' in page
    assert "Analysis history" in page
    assert 'view.textContent = "View"' in page
    assert "loadHistoryRun(record)" in page
    assert "/reports/${encodeURIComponent(item.field)}" in page
    assert "clearRunHistory" in page
