"""Presentation-only translation for completed agent output.

The trading graph reasons, logs, remembers, and extracts signals from canonical
English output. This module creates localized copies only for callers and user
interfaces, so translation cannot alter trading behavior.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from tradingagents.llm_clients.base_client import normalize_content

logger = logging.getLogger(__name__)


_TOP_LEVEL_FIELDS = (
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)

_NESTED_FIELDS = {
    "investment_debate_state": (
        "bull_history",
        "bear_history",
        "judge_decision",
    ),
    "risk_debate_state": (
        "aggressive_history",
        "conservative_history",
        "neutral_history",
        "judge_decision",
    ),
}

_LANGUAGE_ALIASES = {
    "en": "English",
    "en-us": "English",
    "english": "English",
    "vi": "Vietnamese",
    "vi-vn": "Vietnamese",
    "vietnamese": "Vietnamese",
    "tiếng việt": "Vietnamese",
}


def normalize_output_language(language: str | None) -> str:
    """Return a stable display name while accepting common locale aliases."""
    cleaned = (language or "English").strip()
    if not cleaned:
        return "English"
    return _LANGUAGE_ALIASES.get(cleaned.lower(), cleaned)


class OutputTranslator:
    """Translate report copies without mutating canonical graph output."""

    def __init__(self, llm: Any, language: str | None = "English"):
        self.llm = llm
        self.language = normalize_output_language(language)
        self._cache: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return self.language.lower() != "english"

    def translate_text(self, text: str) -> str:
        """Translate one report fragment, returning English on any failure."""
        if not self.enabled or not text or not text.strip():
            return text
        if text in self._cache:
            return self._cache[text]

        messages = [
            (
                "system",
                (
                    f"Translate the user's financial report into {self.language}. "
                    "Return only the translated report. Preserve the original Markdown "
                    "structure, tickers, numbers, currencies, percentages, URLs, code, "
                    "technical indicator names, and proper nouns. Preserve these "
                    "canonical trading rating values exactly in English wherever they "
                    "appear: Buy, Overweight, Hold, Underweight, Sell. Do not add, "
                    "remove, summarize, reinterpret, or fact-check content."
                ),
            ),
            ("human", text),
        ]

        try:
            response = normalize_content(self.llm.invoke(messages))
            translated = response.content.strip()
            if translated:
                self._cache[text] = translated
                return translated
        except Exception as exc:
            logger.warning(
                "Output translation to %s failed; using canonical English output: %s",
                self.language,
                exc,
            )
        return text

    def translate_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Return a localized copy of user-facing graph-state fields."""
        if not self.enabled:
            return state

        localized = dict(state)
        for field in _TOP_LEVEL_FIELDS:
            value = localized.get(field)
            if isinstance(value, str):
                localized[field] = self.translate_text(value)

        for state_field, text_fields in _NESTED_FIELDS.items():
            nested = localized.get(state_field)
            if not isinstance(nested, dict):
                continue
            localized_nested = dict(nested)
            localized[state_field] = localized_nested
            for text_field in text_fields:
                value = localized_nested.get(text_field)
                if isinstance(value, str):
                    localized_nested[text_field] = self.translate_text(value)

        return localized
