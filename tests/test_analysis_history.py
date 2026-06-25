"""Analysis history persistence tests."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from tradingagents.observability.analysis_history import (
    AnalysisHistoryStore,
    json_safe,
)


def test_json_safe_serializes_langchain_messages():
    payload = {"messages": [AIMessage(content="hello", id="msg-1")]}

    safe = json_safe(payload)

    assert safe["messages"][0]["content"] == "hello"
    assert safe["messages"][0]["id"] == "msg-1"
    json.dumps(safe)


def test_analysis_history_store_persists_run_reports_and_final_state(tmp_path):
    store = AnalysisHistoryStore({"results_dir": str(tmp_path)})

    artifact_dir = store.start_run(
        run_id="run-1",
        ticker="NVDA",
        trade_date="2026-01-10",
        provider="openrouter",
        quick_model="deepseek/deepseek-v4-flash",
        deep_model="deepseek/deepseek-v4-pro",
        analysts=["market", "news"],
        payload={
            "ticker": "NVDA",
            "date": "2026-01-10",
            "provider": "openrouter",
        },
        config={"results_dir": str(tmp_path)},
    )
    report_path = store.save_report(
        run_id="run-1",
        field="market_report",
        agent="Market Analyst",
        content="Market report",
    )
    final_state_path = store.complete_run(
        run_id="run-1",
        decision="Buy",
        stats={
            "tokens_in": 10,
            "tokens_out": 5,
            "llm_calls": 2,
            "tool_calls": 3,
        },
        final_state={"messages": [AIMessage(content="final")]},
        duration_ms=1234,
    )

    run = store.get_run("run-1")
    assert run is not None
    assert run["status"] == "completed"
    assert run["ticker"] == "NVDA"
    assert run["trade_date"] == "2026-01-10"
    assert run["decision"] == "Buy"
    assert run["tokens_in"] == 10
    assert run["tokens_out"] == 5
    assert run["payload"]["provider"] == "openrouter"
    assert store.read_report("run-1", "market_report") == "Market report"
    assert report_path.exists()
    assert final_state_path is not None and final_state_path.exists()
    assert (artifact_dir / "manifest.json").exists()

    final_state = json.loads(final_state_path.read_text(encoding="utf-8"))
    assert final_state["messages"][0]["content"] == "final"
    assert [item["run_id"] for item in store.list_runs()] == ["run-1"]


def test_analysis_history_store_records_failure_and_delete(tmp_path):
    store = AnalysisHistoryStore({"analysis_history_dir": str(tmp_path / "history")})
    store.start_run(
        run_id="run-2",
        ticker="AAPL",
        trade_date="2026-01-11",
        provider="openai",
        quick_model="gpt-5.4-mini",
        deep_model="gpt-5.4",
        analysts=["market"],
        payload={"ticker": "AAPL"},
        config={},
    )

    store.fail_run(run_id="run-2", error="provider unavailable")

    run = store.get_run("run-2")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "provider unavailable"
    assert store.delete_run("run-2") is True
    assert store.get_run("run-2") is None
