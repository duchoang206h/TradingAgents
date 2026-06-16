import pytest

from tradingagents.dataflows import coingecko


@pytest.mark.unit
def test_format_crypto_context_includes_market_attention_fields():
    coin_payload = {
        "id": "bitcoin",
        "name": "Bitcoin",
        "symbol": "btc",
        "market_cap_rank": 1,
        "sentiment_votes_up_percentage": 76.2,
        "sentiment_votes_down_percentage": 23.8,
        "categories": ["Cryptocurrency", "Layer 1"],
        "links": {"homepage": ["https://bitcoin.org"]},
        "market_data": {
            "current_price": {"usd": 100000},
            "price_change_percentage_24h": 2.5,
            "price_change_percentage_7d": -4.25,
            "total_volume": {"usd": 42_000_000_000},
            "market_cap": {"usd": 1_900_000_000_000},
        },
        "community_data": {
            "twitter_followers": 7_000_000,
            "reddit_subscribers": 6_800_000,
        },
    }
    trending_payload = {
        "coins": [
            {"item": {"id": "ethereum"}},
            {"item": {"id": "bitcoin"}},
        ]
    }

    block = coingecko._format_crypto_context("BTC-USD", coin_payload, trending_payload)

    assert "CoinGecko crypto context for Bitcoin (BTC)" in block
    assert "Market cap rank: 1" in block
    assert "24h price change: +2.50%" in block
    assert "7d price change: -4.25%" in block
    assert "CoinGecko trending search rank: 2" in block
    assert "Sentiment votes up/down: 76.20% / 23.80%" in block


@pytest.mark.unit
def test_resolve_coin_id_uses_common_crypto_map_without_network(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("network should not be called for common symbols")

    monkeypatch.setattr(coingecko, "_fetch_json", fail_fetch)

    assert coingecko._resolve_coin_id("ETH-USD", timeout=0.1) == "ethereum"
    assert coingecko._resolve_coin_id("HYPE32196-USD", timeout=0.1) == "hyperliquid"


@pytest.mark.unit
def test_fetch_coingecko_crypto_context_degrades_when_coin_id_missing(monkeypatch):
    monkeypatch.setattr(coingecko, "_resolve_coin_id", lambda symbol, timeout: None)

    assert (
        coingecko.fetch_coingecko_crypto_context("UNKNOWN")
        == "<coingecko unavailable: no coin id found for UNKNOWN>"
    )
