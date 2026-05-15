# Date Semantics and Future Improvements

The analysis date is currently an as-of date for the agent graph. It is passed through as `trade_date`, shown to agents as the current trading date, and used by date-aware data tools for historical price, technical indicator, news, checkpoint, and report paths.

Some data sources are still latest-feed snapshots rather than strict historical snapshots. In particular, social sentiment sources such as StockTwits, Reddit, and CoinGecko fetch recent/current provider data, and the yfinance fundamentals overview uses the latest `Ticker.info` metadata. Financial statements and technical indicators are filtered by the selected date where supported, but the overall run should be understood as a mix of date-bounded data and latest available provider data.

Future improvements should make this behavior explicit and configurable:

- Add a first-class date context, for example `trade_date`, `as_of_datetime`, `timezone`, `market_session`, and `allow_live_data`.
- Separate modes for `historical_asof` analysis and `latest_live` analysis.
- Validate future dates consistently across CLI, WebUI, and API calls.
- Make live sentiment feeds date-aware where provider APIs allow it, or label them clearly as latest-feed inputs in reports.
- Ensure OHLCV date ranges include the selected analysis date when users expect "through this date" behavior.
- Add report metadata showing which sections used date-bounded data and which used live/latest snapshots.
