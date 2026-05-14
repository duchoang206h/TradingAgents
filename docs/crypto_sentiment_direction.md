# Crypto Sentiment Direction

This project now adds CoinGecko context to the sentiment analyst for crypto
assets. The current goal is pragmatic: enrich the existing news, StockTwits,
and Reddit sentiment read with crypto-native market attention and liquidity
signals without making every local run depend on paid APIs.

## Current implementation

- Crypto symbols are detected through `tradingagents.dataflows.crypto_utils`.
- For crypto tickers, the sentiment analyst fetches CoinGecko context before
  the LLM call.
- The CoinGecko block includes price change, volume, market cap rank,
  trending-search rank, broad community counts, and CoinGecko sentiment vote
  percentages when available.
- The prompt explicitly treats CoinGecko as context, not as a standalone
  sentiment source.

## Why CoinGecko first

CoinGecko is a good first crypto-native source because it has broad asset
coverage, useful free endpoints, and signals that help interpret social/news
sentiment:

- Trending search rank can indicate retail attention.
- 24h/7d price change helps distinguish rising attention from panic selling.
- Volume and market cap rank help judge whether social chatter is liquid enough
  to matter.
- Community follower/subscriber counts provide rough signal-quality context.

CoinMarketCap is still useful, especially for rankings, listings, quotes, and
market metadata, but it is less compelling as the first sentiment-oriented
integration because most of its data is reference/market data rather than
social or narrative signal.

## Near-term improvements

- Add crypto-specific Reddit subreddits:
  `CryptoCurrency`, `Bitcoin`, `ethereum`, `solana`, and asset-specific
  communities where appropriate.
- Normalize social tickers per source. Examples:
  - Yahoo Finance: `BTC-USD`
  - StockTwits: often `BTC.X` or `BTC`
  - Reddit search: usually `BTC`, `Bitcoin`, or `$BTC`
- Add config switches for crypto sources:
  - enable/disable CoinGecko context
  - choose free vs pro endpoint base URL
  - adjust timeout and cache TTL
- Cache CoinGecko responses under the existing cache directory to reduce rate
  limit pressure during repeated runs.
- Include CoinGecko categories and category-level trend summaries for assets
  like AI tokens, L2s, DeFi, meme coins, and stablecoins.

## Medium-term improvements

- Add CryptoPanic or another crypto-news aggregator for crypto-native headlines.
- Add LunarCrush, Santiment, or similar providers for dedicated social
  sentiment if API access is available.
- Add on-chain context for supported assets:
  exchange inflows/outflows, active addresses, transaction counts, fees,
  stablecoin liquidity, and large wallet movement.
- Add derivatives context:
  funding rates, open interest, liquidations, basis, and options skew.
- Add tokenomics context:
  unlock schedule, circulating supply changes, emissions, burns, staking
  yield, governance proposals, and foundation/team wallet disclosures.

## Long-term direction

The long-term target is a dedicated crypto sentiment stack rather than a stock
sentiment stack with crypto context attached. A mature design would separate
crypto evidence into these buckets:

- Market attention: CoinGecko/CoinMarketCap trending, exchange volume, search
  interest, app rankings.
- Social sentiment: StockTwits, Reddit, X/Twitter, Telegram/Discord when
  legally and operationally practical.
- News narrative: crypto-native news feeds, regulatory headlines, protocol
  announcements.
- On-chain behavior: flows, usage, holders, whale activity, network revenue.
- Derivatives positioning: funding, open interest, liquidation clusters.
- Token economics: unlocks, staking, burns, incentives, governance.

The final report should keep these buckets distinct. Mixing them into one
"sentiment" score hides risk: high attention can be bullish momentum, but it
can also be crowded positioning or panic. The agent should explain whether
sources align, diverge, or merely show activity without clear directional
intent.
