# Repository Guidelines

## Project Structure & Module Organization

`tradingagents/` contains the core package. Key areas are `agents/` for analyst, researcher, trader, manager, and risk roles; `dataflows/` for market/news/fundamental data adapters; `graph/` for LangGraph orchestration, checkpointing, and signal processing; and `llm_clients/` for provider-specific model clients and validation. `cli/` implements the Typer/Rich command-line interface, while `webui/` provides the FastAPI server and static browser UI. Tests live in `tests/`, smoke utilities in `scripts/`, and README images/assets in `assets/`. `main.py` is a small programmatic usage example.

## Build, Test, and Development Commands

Install locally after creating a Python 3.10+ environment:

```bash
pip install -e .
```

Run the interactive CLI:

```bash
tradingagents
python -m cli.main
```

Run the WebUI from source:

```bash
python -m webui
```

Run tests:

```bash
pytest
pytest -m unit
pytest tests/test_signal_processing.py
```

Use Docker when you want an isolated runtime:

```bash
cp .env.example .env
docker compose run --rm tradingagents
docker compose --profile ollama run --rm tradingagents-ollama
```

## Coding Style & Naming Conventions

Use standard Python style with 4-space indentation, type hints where they clarify public interfaces, and concise docstrings for modules/classes with non-obvious behavior. Follow existing names: `snake_case` for functions, modules, and fields; `PascalCase` for classes; provider-specific files such as `openai_client.py` and `google_client.py`; tests named `test_<behavior>.py`. Prefer adding provider behavior through `tradingagents/llm_clients/` and shared graph logic through `tradingagents/graph/` rather than duplicating code in CLI or WebUI layers.

## Testing Guidelines

Pytest is configured in `pyproject.toml` with `tests/` as the test root, strict markers, and markers for `unit`, `integration`, and `smoke`. Add or update focused tests near the changed behavior. For external-service behavior, mock provider clients or mark the test `integration` so routine local runs stay fast and deterministic.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit style, for example `feat(cli): ...`, `fix: ...`, `docs(readme): ...`, `refactor: ...`, and `chore: ...`. Keep subject lines imperative and scoped when useful. Pull requests should describe the user-facing change, list test commands run, call out API key or environment impacts, and include screenshots for CLI/WebUI visual changes.

## Security & Configuration Tips

Do not commit `.env` or secrets. Start from `.env.example` or `.env.enterprise.example`, and document new environment variables there. Runtime caches, memory logs, and checkpoint databases are stored under `~/.tradingagents/`; use `TRADINGAGENTS_CACHE_DIR` when tests or demos need isolated state.
