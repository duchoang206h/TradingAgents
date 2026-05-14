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
}

CRYPTO_QUOTES = {"USD", "USDT", "USDC", "BTC", "ETH", "EUR"}


def split_crypto_symbol(symbol: str) -> tuple[str, str | None]:
    """Return ``(base, quote)`` for common crypto symbols.

    Bare symbols like ``BTC`` return ``("BTC", None)``; pair symbols like
    ``BTC-USD`` and ``ETH/USDT`` return the parsed quote when both sides are
    recognised as a common crypto asset or quote currency.
    """
    cleaned = symbol.strip().upper().replace("/", "-")
    if "-" in cleaned:
        base, quote = cleaned.split("-", 1)
        if base in COMMON_CRYPTO_BASES and quote in CRYPTO_QUOTES:
            return base, quote
        return cleaned, None
    if cleaned in COMMON_CRYPTO_BASES:
        return cleaned, None
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
        return f"{base}-{quote}"
    if base in COMMON_CRYPTO_BASES:
        return f"{base}-{quote_currency.strip().upper()}"
    return cleaned


def crypto_base_symbol(symbol: str) -> str:
    """Return the base asset for a common crypto symbol."""
    return split_crypto_symbol(symbol)[0]
