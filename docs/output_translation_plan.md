# Post-Processing Output Translation Plan

## Goal

Support multilingual user-facing output, starting with Vietnamese, without
changing the existing agent system prompts or allowing translation to affect
agent reasoning, tool calls, graph state, signal extraction, or memory.

## Architecture

```text
Agents generate canonical English output
        |
        v
Graph processes, logs, and stores canonical English
        |
        v
OutputTranslator creates localized presentation copies
        |
        v
Python return values / WebUI stream / CLI display / saved reports
```

The requested `output_language` is a presentation setting. Agent execution is
always configured with English output. The translator uses the graph's quick
thinking LLM after an agent has completed its work.

## Invariants

- Do not edit or append localization instructions to existing agent prompts.
- Keep internal graph state and `TradingMemoryLog` content in English.
- Extract the canonical signal from the original English final decision.
- Preserve tickers, numbers, currencies, URLs, Markdown, code, and tool names.
- Preserve canonical rating values exactly:
  `Buy`, `Overweight`, `Hold`, `Underweight`, and `Sell`.
- Translation failure must fall back to the original English output.
- English output must remain a zero-call, backward-compatible path.

## Translation Surface

Translate presentation copies of:

- Analyst reports
- Research Manager investment plan
- Trader investment plan
- Portfolio Manager final decision
- Bull/bear debate histories shown in reports
- Risk debate histories shown in reports

Do not translate:

- LangGraph messages used by downstream agents
- Tool calls or tool results
- Checkpoints and full-state logs
- Trading memory and reflections
- Canonical signal returned by `process_signal`

## Implementation Phases

### Phase 1: Reusable translator and graph integration

- Add `OutputTranslator` with English no-op behavior, response caching, and
  graceful fallback.
- Force agent-facing `output_language` to English inside `TradingAgentsGraph`.
- Localize copies returned by `propagate()` and streamed by
  `propagate_stream()`.
- Keep `curr_state`, logs, memory, and signal processing canonical English.

### Phase 2: CLI and WebUI integration

- Add Vietnamese as a first-class language option.
- Localize CLI report chunks before live display and report-file writes.
- Save and display the localized final state while retaining the original
  internal state.
- Stream localized report fields to the WebUI.

### Phase 3: Verification

- Test English no-op behavior.
- Test Vietnamese translation prompts and protected canonical terms.
- Test translated state copies do not mutate original state.
- Test graph configuration prevents requested languages from reaching agents.
- Test WebUI/stream behavior continues to preserve canonical internal state.

## Future Improvements

- Add deterministic translation providers for lower cost.
- Add translation cache persistence keyed by content hash and locale.
- Expose original and localized report variants in the WebUI.
- Add per-language terminology glossaries and translation quality evaluation.
- Translate static CLI/WebUI interface labels separately from report output.
