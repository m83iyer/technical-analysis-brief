# Technical Analysis Brief

Turn a US or Indian stock ticker into a refusal-first, one-page technical decision brief.

The engine evaluates a frozen set of 15 transparent rules, selects one winner using training and validation data only, and then reveals an untouched holdout. If that pre-selected rule fails, the result is `NO ROBUST EDGE` and entry, stop and target coordinates stay suppressed. A qualified page answers four practical questions: what activates the setup, when the model assumes execution, what invalidates or exits it, and whether the same rule survived unseen history and higher costs.

Success rate never appears alone. The page pairs it with payoff ratio, expectancy, profit factor, drawdown, completed trades, median holding period, cost stress and neighboring-parameter stability. Fixed invalidation and 1R/2R values are planning references; historical returns use the stated rule exit.

## Markets

- US equities: `AAPL`, `MSFT`, `BRK.B`
- India on NSE: `RELIANCE`, `TCS.NS`, `HDFCBANK.NS`
- India on BSE: `500325.BO` or the six-digit code with `--market in`

Plain Indian symbols default to NSE when `--market in` is supplied. The evidence receipt keeps the canonical `.NS` or `.BO` suffix, currency, exchange, market-specific liquidity threshold and declared cost assumptions. USD never leaks into an INR artifact.

## Install and run

```bash
python -m pip install .
technical-brief AAPL --market us --out outputs/aapl
technical-brief RELIANCE --market in --out outputs/reliance
technical-brief 500325.BO --out outputs/reliance-bse
```

Every successful run writes the exact adjusted OHLCV CSV, deterministic JSON evidence, one-page PDF and 1600 x 2000 PNG. A short, illiquid or unavailable history writes a machine-readable failure receipt and no trading coordinates.

For a replay with saved data:

```bash
technical-brief RELIANCE.NS --market in \
  --input-csv examples/reliance-adjusted-ohlcv.csv \
  --source "saved research input" \
  --fetched-at "2026-07-22T00:00:00+00:00" \
  --out outputs/replay
```

## Boundaries

The tool does not place orders, personalize position size, use intraday data, or ask an LLM to choose a rule. Yahoo Finance is a convenient research source, not an exchange-grade point-in-time feed. Taxes, market impact and partial fills are excluded; India uses a higher declared fee-plus-slippage model, but it is not a broker-specific charge calculator.

See `PRODUCT_SPEC.md` and `METHODOLOGY.md` for the full evidence contract.

Research output — not a recommendation. The reader decides whether to act.
