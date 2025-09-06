# scalping_15m

Automated trading bot orchestrator for 1h timeframe with 4h/1d context, including scheduled checks and order management.

The bot now targets the **forex** market using the OANDA API and is
optimised for trading **XAU/USD**.  The payload includes the US Dollar
Index (DXY), latest forex news, and a session filter only allows trades
between the London and New York sessions (06:00–16:00 UTC).

This build automatically removes JSON metadata for cancelled or unmapped limit orders without open positions before calling the GPT API.

The stop-loss manager shifts the stop-loss to the entry price once the first take-profit is hit.

## Configuration

Create a `.env` file with your credentials and desired pairs. **Both**
`OANDA_API_KEY` and `OANDA_ACCOUNT_ID` must be set or the application will
refuse to start. The following variables are recognised:

```env
OANDA_API_KEY=your_oanda_api_key
OANDA_ACCOUNT_ID=your_oanda_account_id
OANDA_API_URL=https://api-fxpractice.oanda.com/v3
TE_API_KEY=your_trading_economics_key
OPENAI_API_KEY=your_openai_api_key

# Comma separated list of forex pairs (e.g. XAUUSD,EURUSD)
FOREX_PAIRS=XAUUSD
```

### OANDA practice accounts

OANDA provides free **practice** accounts for testing and backtesting. A
practice API key and account ID are distinct from live credentials and use
the base URL `https://api-fxpractice.oanda.com`. You can choose a virtual
balance of 10k, 50k or 100k USD; prices mirror the real market but orders do
not risk real funds. To trade live, replace `OANDA_API_URL` with
`https://api-fxtrade.oanda.com/v3` and supply your live credentials.

### Economic events API

Upcoming macroeconomic events and news are fetched from the
[Trading Economics](https://tradingeconomics.com/api/) API. If
`TE_API_KEY` is not set, the public `guest:guest` key is used (subject to
rate limits). When the key is missing or the request fails, the bot
continues operating but the `events` and `news` sections of the payload
will be empty.
