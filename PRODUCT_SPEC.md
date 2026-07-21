# Technical Analysis Brief - Product Specification

## Problem

Most technical-analysis outputs optimize for a confident-looking chart. This tool optimizes for a usable decision protocol: is there a qualified setup, what exact condition activates it, what invalidates it, what ends it, and did that same rule survive chronology, costs, nearby parameters, and an untouched holdout?

## Version-two scope

- liquid US equities and broad US equity ETFs;
- liquid Indian equities listed on NSE or BSE;
- daily, adjusted OHLCV data;
- long-only research rules;
- at least eight years of usable history;
- a fixed registry of fifteen simple trend, breakout, momentum, and adaptive mean-reversion rules;
- next-session-open execution for decisions formed at the prior close;
- market-specific declared fee-plus-slippage assumptions: US 10 basis points per side with 20/40 stress; India 15 basis points per side with 30/60 stress.

Intraday signals, options, short selling, leverage, taxes, market impact, personalized sizing, broker execution, and live order placement are outside version two.

## Input

- ticker and optional explicit `us` or `in` market;
- adjusted daily OHLCV history;
- source and fetch timestamp;
- optional explicit as-of session.

## Method

1. Validate chronology, uniqueness, required fields, price integrity, history length, and liquidity.
2. Freeze the latest fifteen years, or all available history when shorter.
3. Split chronologically into 50% training, 25% validation, and 25% untouched holdout windows.
4. Evaluate the fixed rule registry with next-open execution and declared costs.
5. Gate rules on activity, positive validation evidence, drawdown, doubled-cost survival, and nearby-parameter stability.
6. Select exactly one pre-holdout winner using validation evidence only.
7. Reveal the untouched holdout and either qualify the pre-selected rule or return `NO ROBUST EDGE`.
8. Generate a decision contract only when the pre-selected rule qualifies: setup status, activation condition, next-open execution timing, risk invalidation, planning R-levels, and the exact tested exit rule. If it does not qualify, the full decision contract is suppressed.

## Output

- one-page PDF and 1600 x 2000 PNG infographic;
- deterministic JSON evidence sidecar;
- exact adjusted OHLCV input used for the run, its canonical ticker, market, exchange and currency;
- pre-holdout ranking and rejection reasons;
- validation, holdout, cost-stress, neighboring-parameter, regime, and benchmark evidence;
- current setup state, activation condition, execution timing, invalidation, 1R and 2R planning references, and the tested exit rule when qualified;
- success rate paired with payoff ratio, expectancy, profit factor, drawdown, completed trades, and median holding sessions.

The one-page hierarchy is deliberately limited to three dominant visuals:

1. a decision map showing current price structure and decision coordinates;
2. an exact activation, execution, invalidation, and exit protocol;
3. out-of-sample strategy evidence explaining whether the rule earned trust.

The public artifact must state:

`Research output - not a recommendation. The reader decides whether to act.`

## Refusal behavior

The tool returns `NO ROBUST EDGE` and suppresses conditional levels when:

- history or liquidity is insufficient;
- no rule clears the pre-holdout gates;
- the selected rule fails the untouched holdout;
- the rule fails doubled-cost or neighboring-parameter evidence;
- current data are incomplete or internally inconsistent.

Empty is an acceptable result. The renderer must not replace missing evidence with a generic trading opinion. A rule that is already active is labelled `ACTIVE / NO FRESH TRIGGER`; it is not misrepresented as a new entry event.
