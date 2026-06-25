import unittest

import pytest

from cli.utils import normalize_ticker_symbol
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.dataflows.crypto_utils import (
    crypto_base_symbol,
    is_crypto_symbol,
    social_crypto_symbol,
    stocktwits_symbol,
)


@pytest.mark.unit
class TickerSymbolHandlingTests(unittest.TestCase):
    def test_normalize_ticker_symbol_preserves_exchange_suffix(self):
        self.assertEqual(normalize_ticker_symbol(" cnc.to "), "CNC.TO")

    def test_normalize_ticker_symbol_expands_common_crypto(self):
        self.assertEqual(normalize_ticker_symbol(" btc "), "BTC-USD")
        self.assertEqual(normalize_ticker_symbol("eth/usdt"), "ETH-USDT")

    def test_normalize_ticker_symbol_uses_hyperliquid_yahoo_symbol(self):
        self.assertEqual(normalize_ticker_symbol(" hype "), "HYPE32196-USD")
        self.assertEqual(normalize_ticker_symbol("hype-usd"), "HYPE32196-USD")

    def test_build_instrument_context_mentions_exact_symbol(self):
        context = build_instrument_context("7203.T")
        self.assertIn("7203.T", context)
        self.assertIn("exchange suffix", context)

    def test_build_instrument_context_is_crypto_aware(self):
        context = build_instrument_context("SOL-USD")
        self.assertIn("crypto asset", context)
        self.assertIn("not a company", context)

    def test_hyperliquid_yahoo_symbol_remains_crypto_aware(self):
        self.assertTrue(is_crypto_symbol("HYPE32196-USD"))
        self.assertEqual(crypto_base_symbol("HYPE32196-USD"), "HYPE")
        context = build_instrument_context("HYPE32196-USD")
        self.assertIn("crypto asset", context)
        self.assertIn("base asset `HYPE`", context)

    def test_social_sources_use_canonical_crypto_symbols(self):
        self.assertEqual(social_crypto_symbol("HYPE32196-USD"), "HYPE")
        self.assertEqual(stocktwits_symbol("HYPE32196-USD"), "HYPE.X")
        self.assertEqual(social_crypto_symbol("NVDA"), "NVDA")
        self.assertEqual(stocktwits_symbol("NVDA"), "NVDA")


if __name__ == "__main__":
    unittest.main()
