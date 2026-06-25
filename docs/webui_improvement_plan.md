# WebUI Improvement Plan

## Goal

Turn the WebUI into a clear three-state decision workspace:

1. **Configure** an analysis with sensible defaults and optional advanced settings.
2. **Monitor** authoritative pipeline progress with useful recovery controls.
3. **Decide** from a concise recommendation and supporting evidence before reading raw reports.

The implementation should preserve the current FastAPI server, static frontend,
model catalog, SSE streaming, theme tokens, and incremental report delivery.

## Design Direction

- Product type: financial analysis dashboard
- Pattern: data-dense workspace with progressive disclosure
- Visual tone: professional, technical, and trustworthy
- Primary action: run an analysis
- Primary result: final decision with thesis, evidence, risks, and run metadata
- Supporting result: complete agent reports

## Phase 1: Foundation

### Responsive layout

- Stack configuration and results below desktop widths.
- Make the configuration panel collapsible on smaller screens.
- Prevent report tables, pipeline stages, and long content from causing page overflow.
- Verify at 375px, 768px, 1024px, and 1440px widths.

### Forms and accessibility

- Add inline validation for ticker, date, analyst selection, models, and round counts.
- Reject future analysis dates before starting a run.
- Replace blocking `alert()` dialogs with inline errors and non-blocking notices.
- Add semantic labels, field descriptions, visible keyboard focus, and `aria-live`
  status regions.
- Implement accessible report tabs with keyboard navigation.
- Respect `prefers-reduced-motion`.

### Security and reliability

- Sanitize generated Markdown before inserting it into the page.
- Handle failed HTTP responses and malformed API payloads.
- Keep the UI usable when model catalog loading fails.
- Track stream connection errors and provide retry guidance.

## Phase 2: Configuration and Monitoring

### Simplified configuration

- Add Quick, Standard, and Deep research presets.
- Keep provider, model, language, checkpoint, and round controls in Advanced settings.
- Persist the last successful configuration locally.
- Show a concise run summary before analysis starts.

### Authoritative execution state

- Emit backend stage events with `queued`, `running`, `done`, `error`, and `skipped`
  states.
- Stop inferring pipeline progress from report arrival in the frontend.
- Keep activity details available after completion.
- Add cancel and retry controls.
- Display elapsed time and run statistics consistently.

## Phase 3: Decision-First Results

- Put the final decision above raw agent reports.
- Present the recommendation, ticker, date, runtime, LLM calls, tool calls, and
  token usage as structured information.
- Extract and display a concise decision summary from the final report.
- Keep complete agent reports in supporting tabs.
- Add report copy and Markdown export actions.
- Improve long-report readability with constrained text width, sticky report
  controls, scrollable tables, and report search.

## Phase 4: History and Comparison

- Store and display recent runs.
- Allow users to rerun a saved configuration.
- Compare decisions for the same ticker across dates.
- Add charts only when structured financial data is available.

## Acceptance Criteria

- No horizontal page overflow at 375px, 768px, 1024px, or 1440px.
- The complete workflow is usable by keyboard.
- Text and controls meet WCAG AA contrast.
- Pipeline state reflects backend execution rather than frontend guesses.
- Validation and runtime errors appear near the relevant workflow and include a
  recovery action.
- Model-generated Markdown cannot inject executable HTML.
- Risk discussion rounds are sent and applied independently from debate rounds.
- Users can cancel an active run and retry a failed run.

## Implementation Status

- [x] Responsive workspace and mobile configuration drawer
- [x] Accessible validation, notices, tabs, and focus states
- [x] Sanitized report rendering
- [x] Research presets and persisted configuration
- [x] Independent debate and risk round controls
- [x] Backend stage events
- [x] Cancel and retry controls
- [x] Decision-first result card
- [x] Report copy, export, and search
- [x] Focused WebUI tests
- [x] Recent run history and comparison
