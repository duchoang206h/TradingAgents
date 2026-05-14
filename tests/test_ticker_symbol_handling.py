import unittest

import pytest

from cli.utils import normalize_ticker_symbol
from tradingagents.agents.utils.agent_utils import build_instrument_context


@pytest.mark.unit
class TickerSymbolHandlingTests(unittest.TestCase):
    def test_normalize_ticker_symbol_preserves_exchange_suffix(self):
        self.assertEqual(normalize_ticker_symbol(" cnc.to "), "CNC.TO")

    def test_normalize_ticker_symbol_expands_common_crypto(self):
        self.assertEqual(normalize_ticker_symbol(" btc "), "BTC-USD")
        self.assertEqual(normalize_ticker_symbol("eth/usdt"), "ETH-USDT")

    def test_build_instrument_context_mentions_exact_symbol(self):
        context = build_instrument_context("7203.T")
        self.assertIn("7203.T", context)
        self.assertIn("exchange suffix", context)

    def test_build_instrument_context_is_crypto_aware(self):
        context = build_instrument_context("SOL-USD")
        self.assertIn("crypto asset", context)
        self.assertIn("not a company", context)


if __name__ == "__main__":
    unittest.main()
