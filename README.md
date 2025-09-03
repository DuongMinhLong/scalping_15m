# scalping_15m

Automated trading bot orchestrator for 15m timeframe with 1h/4h context, including scheduled checks and order management. Only model suggestions with confidence ≥7 and risk‑reward >1.5 are acted upon.

This build automatically removes JSON metadata for cancelled or unmapped limit orders without open positions before calling the GPT API.

The stop-loss manager shifts the stop-loss to the entry price once the first take-profit is hit.

## Configuration

Specify the trading pairs to analyse via the `COIN_PAIRS` variable in your `.env` file. Use a comma-separated list of pairs (e.g. `COIN_PAIRS=BTCUSDT,ETHUSDT`).

### Economic events API

Upcoming macroeconomic events are fetched from the
[Trading Economics](https://tradingeconomics.com/api/) calendar API. Set
the `TE_API_KEY` environment variable with your API token to enable
event retrieval. If the variable is not set, the public `guest:guest`
key is used (subject to rate limits):

```env
TE_API_KEY=your_api_key_here
```

If the key is missing or the request fails, the bot will continue
operating but the `events` section of the payload will be empty.
