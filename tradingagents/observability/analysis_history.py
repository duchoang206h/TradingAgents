"""SQLite-backed analysis history with file artifacts.

The history index keeps searchable run metadata in SQLite while large
artifacts such as reports and final state live as files next to the DB.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


_REPORT_FIELDS = {
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
}


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with second-level precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_safe(value: Any) -> Any:
    """Convert common LangChain/Pydantic objects into JSON-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return json_safe(value.dict())
    return str(value)


def _dump_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, indent=2)


def _load_json(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _safe_run_component(value: str) -> str:
    """Validate UUID-like run identifiers as path components."""
    if not value or len(value) > 80:
        raise ValueError(f"invalid run_id: {value!r}")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(char not in allowed for char in value):
        raise ValueError(f"run_id contains unsafe characters: {value!r}")
    return value


class AnalysisHistoryStore:
    """Persist analysis run history and report artifacts."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        base_dir = cfg.get("analysis_history_dir")
        if base_dir is None:
            base_dir = Path(cfg.get("results_dir", ".")) / "analysis_history"
        self.base_dir = Path(base_dir).expanduser()
        self.runs_dir = self.base_dir / "runs"
        self.db_path = self.base_dir / "history.sqlite"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT,
                    quick_model TEXT,
                    deep_model TEXT,
                    analysts_json TEXT,
                    payload_json TEXT,
                    decision TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms INTEGER,
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    llm_calls INTEGER DEFAULT 0,
                    tool_calls INTEGER DEFAULT 0,
                    artifact_dir TEXT,
                    final_state_path TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_reports (
                    run_id TEXT NOT NULL,
                    field TEXT NOT NULL,
                    agent TEXT,
                    path TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, field),
                    FOREIGN KEY (run_id) REFERENCES analysis_runs(run_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_runs_ticker_date
                    ON analysis_runs(ticker, trade_date DESC);
                CREATE INDEX IF NOT EXISTS idx_analysis_runs_status_started
                    ON analysis_runs(status, started_at DESC);
                """
            )

    def artifact_dir(self, run_id: str) -> Path:
        return self.runs_dir / _safe_run_component(run_id)

    def start_run(
        self,
        *,
        run_id: str,
        ticker: str,
        trade_date: str,
        provider: str,
        quick_model: str,
        deep_model: str,
        analysts: list[str],
        payload: dict[str, Any],
        config: dict[str, Any],
    ) -> Path:
        safe_ticker_component(ticker)
        now = utc_now_iso()
        artifact_dir = self.artifact_dir(run_id)
        (artifact_dir / "reports").mkdir(parents=True, exist_ok=True)

        manifest = {
            "run_id": run_id,
            "ticker": ticker,
            "trade_date": trade_date,
            "provider": provider,
            "quick_model": quick_model,
            "deep_model": deep_model,
            "analysts": analysts,
            "payload": payload,
            "config": config,
            "started_at": now,
        }
        (artifact_dir / "manifest.json").write_text(
            _dump_json(manifest),
            encoding="utf-8",
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_runs (
                    run_id, ticker, trade_date, status, provider, quick_model,
                    deep_model, analysts_json, payload_json, started_at,
                    artifact_dir, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    ticker,
                    trade_date,
                    "running",
                    provider,
                    quick_model,
                    deep_model,
                    json.dumps(json_safe(analysts), ensure_ascii=False),
                    json.dumps(json_safe(payload), ensure_ascii=False),
                    now,
                    str(artifact_dir),
                    now,
                    now,
                ),
            )
        return artifact_dir

    def save_report(
        self,
        *,
        run_id: str,
        field: str,
        agent: str,
        content: str,
    ) -> Path:
        if field not in _REPORT_FIELDS:
            raise ValueError(f"unknown report field: {field}")
        now = utc_now_iso()
        report_dir = self.artifact_dir(run_id) / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"{field}.md"
        path.write_text(str(content), encoding="utf-8")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis_reports (run_id, field, agent, path, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, field) DO UPDATE SET
                    agent = excluded.agent,
                    path = excluded.path,
                    updated_at = excluded.updated_at
                """,
                (run_id, field, agent, str(path), now),
            )
            conn.execute(
                "UPDATE analysis_runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
        return path

    def complete_run(
        self,
        *,
        run_id: str,
        decision: str,
        stats: dict[str, Any],
        final_state: dict[str, Any] | None,
        duration_ms: int | None = None,
    ) -> Path | None:
        now = utc_now_iso()
        final_state_path = None
        if final_state is not None:
            final_state_path = self.artifact_dir(run_id) / "final_state.json"
            final_state_path.write_text(_dump_json(final_state), encoding="utf-8")

        stats_path = self.artifact_dir(run_id) / "stats.json"
        stats_path.write_text(_dump_json(stats), encoding="utf-8")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_runs
                SET status = 'completed',
                    decision = ?,
                    completed_at = ?,
                    duration_ms = ?,
                    tokens_in = ?,
                    tokens_out = ?,
                    llm_calls = ?,
                    tool_calls = ?,
                    final_state_path = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    decision,
                    now,
                    duration_ms,
                    int(stats.get("tokens_in") or 0),
                    int(stats.get("tokens_out") or 0),
                    int(stats.get("llm_calls") or 0),
                    int(stats.get("tool_calls") or 0),
                    str(final_state_path) if final_state_path else None,
                    now,
                    run_id,
                ),
            )
        return final_state_path

    def fail_run(self, *, run_id: str, error: str, status: str = "failed") -> None:
        if status not in {"failed", "cancelled"}:
            raise ValueError(f"invalid terminal status: {status}")
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_runs
                SET status = ?, error = ?, completed_at = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (status, error, now, now, run_id),
            )

    def list_runs(
        self,
        *,
        limit: int = 50,
        ticker: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        where: list[str] = []
        params: list[Any] = []
        if ticker:
            where.append("ticker = ?")
            params.append(ticker.upper())
        if status:
            where.append("status = ?")
            params.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = f"""
            SELECT * FROM analysis_runs
            {clause}
            ORDER BY COALESCE(completed_at, started_at, created_at) DESC
            LIMIT ?
        """
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_reports(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT field, agent, path, updated_at
                FROM analysis_reports
                WHERE run_id = ?
                ORDER BY updated_at ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_report(self, run_id: str, field: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT path FROM analysis_reports
                WHERE run_id = ? AND field = ?
                """,
                (run_id, field),
            ).fetchone()
        if row is None:
            return None
        path = Path(row["path"])
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def delete_run(self, run_id: str) -> bool:
        artifact_dir = self.artifact_dir(run_id)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_runs WHERE run_id = ?",
                (run_id,),
            )
        if artifact_dir.exists():
            for path in sorted(artifact_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            artifact_dir.rmdir()
        return cursor.rowcount > 0

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["analysts"] = _load_json(data.pop("analysts_json", None), [])
        data["payload"] = _load_json(data.pop("payload_json", None), {})
        return data
