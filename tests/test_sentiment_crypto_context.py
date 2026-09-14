from unittest.mock import MagicMock

import pytest
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts import sentiment_analyst


@pytest.mark.unit
def test_build_system_message_includes_coingecko_context_when_provided():
    message = sentiment_analyst._build_system_message(
        ticker="BTC-USD",
        start_date="2026-05-08",
        end_date="2026-05-15",
        news_block="news",
        stocktwits_block="stocktwits",
        reddit_block="reddit",
        crypto_context_block="CoinGecko crypto context for Bitcoin (BTC)",
    )

    assert "### CoinGecko crypto context" in message
    assert "<start_of_coingecko>" in message
    assert "CoinGecko crypto context for Bitcoin (BTC)" in message
    assert "use CoinGecko as context" in message


@pytest.mark.unit
def test_build_system_message_omits_coingecko_section_for_equities():
    message = sentiment_analyst._build_system_message(
        ticker="NVDA",
        start_date="2026-05-08",
        end_date="2026-05-15",
        news_block="news",
        stocktwits_block="stocktwits",
        reddit_block="reddit",
    )

    assert "<start_of_coingecko>" not in message


@pytest.mark.unit
def test_sentiment_node_fetches_coingecko_only_for_crypto(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sentiment_analyst.get_news,
        "func",
        lambda ticker, start, end: "news",
    )
    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_stocktwits_messages",
        lambda ticker, limit=30: "stocktwits",
    )
    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_reddit_posts",
        lambda ticker: "reddit",
    )

    def fake_coingecko(ticker):
        calls.append(ticker)
        return "CoinGecko crypto context for Bitcoin (BTC)"

    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_coingecko_crypto_context",
        fake_coingecko,
    )

    response = MagicMock(content="sentiment report")
    node = sentiment_analyst.create_sentiment_analyst(RunnableLambda(lambda _: response))
    result = node(
        {
            "company_of_interest": "BTC-USD",
            "trade_date": "2026-05-15",
            "messages": [],
        }
    )

    assert calls == ["BTC-USD"]
    assert result["sentiment_report"] == "sentiment report"


@pytest.mark.unit
def test_sentiment_node_skips_coingecko_for_equities(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sentiment_analyst.get_news,
        "func",
        lambda ticker, start, end: "news",
    )
    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_stocktwits_messages",
        lambda ticker, limit=30: "stocktwits",
    )
    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_reddit_posts",
        lambda ticker: "reddit",
    )
    monkeypatch.setattr(
        sentiment_analyst,
        "fetch_coingecko_crypto_context",
        lambda ticker: calls.append(ticker) or "coingecko",
    )

    response = MagicMock(content="sentiment report")
    node = sentiment_analyst.create_sentiment_analyst(RunnableLambda(lambda _: response))
    node(
        {
            "company_of_interest": "NVDA",
            "trade_date": "2026-05-15",
            "messages": [],
        }
    )

    assert calls == []
