import pytest
from urllib.error import HTTPError

from tradingagents.dataflows import reddit, stocktwits


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


@pytest.mark.unit
def test_stocktwits_uses_crypto_stream_symbol(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return _FakeResponse(b'{"messages": []}')

    monkeypatch.setattr(stocktwits, "urlopen", fake_urlopen)

    result = stocktwits.fetch_stocktwits_messages("HYPE32196-USD", timeout=0.1)

    assert captured["url"].endswith("/HYPE.X.json")
    assert "$HYPE.X" in result


@pytest.mark.unit
def test_reddit_uses_canonical_crypto_query(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return _FakeResponse(b'{"data": {"children": []}}')

    monkeypatch.setattr(reddit, "urlopen", fake_urlopen)

    result = reddit.fetch_reddit_posts(
        "HYPE32196-USD",
        subreddits=("stocks",),
        timeout=0.1,
        inter_request_delay=0,
    )

    assert "q=HYPE" in captured["url"]
    assert "HYPE32196-USD" not in captured["url"]
    assert "mentioning HYPE" in result


@pytest.mark.unit
def test_reddit_403_stops_after_single_placeholder(monkeypatch):
    calls = []

    monkeypatch.delenv("TRADINGAGENTS_REDDIT_BACKEND", raising=False)

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        raise HTTPError(req.full_url, 403, "Blocked", hdrs=None, fp=None)

    monkeypatch.setattr(reddit, "urlopen", fake_urlopen)

    result = reddit.fetch_reddit_posts(
        "HYPE32196-USD",
        subreddits=("wallstreetbets", "stocks", "investing"),
        timeout=0.1,
        inter_request_delay=0,
    )

    assert len(calls) == 1
    assert result == (
        "<reddit unavailable: HTTP 403 blocked unauthenticated public access for HYPE>"
    )


@pytest.mark.unit
def test_reddit_403_uses_browser_fallback_when_enabled(monkeypatch):
    calls = []
    fallback_calls = []

    monkeypatch.setenv("TRADINGAGENTS_REDDIT_BACKEND", "browser")

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        raise HTTPError(req.full_url, 403, "Blocked", hdrs=None, fp=None)

    def fake_browser_fallback(ticker, subreddits, limit_per_sub, timeout):
        fallback_calls.append((ticker, tuple(subreddits), limit_per_sub, timeout))
        return "browser fallback result"

    monkeypatch.setattr(reddit, "urlopen", fake_urlopen)
    monkeypatch.setattr(reddit, "_fetch_reddit_posts_browser", fake_browser_fallback)

    result = reddit.fetch_reddit_posts(
        "HYPE32196-USD",
        subreddits=("wallstreetbets", "stocks", "investing"),
        limit_per_sub=2,
        timeout=0.1,
        inter_request_delay=0,
    )

    assert len(calls) == 1
    assert fallback_calls == [
        ("HYPE32196-USD", ("wallstreetbets", "stocks", "investing"), 2, 0.1)
    ]
    assert result == "browser fallback result"


@pytest.mark.unit
def test_browser_fallback_uses_hype_crypto_subreddits_for_default_list():
    assert reddit._browser_subreddits("HYPE", reddit.DEFAULT_SUBREDDITS) == (
        "CryptoCurrency",
        "CryptoMarkets",
        "hyperliquid1",
    )
    assert reddit._browser_subreddits("HYPE", ("stocks",)) == ("stocks",)
