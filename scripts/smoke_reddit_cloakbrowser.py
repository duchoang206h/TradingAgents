"""Smoke-test Reddit search through CloakBrowser.

This is an opt-in diagnostic script for environments where Reddit's public
JSON endpoints return HTTP 403. It does not change the application runtime
path and does not add CloakBrowser to the base project dependencies.

Usage:
    uv run --with cloakbrowser python scripts/smoke_reddit_cloakbrowser.py HYPE
    uv run --with cloakbrowser python scripts/smoke_reddit_cloakbrowser.py HYPE --headed
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from urllib.parse import quote_plus

from tradingagents.dataflows.crypto_utils import social_crypto_symbol

DEFAULT_SUBREDDITS = ("wallstreetbets", "stocks", "investing")
SYMBOL_SEARCH_PROFILES = {
    "HYPE": {
        "search_query": '"$HYPE" OR Hyperliquid',
        "match_terms": ("$HYPE", "HYPE.X", "Hyperliquid"),
    },
}


def _default_profile_dir() -> Path:
    return Path.home() / ".tradingagents" / "reddit-cloakbrowser-profile"


def _load_cloakbrowser():
    try:
        from cloakbrowser import launch_persistent_context
    except ImportError as exc:
        raise SystemExit(
            "cloakbrowser is not installed. Run with:\n"
            "  uv run --with cloakbrowser python scripts/smoke_reddit_cloakbrowser.py HYPE"
        ) from exc
    return launch_persistent_context


def _page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


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


def _goto(page, url: str, timeout_ms: int, settle_seconds: float) -> str:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        return f"navigation error: {type(exc).__name__}: {exc}"
    time.sleep(settle_seconds)
    text = _page_text(page)
    return _blocked_reason(text) or ""


def _search_profile(query: str) -> tuple[str, tuple[str, ...]]:
    profile = SYMBOL_SEARCH_PROFILES.get(query.upper())
    if profile:
        return profile["search_query"], tuple(profile["match_terms"])
    return query, (query,)


def _extract_posts(page, limit: int, match_terms: tuple[str, ...]) -> list[dict[str, str]]:
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


def _search_subreddit(
    page,
    subreddit: str,
    query: str,
    search_query: str,
    match_terms: tuple[str, ...],
    args,
) -> dict:
    url = (
        f"https://www.reddit.com/r/{subreddit}/search/"
        f"?q={quote_plus(search_query)}&restrict_sr=1&sort=new&t=week"
    )
    block = _goto(page, url, args.timeout_ms, args.settle_seconds)
    if block:
        return {"subreddit": subreddit, "url": url, "error": block, "posts": []}
    posts = _extract_posts(page, args.limit, match_terms)
    return {"subreddit": subreddit, "url": url, "posts": posts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", help="Ticker or crypto symbol, e.g. HYPE or HYPE32196-USD")
    parser.add_argument(
        "--subreddits",
        nargs="+",
        default=list(DEFAULT_SUBREDDITS),
        help="Subreddits to search",
    )
    parser.add_argument("--limit", type=int, default=5, help="Max posts per subreddit")
    parser.add_argument(
        "--search-query",
        default=None,
        help="Override the Reddit search query; defaults to symbol-specific profile",
    )
    parser.add_argument(
        "--match-terms",
        nargs="+",
        default=None,
        help="Terms that must appear in an extracted post card/link",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=_default_profile_dir(),
        help="Persistent browser profile directory",
    )
    parser.add_argument(
        "--clear-profile",
        action="store_true",
        help="Delete the profile directory before launching",
    )
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument(
        "--keep-http2",
        action="store_true",
        help="Do not pass --disable-http2 to Chromium",
    )
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument("--warmup-seconds", type=float, default=3.0)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--json", action="store_true", help="Print raw JSON only")
    args = parser.parse_args()

    query = social_crypto_symbol(args.symbol)
    default_search_query, default_match_terms = _search_profile(query)
    search_query = args.search_query or default_search_query
    match_terms = tuple(args.match_terms) if args.match_terms else default_match_terms
    if args.clear_profile and args.profile_dir.exists():
        shutil.rmtree(args.profile_dir)
    args.profile_dir.mkdir(parents=True, exist_ok=True)
    launch_persistent_context = _load_cloakbrowser()

    launch_args = [] if args.keep_http2 else ["--disable-http2"]
    context = launch_persistent_context(
        str(args.profile_dir),
        headless=not args.headed,
        args=launch_args,
    )

    results = {
        "query": query,
        "search_query": search_query,
        "match_terms": list(match_terms),
        "profile_dir": str(args.profile_dir),
        "disable_http2": not args.keep_http2,
        "subreddits": [],
    }

    try:
        page = context.new_page()
        warmup_error = _goto(
            page,
            "https://www.reddit.com",
            args.timeout_ms,
            args.warmup_seconds,
        )
        results["warmup_error"] = warmup_error

        if warmup_error:
            results["subreddits"] = []
        else:
            for subreddit in args.subreddits:
                results["subreddits"].append(
                    _search_subreddit(
                        page,
                        subreddit,
                        query,
                        search_query,
                        match_terms,
                        args,
                    )
                )
    finally:
        context.close()

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"Query: {results['query']}")
    print(f"Search query: {results['search_query']}")
    print(f"Match terms: {', '.join(results['match_terms'])}")
    print(f"Profile: {results['profile_dir']}")
    print(f"HTTP/2 disabled: {results['disable_http2']}")
    if results.get("warmup_error"):
        print(f"Warm-up failed: {results['warmup_error']}")
        print(json.dumps(results, indent=2))
        return 2

    total = 0
    for entry in results["subreddits"]:
        print(f"\nr/{entry['subreddit']}")
        if entry.get("error"):
            print(f"  error: {entry['error']}")
            continue
        posts = entry.get("posts") or []
        total += len(posts)
        if not posts:
            print("  no posts extracted")
            continue
        for idx, post in enumerate(posts, start=1):
            meta = []
            if post.get("score"):
                meta.append(f"score={post['score']}")
            if post.get("comments"):
                meta.append(f"comments={post['comments']}")
            suffix = f" ({', '.join(meta)})" if meta else ""
            print(f"  {idx}. {post['title']}{suffix}")
            print(f"     {post['url']}")

    print(f"\nTotal posts extracted: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
