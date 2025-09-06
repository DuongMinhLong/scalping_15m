# scalping_15m

Automated trading bot orchestrator for 1h timeframe with 4h/1d context, including scheduled checks and order management.

The bot now targets the **forex** market using the FXCM API and is
optimised for trading **XAU/USD**. The payload includes the US Dollar
Index (DXY), latest forex news, and a session filter only allows trades
between the London and New York sessions (06:00–16:00 UTC).

This build automatically removes JSON metadata for cancelled or unmapped limit orders without open positions before calling the GPT API.

The stop-loss manager shifts the stop-loss to the entry price once the first take-profit is hit.

## Configuration

Create a `.env` file with your credentials and desired pairs. **Both**
`FXCM_API_KEY` and `FXCM_ACCOUNT_ID` must be set or the application will
refuse to start. The following variables are recognised:

```env
FXCM_API_KEY=your_fxcm_api_key
FXCM_ACCOUNT_ID=your_fxcm_account_id
FXCM_API_URL=https://api-demo.fxcm.com
TE_API_KEY=your_trading_economics_key
OPENAI_API_KEY=your_openai_api_key

# Comma separated list of forex pairs (e.g. XAUUSD,EURUSD)
FOREX_PAIRS=XAUUSD
```

### FXCM practice accounts

FXCM provides free **demo** accounts for testing and backtesting. A demo
API token and account ID are distinct from live credentials and use the
base URL `https://api-demo.fxcm.com`. You can choose a virtual balance and
trade with real-time prices without risking funds. To trade live, replace
`FXCM_API_URL` with `https://api.fxcm.com` and supply your live
credentials.

### Economic events API

Upcoming macroeconomic events and news are fetched from the
[Trading Economics](https://tradingeconomics.com/api/) API. If
`TE_API_KEY` is not set, the public `guest:guest` key is used (subject to
rate limits). When the key is missing or the request fails, the bot
continues operating but the `events` and `news` sections of the payload
will be empty.
