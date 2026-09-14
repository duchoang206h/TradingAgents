"""Helpers for crypto symbols supported through exchange-qualified tickers."""

from __future__ import annotations

COMMON_CRYPTO_BASES = {
    "AAVE",
    "ADA",
    "AVAX",
    "BCH",
    "BNB",
    "BTC",
    "DOGE",
    "DOT",
    "ETC",
    "ETH",
    "FIL",
    "HBAR",
    "ICP",
    "LINK",
    "LTC",
    "MATIC",
    "NEAR",
    "OP",
    "PEPE",
    "SHIB",
    "SOL",
    "SUI",
    "TON",
    "TRX",
    "UNI",
    "USDC",
    "USDT",
    "XLM",
    "XRP",
    "HYPE",
}

CRYPTO_QUOTES = {"USD", "USDT", "USDC", "BTC", "ETH", "EUR"}

# Some crypto assets need provider-specific Yahoo Finance bases that do not
# match the canonical market ticker. Keep prompts and crypto lookups canonical,
# but route OHLCV/fundamentals calls to Yahoo's actual symbol.
YFINANCE_CRYPTO_BASE_ALIASES = {
    "HYPE": "HYPE32196",
}
YFINANCE_CRYPTO_ALIAS_TO_BASE = {
    provider_base: canonical_base
    for canonical_base, provider_base in YFINANCE_CRYPTO_BASE_ALIASES.items()
}


def _canonical_crypto_base(base: str) -> str:
    return YFINANCE_CRYPTO_ALIAS_TO_BASE.get(base, base)


def _provider_crypto_base(base: str, quote: str) -> str:
    if quote == "USD":
        return YFINANCE_CRYPTO_BASE_ALIASES.get(base, base)
    return base


def split_crypto_symbol(symbol: str) -> tuple[str, str | None]:
    """Return ``(base, quote)`` for common crypto symbols.

    Bare symbols like ``BTC`` return ``("BTC", None)``; pair symbols like
    ``BTC-USD`` and ``ETH/USDT`` return the parsed quote when both sides are
    recognised as a common crypto asset or quote currency.
    """
    cleaned = symbol.strip().upper().replace("/", "-")
    if "-" in cleaned:
        raw_base, quote = cleaned.split("-", 1)
        base = _canonical_crypto_base(raw_base)
        if base in COMMON_CRYPTO_BASES and quote in CRYPTO_QUOTES:
            return base, quote
        return cleaned, None
    base = _canonical_crypto_base(cleaned)
    if base in COMMON_CRYPTO_BASES:
        return base, None
    return cleaned, None


def is_crypto_symbol(symbol: str) -> bool:
    """Return True when ``symbol`` is a common crypto asset or pair."""
    base, quote = split_crypto_symbol(symbol)
    return base in COMMON_CRYPTO_BASES and (quote is None or quote in CRYPTO_QUOTES)


def normalize_crypto_symbol(symbol: str, quote_currency: str = "USD") -> str:
    """Normalize common bare crypto tickers to Yahoo-style quote pairs."""
    cleaned = symbol.strip().upper().replace("/", "-")
    base, quote = split_crypto_symbol(cleaned)
    if quote:
        return f"{_provider_crypto_base(base, quote)}-{quote}"
    if base in COMMON_CRYPTO_BASES:
        quote = quote_currency.strip().upper()
        return f"{_provider_crypto_base(base, quote)}-{quote}"
    return cleaned


def social_crypto_symbol(symbol: str) -> str:
    """Return the canonical symbol to use in text/social searches."""
    if is_crypto_symbol(symbol):
        return crypto_base_symbol(symbol)
    return symbol.strip().upper()


def stocktwits_symbol(symbol: str) -> str:
    """Return the symbol format expected by StockTwits streams."""
    if is_crypto_symbol(symbol):
        return f"{crypto_base_symbol(symbol)}.X"
    return symbol.strip().upper()


def crypto_base_symbol(symbol: str) -> str:
    """Return the base asset for a common crypto symbol."""
    return split_crypto_symbol(symbol)[0]
