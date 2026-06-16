"""CoinGecko crypto context fetcher.

The sentiment analyst uses this as a crypto-native context source. It is not
pure social sentiment; it captures market attention, liquidity, and broad
community/market signals that complement news, StockTwits, and Reddit.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from tradingagents.dataflows.crypto_utils import crypto_base_symbol

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.coingecko.com/api/v3"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

_COMMON_COIN_IDS = {
    "AAVE": "aave",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "BCH": "bitcoin-cash",
    "BNB": "binancecoin",
    "BTC": "bitcoin",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "ETC": "ethereum-classic",
    "ETH": "ethereum",
    "FIL": "filecoin",
    "HBAR": "hedera-hashgraph",
    "HYPE": "hyperliquid",
    "ICP": "internet-computer",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "MATIC": "matic-network",
    "NEAR": "near",
    "OP": "optimism",
    "PEPE": "pepe",
    "SHIB": "shiba-inu",
    "SOL": "solana",
    "SUI": "sui",
    "TON": "the-open-network",
    "TRX": "tron",
    "UNI": "uniswap",
    "USDC": "usd-coin",
    "USDT": "tether",
    "XLM": "stellar",
    "XRP": "ripple",
}


def _fetch_json(url: str, timeout: float) -> Any:
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _safe_get(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _fmt_num(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if abs(num) >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B{suffix}"
    if abs(num) >= 1_000_000:
        return f"{num / 1_000_000:.2f}M{suffix}"
    if abs(num) >= 1_000:
        return f"{num / 1_000:.2f}K{suffix}"
    return f"{num:.2f}{suffix}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_share(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _resolve_coin_id(symbol: str, timeout: float) -> str | None:
    base = crypto_base_symbol(symbol).upper()
    if base in _COMMON_COIN_IDS:
        return _COMMON_COIN_IDS[base]

    try:
        payload = _fetch_json(f"{_BASE_URL}/search?query={quote(base)}", timeout)
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("CoinGecko search failed for %s: %s", symbol, exc)
        return None

    coins = payload.get("coins", []) if isinstance(payload, dict) else []
    for coin in coins:
        if (coin.get("symbol") or "").upper() == base:
            return coin.get("id")
    return None


def _trending_rank(trending_payload: Any, coin_id: str) -> str:
    coins = trending_payload.get("coins", []) if isinstance(trending_payload, dict) else []
    for idx, item in enumerate(coins, start=1):
        item_data = item.get("item") if isinstance(item, dict) else {}
        if isinstance(item_data, dict) and item_data.get("id") == coin_id:
            return str(idx)
    return "not in top trending search results"


def _format_crypto_context(
    symbol: str,
    coin_payload: dict[str, Any],
    trending_payload: dict[str, Any],
) -> str:
    market = coin_payload.get("market_data") or {}
    community = coin_payload.get("community_data") or {}
    links = coin_payload.get("links") or {}
    coin_id = coin_payload.get("id", "unknown")
    name = coin_payload.get("name", symbol.upper())
    symbol_text = (coin_payload.get("symbol") or symbol).upper()
    categories = coin_payload.get("categories") or []
    homepage = (links.get("homepage") or [""])[0] if isinstance(links, dict) else ""

    return "\n".join(
        [
            f"CoinGecko crypto context for {name} ({symbol_text})",
            f"CoinGecko ID: {coin_id}",
            f"Market cap rank: {coin_payload.get('market_cap_rank') or 'n/a'}",
            f"Current price USD: {_fmt_num(_safe_get(market, 'current_price', 'usd'))}",
            f"24h price change: {_fmt_pct(market.get('price_change_percentage_24h'))}",
            f"7d price change: {_fmt_pct(market.get('price_change_percentage_7d'))}",
            f"24h total volume USD: {_fmt_num(_safe_get(market, 'total_volume', 'usd'))}",
            f"Market cap USD: {_fmt_num(_safe_get(market, 'market_cap', 'usd'))}",
            f"CoinGecko trending search rank: {_trending_rank(trending_payload, coin_id)}",
            f"Sentiment votes up/down: {_fmt_share(coin_payload.get('sentiment_votes_up_percentage'))} / {_fmt_share(coin_payload.get('sentiment_votes_down_percentage'))}",
            f"Community: Twitter followers {_fmt_num(community.get('twitter_followers'))}, Reddit subscribers {_fmt_num(community.get('reddit_subscribers'))}",
            "Categories: " + (", ".join(categories[:5]) if categories else "n/a"),
            f"Homepage: {homepage or 'n/a'}",
        ]
    )


def fetch_coingecko_crypto_context(symbol: str, timeout: float = 10.0) -> str:
    """Return a formatted CoinGecko context block for a crypto symbol.

    The function degrades to a placeholder string on lookup, network, or parse
    failures so agent prompts can include the limitation without crashing a run.
    """
    coin_id = _resolve_coin_id(symbol, timeout)
    if not coin_id:
        return f"<coingecko unavailable: no coin id found for {symbol.upper()}>"

    try:
        coin_payload = _fetch_json(
            f"{_BASE_URL}/coins/{quote(coin_id)}"
            "?localization=false&tickers=false&market_data=true"
            "&community_data=true&developer_data=false&sparkline=false",
            timeout,
        )
        trending_payload = _fetch_json(f"{_BASE_URL}/search/trending", timeout)
    except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("CoinGecko fetch failed for %s (%s): %s", symbol, coin_id, exc)
        return f"<coingecko unavailable: {type(exc).__name__}>"

    if not isinstance(coin_payload, dict):
        return f"<coingecko unavailable: unexpected response for {symbol.upper()}>"
    return _format_crypto_context(symbol, coin_payload, trending_payload)
