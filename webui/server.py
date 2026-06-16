"""FastAPI web UI server for TradingAgents."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel, Field, field_validator

load_dotenv()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.dataflows.crypto_utils import normalize_crypto_symbol  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS  # noqa: E402
from tradingagents.llm_clients.openrouter_catalog import (  # noqa: E402
    OpenRouterCatalogError,
    get_openrouter_model_catalog,
)


_ANALYST_STAGES = ("market", "social", "news", "fundamentals")
_PIPELINE_STAGES = (
    *_ANALYST_STAGES,
    "bull",
    "bear",
    "research_mgr",
    "trader",
    "aggressive",
    "conservative",
    "neutral",
    "portfolio",
)
_NODE_TO_STAGE = {
    "Market Analyst": "market",
    "Social Analyst": "social",
    "News Analyst": "news",
    "Fundamentals Analyst": "fundamentals",
    "Bull Researcher": "bull",
    "Bear Researcher": "bear",
    "Research Manager": "research_mgr",
    "Trader": "trader",
    "Aggressive Analyst": "aggressive",
    "Conservative Analyst": "conservative",
    "Neutral Analyst": "neutral",
    "Portfolio Manager": "portfolio",
}


@dataclass
class RunState:
    """Mutable state shared by a worker thread and its SSE consumer."""

    queue: Queue = field(default_factory=Queue)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    stage_status: dict[str, str] = field(default_factory=dict)
    stage_lock: threading.Lock = field(default_factory=threading.Lock)


class ProgressCallbackHandler(BaseCallbackHandler):
    """Pushes live tool/LLM activity events to the SSE queue."""

    def __init__(self, push_fn, stage_fn=None) -> None:
        super().__init__()
        self._push = push_fn
        self._stage = stage_fn
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def on_chain_start(self, serialized, inputs, *, metadata=None, **kwargs):
        """Surface the actual LangGraph node that started executing."""
        if self._stage is None:
            return
        node = (metadata or {}).get("langgraph_node")
        stage = _NODE_TO_STAGE.get(node)
        if stage:
            self._stage(stage, "running")

    def on_chat_model_start(self, serialized, messages, **kwargs):
        with self._lock:
            self.llm_calls += 1
        name = (serialized.get("kwargs", {}).get("model") or
                serialized.get("kwargs", {}).get("model_name") or "LLM")
        self._push({"type": "progress", "event": "llm", "name": name})

    def on_llm_start(self, serialized, prompts, **kwargs):
        with self._lock:
            self.llm_calls += 1

    def on_llm_end(self, response: LLMResult, **kwargs):
        try:
            msg = response.generations[0][0].message
            usage = getattr(msg, "usage_metadata", None) or {}
            with self._lock:
                self.tokens_in  += usage.get("input_tokens", 0)
                self.tokens_out += usage.get("output_tokens", 0)
        except Exception:
            pass

    def on_tool_start(self, serialized, input_str, **kwargs):
        with self._lock:
            self.tool_calls += 1
        name = serialized.get("name", "tool")
        preview = (input_str or "")[:120]
        self._push({"type": "progress", "event": "tool", "name": name, "input": preview})

    def on_tool_end(self, output, **kwargs):
        preview = str(output or "")[:80]
        self._push({"type": "progress", "event": "tool_done", "preview": preview})

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
            }


app = FastAPI(title="TradingAgents Web UI")

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# run_id → mutable run state (cleaned up after stream ends)
_runs: dict[str, RunState] = {}
_runs_lock = threading.Lock()

_REPORT_FIELDS = {
    "market_report":        "Market Analyst",
    "sentiment_report":     "Social Analyst",
    "news_report":          "News Analyst",
    "fundamentals_report":  "Fundamentals Analyst",
    "investment_plan":      "Research Manager",
    "trader_investment_plan": "Trader",
    "final_trade_decision": "Portfolio Manager",
}
_REPORT_TO_STAGE = {
    "market_report": "market",
    "sentiment_report": "social",
    "news_report": "news",
    "fundamentals_report": "fundamentals",
    "investment_plan": "research_mgr",
    "trader_investment_plan": "trader",
    "final_trade_decision": "portfolio",
}


class AnalyzeRequest(BaseModel):
    # Field names mirror the frontend form in index.html
    ticker: str = Field(min_length=1, max_length=32)
    date: str
    analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    provider: str = "openai"
    quick_model: str = Field(default="gpt-5.4-mini", min_length=1, max_length=120)
    deep_model: str = Field(default="gpt-5.4-mini", min_length=1, max_length=120)
    max_debate_rounds: int = Field(default=1, ge=1, le=5)
    max_risk_discuss_rounds: int = Field(default=1, ge=1, le=5)
    language: str = Field(default="English", min_length=1, max_length=60)
    checkpoint: bool = False

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker or not all(ch.isalnum() or ch in "._-^" for ch in ticker):
            raise ValueError("Enter a valid ticker, such as NVDA, 0700.HK, or BTC-USD.")
        return ticker

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Use an analysis date in YYYY-MM-DD format.") from exc
        if parsed > date.today():
            raise ValueError("Analysis date cannot be in the future.")
        return value

    @field_validator("analysts")
    @classmethod
    def validate_analysts(cls, value: list[str]) -> list[str]:
        invalid = set(value) - set(_ANALYST_STAGES)
        if invalid:
            raise ValueError(f"Unknown analysts: {', '.join(sorted(invalid))}.")
        selected = [stage for stage in _ANALYST_STAGES if stage in value]
        if not selected:
            raise ValueError("Select at least one analyst.")
        return selected

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if value not in MODEL_OPTIONS:
            raise ValueError(f"Unknown LLM provider: {value}.")
        return value


def _push_stage(run_state: RunState, stage: str, status: str) -> None:
    """Push a stage transition once and retain its latest status."""
    if stage not in _PIPELINE_STAGES:
        return
    with run_state.stage_lock:
        if run_state.stage_status.get(stage) == status:
            return
        run_state.stage_status[stage] = status
    run_state.queue.put({"type": "stage", "stage": stage, "status": status})


def _finish_stage_for_report(run_state: RunState, report_field: str) -> None:
    """Complete the pipeline stages represented by a streamed report."""
    stage = _REPORT_TO_STAGE.get(report_field)
    if stage is None:
        return
    if stage == "research_mgr":
        for key in ("bull", "bear", "research_mgr"):
            _push_stage(run_state, key, "done")
    elif stage == "portfolio":
        for key in ("aggressive", "conservative", "neutral", "portfolio"):
            _push_stage(run_state, key, "done")
    else:
        _push_stage(run_state, stage, "done")


def _finish_active_stages(run_state: RunState, status: str) -> None:
    with run_state.stage_lock:
        active = [
            stage
            for stage, current_status in run_state.stage_status.items()
            if current_status in {"queued", "running"}
        ]
    for stage in active:
        _push_stage(run_state, stage, status)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/models")
async def get_models():
    models = {
        provider: {
            mode: list(options)
            for mode, options in mode_options.items()
        }
        for provider, mode_options in MODEL_OPTIONS.items()
    }
    try:
        models.update(await asyncio.to_thread(get_openrouter_model_catalog))
    except OpenRouterCatalogError:
        pass
    return models


@app.post("/api/analyze")
async def start_analysis(req: AnalyzeRequest) -> dict:
    run_id = str(uuid.uuid4())
    run_state = RunState()
    with _runs_lock:
        _runs[run_id] = run_state

    def _push(event: dict[str, Any]) -> None:
        run_state.queue.put(event)

    def run() -> None:
        try:
            selected_analysts = set(req.analysts)
            for stage in _PIPELINE_STAGES:
                status = "queued"
                if stage in _ANALYST_STAGES and stage not in selected_analysts:
                    status = "skipped"
                _push_stage(run_state, stage, status)

            ticker = normalize_crypto_symbol(req.ticker)
            config = DEFAULT_CONFIG.copy()
            config["llm_provider"]          = req.provider
            config["quick_think_llm"]       = req.quick_model
            config["deep_think_llm"]        = req.deep_model
            config["max_debate_rounds"]     = req.max_debate_rounds
            config["max_risk_discuss_rounds"] = req.max_risk_discuss_rounds
            config["output_language"]       = req.language
            config["checkpoint_enabled"]    = req.checkpoint

            _push({"type": "status", "message": "Initializing analysis"})
            stats = ProgressCallbackHandler(
                _push,
                lambda stage, status: _push_stage(run_state, stage, status),
            )
            ta = TradingAgentsGraph(
                selected_analysts=req.analysts,
                debug=False,
                config=config,
                callbacks=[stats],
            )
            _push({"type": "status", "message": f"Analyzing {ticker} on {req.date}"})

            prev: dict[str, str] = {}
            for chunk in ta.propagate_stream(ticker, req.date, callbacks=[stats]):
                if run_state.cancel_event.is_set():
                    _finish_active_stages(run_state, "cancelled")
                    _push({"type": "cancelled", "message": "Analysis cancelled"})
                    return
                for report_field, agent_name in _REPORT_FIELDS.items():
                    val = chunk.get(report_field) or ""
                    if val and val != prev.get(report_field, ""):
                        _finish_stage_for_report(run_state, report_field)
                        _push(
                            {
                                "type": "report",
                                "field": report_field,
                                "agent": agent_name,
                                "content": val,
                            }
                        )
                        prev[report_field] = val

            if run_state.cancel_event.is_set():
                _finish_active_stages(run_state, "cancelled")
                _push({"type": "cancelled", "message": "Analysis cancelled"})
                return

            _finish_active_stages(run_state, "done")
            decision = ta.process_signal(
                (ta.curr_state or {}).get("final_trade_decision", "")
            )
            _push({
                "type": "complete",
                "decision": decision,
                "ticker": ticker,
                "date": req.date,
                "stats": stats.get_stats(),
            })

        except Exception as exc:
            _finish_active_stages(run_state, "error")
            _push({"type": "error", "message": str(exc)})
        finally:
            run_state.queue.put(None)  # sentinel

    threading.Thread(target=run, daemon=True).start()
    return {"run_id": run_id}


@app.post("/api/cancel/{run_id}")
async def cancel_analysis(run_id: str) -> dict:
    with _runs_lock:
        run_state = _runs.get(run_id)
    if run_state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run_state.cancel_event.set()
    run_state.queue.put({"type": "status", "message": "Cancelling analysis"})
    return {"status": "cancelling"}


@app.get("/api/stream/{run_id}")
async def stream_job(run_id: str) -> StreamingResponse:
    with _runs_lock:
        run_state = _runs.get(run_id)
    if run_state is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def _generate():
        loop = asyncio.get_event_loop()
        while True:
            try:
                item = await loop.run_in_executor(
                    None, lambda: run_state.queue.get(timeout=30)
                )
            except Empty:
                yield ": keepalive\n\n"
                continue
            if item is None:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                with _runs_lock:
                    _runs.pop(run_id, None)
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
