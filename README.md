# scalping_15m

Automated trading bot orchestrator with scheduled checks and order management.

This build automatically removes JSON metadata for cancelled or unmapped limit orders without open positions before calling the GPT API.

The stop-loss manager shifts the stop-loss to the entry price once the first take-profit is hit.
