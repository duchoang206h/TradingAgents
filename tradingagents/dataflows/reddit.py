"""Reddit search fetcher for ticker-specific discussion posts.

Uses Reddit's public JSON endpoints (``reddit.com/r/{sub}/search.json``)
which do not require an API key. Public throughput is ~10 requests per
minute per IP, well within budget for a single agent run that queries
a handful of finance subreddits per ticker.

Returns formatted plaintext blocks ready for prompt injection. Degrades
gracefully — returns a placeholder string rather than raising, so callers
never have to special-case missing data.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from typing import Iterable
from urllib.error import HTTPError, URLError
from pathlib import Path
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from tradingagents.dataflows.crypto_utils import social_crypto_symbol

logger = logging.getLogger(__name__)

_API = "https://www.reddit.com/r/{sub}/search.json?{qs}"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# Default subreddits ordered roughly by signal density for ticker-specific
# discussion. wallstreetbets has the most volume but most noise; stocks /
# investing trend more measured. Caller can override.
DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")
_BROWSER_BACKEND_VALUES = {"browser", "cloakbrowser", "auto"}
_BROWSER_PROFILE_DIR = Path.home() / ".tradingagents" / "reddit-cloakbrowser-profile"
_BROWSER_SUBREDDITS_BY_SYMBOL = {
    "HYPE": ("CryptoCurrency", "CryptoMarkets", "hyperliquid1"),
}
_SEARCH_PROFILES_BY_SYMBOL = {
    "HYPE": {
        "search_query": '"$HYPE" OR Hyperliquid',
        "match_terms": ("$HYPE", "HYPE.X", "Hyperliquid"),
    },
}


class _RedditAccessBlocked(Exception):
    """Reddit blocked unauthenticated public endpoint access."""


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _browser_fallback_enabled() -> bool:
    backend = os.environ.get("TRADINGAGENTS_REDDIT_BACKEND", "").strip().lower()
    return backend in _BROWSER_BACKEND_VALUES


def _search_profile(query_symbol: str) -> tuple[str, tuple[str, ...]]:
    profile = _SEARCH_PROFILES_BY_SYMBOL.get(query_symbol.upper())
    if profile:
        return profile["search_query"], tuple(profile["match_terms"])
    return query_symbol, (query_symbol,)


def _browser_subreddits(query_symbol: str, subreddits: Iterable[str]) -> tuple[str, ...]:
    selected = tuple(subreddits)
    if selected == DEFAULT_SUBREDDITS:
        return _BROWSER_SUBREDDITS_BY_SYMBOL.get(query_symbol.upper(), selected)
    return selected


def _blocked_reason(text: str) -> str | None:
    lower = text.lower()
    if "you've been blocked by network security" in lower:
        return "reddit network-security block"
    if "blocked by network security" in lower:
        return "reddit network-security block"
    if "http error 403" in lower or "403 forbidden" in lower:
        return "http 403"
    if "whoa there, pardner" in lower:
        return "reddit rate-limit/block page"
    return None


def _page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def _browser_goto(page, url: str, timeout_ms: int, settle_seconds: float) -> str:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        return f"navigation error: {type(exc).__name__}: {exc}"
    time.sleep(settle_seconds)
    return _blocked_reason(_page_text(page)) or ""


def _extract_browser_posts(
    page,
    limit: int,
    match_terms: tuple[str, ...],
) -> list[dict[str, str]]:
    return page.evaluate(
        """
        ({limit, matchTerms}) => {
          const posts = [];
          const seen = new Set();
          const terms = (matchTerms || []).map((term) => String(term).toLowerCase());

          function clean(value) {
            return (value || '').replace(/\\s+/g, ' ').trim();
          }

          function addPost(title, url, subreddit, score, comments, haystack) {
            title = clean(title);
            url = clean(url);
            if (!title || !url || seen.has(url)) return;
            const text = clean(haystack || title || url).toLowerCase();
            const urlText = url.toLowerCase();
            if (terms.length && !terms.some((term) => text.includes(term) || urlText.includes(term))) return;
            seen.add(url);
            posts.push({
              title,
              url,
              subreddit: clean(subreddit),
              score: clean(score),
              comments: clean(comments),
            });
          }

          document.querySelectorAll('shreddit-post').forEach((el) => {
            const link = el.querySelector('a[href*="/comments/"]');
            addPost(
              el.getAttribute('post-title') || (link && link.textContent),
              el.getAttribute('content-href') || (link && link.href),
              el.getAttribute('subreddit-prefixed-name'),
              el.getAttribute('score'),
              el.getAttribute('comment-count'),
              el.textContent
            );
          });

          document.querySelectorAll('a[href*="/comments/"]').forEach((link) => {
            addPost(
              link.getAttribute('aria-label') || link.textContent,
              link.href,
              '',
              '',
              '',
              link.textContent
            );
          });

          return posts.slice(0, limit);
        }
        """,
        {"limit": limit, "matchTerms": list(match_terms)},
    )


def _format_browser_blocks(
    query_symbol: str,
    subreddits: Iterable[str],
    posts_by_subreddit: dict[str, list[dict[str, str]]],
) -> str:
    blocks = ["### Reddit browser fallback (CloakBrowser)"]
    total_posts = 0
    for sub in subreddits:
        posts = posts_by_subreddit.get(sub, [])
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}: <no browser-search posts found mentioning {query_symbol} in the past 7 days>")
            continue

        lines = [f"r/{sub} — {len(posts)} browser-search posts mentioning {query_symbol}:"]
        for p in posts:
            meta = []
            if p.get("score"):
                meta.append(f"score {p['score']}")
            if p.get("comments"):
                meta.append(f"{p['comments']} comments")
            suffix = f" ({', '.join(meta)})" if meta else ""
            lines.append(f"  {p.get('title', '').strip()}{suffix}\n    {p.get('url', '').strip()}")
        blocks.append("\n".join(lines))

    if total_posts == 0:
        blocks.append(f"<no Reddit browser-search posts found mentioning {query_symbol}>")
    return "\n\n".join(blocks)


def _fetch_reddit_posts_browser(
    ticker: str,
    subreddits: Iterable[str],
    limit_per_sub: int,
    timeout: float,
) -> str:
    query_symbol = social_crypto_symbol(ticker)
    selected_subreddits = _browser_subreddits(query_symbol, subreddits)
    search_query, match_terms = _search_profile(query_symbol)
    timeout_ms = int(float(os.environ.get("TRADINGAGENTS_REDDIT_BROWSER_TIMEOUT_MS", timeout * 1000)))
    warmup_seconds = float(os.environ.get("TRADINGAGENTS_REDDIT_BROWSER_WARMUP_SECONDS", "3"))
    settle_seconds = float(os.environ.get("TRADINGAGENTS_REDDIT_BROWSER_SETTLE_SECONDS", "2"))
    profile_dir = Path(
        os.environ.get("TRADINGAGENTS_REDDIT_PROFILE_DIR", str(_BROWSER_PROFILE_DIR))
    )
    headless = os.environ.get("TRADINGAGENTS_REDDIT_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    keep_http2 = _env_flag("TRADINGAGENTS_REDDIT_KEEP_HTTP2")

    try:
        from cloakbrowser import launch_persistent_context
    except ImportError:
        return (
            "<reddit browser fallback unavailable: install optional dependency with "
            "`uv run --with cloakbrowser ...`>"
        )

    if _env_flag("TRADINGAGENTS_REDDIT_CLEAR_PROFILE") and profile_dir.exists():
        shutil.rmtree(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    launch_args = [] if keep_http2 else ["--disable-http2"]
    try:
        context = launch_persistent_context(
            str(profile_dir),
            headless=headless,
            args=launch_args,
        )
    except Exception as exc:
        logger.warning("Reddit browser fallback launch failed for %s: %s", query_symbol, exc)
        return f"<reddit browser fallback unavailable: {type(exc).__name__}>"

    posts_by_subreddit: dict[str, list[dict[str, str]]] = {}
    try:
        page = context.new_page()
        warmup_error = _browser_goto(
            page,
            "https://www.reddit.com",
            timeout_ms,
            warmup_seconds,
        )
        if warmup_error:
            return f"<reddit browser fallback blocked during warm-up: {warmup_error}>"

        for sub in selected_subreddits:
            url = (
                f"https://www.reddit.com/r/{sub}/search/"
                f"?q={quote_plus(search_query)}&restrict_sr=1&sort=new&t=week"
            )
            block = _browser_goto(page, url, timeout_ms, settle_seconds)
            if block:
                logger.warning("Reddit browser fallback blocked for r/%s · %s: %s", sub, query_symbol, block)
                posts_by_subreddit[sub] = []
                continue
            posts_by_subreddit[sub] = _extract_browser_posts(
                page,
                limit_per_sub,
                match_terms,
            )
    except Exception as exc:
        logger.warning("Reddit browser fallback failed for %s: %s", query_symbol, exc)
        return f"<reddit browser fallback unavailable: {type(exc).__name__}>"
    finally:
        context.close()

    return _format_browser_blocks(query_symbol, selected_subreddits, posts_by_subreddit)


def _fetch_subreddit(
    ticker: str,
    sub: str,
    limit: int,
    timeout: float,
) -> list[dict]:
    query_symbol = social_crypto_symbol(ticker)
    qs = urlencode({
        "q": query_symbol,
        "restrict_sr": "on",
        "sort": "new",
        "t": "week",  # last 7 days
        "limit": limit,
    })
    url = _API.format(sub=sub, qs=qs)
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except HTTPError as exc:
        if exc.code == 403:
            raise _RedditAccessBlocked from exc
        logger.warning("Reddit fetch failed for r/%s · %s: %s", sub, query_symbol, exc)
        return []
    except (URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Reddit fetch failed for r/%s · %s: %s", sub, query_symbol, exc)
        return []
    children = (payload.get("data") or {}).get("children") or []
    return [c.get("data", {}) for c in children if isinstance(c, dict)]


def fetch_reddit_posts(
    ticker: str,
    subreddits: Iterable[str] = DEFAULT_SUBREDDITS,
    limit_per_sub: int = 5,
    timeout: float = 10.0,
    inter_request_delay: float = 0.4,
) -> str:
    """Fetch recent Reddit posts mentioning ``ticker`` across finance
    subreddits and return them as a formatted plaintext block.

    ``inter_request_delay`` keeps us under Reddit's public rate limit
    (~10 req/min per IP) even if the caller queries many subreddits.
    """
    query_symbol = social_crypto_symbol(ticker)
    subreddits = tuple(subreddits)
    blocks = []
    total_posts = 0
    for i, sub in enumerate(subreddits):
        if i > 0:
            time.sleep(inter_request_delay)
        try:
            posts = _fetch_subreddit(ticker, sub, limit_per_sub, timeout)
        except _RedditAccessBlocked:
            if _browser_fallback_enabled():
                return _fetch_reddit_posts_browser(
                    ticker,
                    subreddits,
                    limit_per_sub,
                    timeout,
                )
            return (
                f"<reddit unavailable: HTTP 403 blocked unauthenticated public "
                f"access for {query_symbol}>"
            )
        total_posts += len(posts)
        if not posts:
            blocks.append(f"r/{sub}: <no posts found mentioning {query_symbol} in the past 7 days>")
            continue

        lines = [f"r/{sub} — {len(posts)} recent posts mentioning {query_symbol}:"]
        for p in posts:
            title = (p.get("title") or "").replace("\n", " ").strip()
            score = p.get("score", 0)
            comments = p.get("num_comments", 0)
            created = p.get("created_utc")
            created_str = (
                time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "?"
            )
            selftext = (p.get("selftext") or "").replace("\n", " ").strip()
            if len(selftext) > 240:
                selftext = selftext[:240] + "…"
            lines.append(
                f"  [{created_str} · {score:>4}↑ · {comments:>3}c] {title}"
                + (f"\n    body excerpt: {selftext}" if selftext else "")
            )
        blocks.append("\n".join(lines))

    if total_posts == 0:
        return (
            f"<no Reddit posts found mentioning {query_symbol} across "
            f"{', '.join(f'r/{s}' for s in subreddits)} in the past 7 days>"
        )
    return "\n\n".join(blocks)
