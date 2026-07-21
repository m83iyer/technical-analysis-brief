# Technical Analysis Brief - Methodology

## Research boundary

This is a historical research artifact, not a signal service. It describes a deterministic rule, its historical evidence, its current mechanical state, and a conditional decision protocol. It does not instruct a reader to transact and it makes no claim about future profitability.

## Data contract

- adjusted daily open, high, low, close, and volume;
- strictly increasing, unique sessions;
- positive OHLC prices and non-negative volume;
- minimum 2,016 sessions, approximately eight trading years;
- latest fifteen years retained when more history exists;
- market-aware twenty-session median notional turnover: at least USD 25 million for US equities or INR 1 billion for Indian equities.

Adjusted prices are used so split and distribution discontinuities do not become artificial strategy events. The exact input is saved beside every artifact and hashed into the evidence receipt.

## Candidate registry

The registry is fixed before any ticker is analyzed. Version two contains fifteen simple long-only rules:

- three Donchian breakout variants;
- three adaptive Bollinger reversion variants with a long-term trend guard;
- three price-momentum variants with a long-term trend guard;
- three moving-average trend variants;
- three MACD trend variants.

The registry is intentionally small. No per-ticker parameter search, LLM-generated rule, or holdout-driven rewrite is permitted.

## Execution model

Signals are calculated after a session closes. A changed position state is filled at the next session open. The simulator applies the declared per-side fee-plus-slippage cost on each state change and marks open exposure from open to close and close to the next open. Each evaluation window begins and ends flat.

## Chronology

After indicator warm-up, the retained history is divided in order:

- training: first 50%;
- validation: next 25%;
- untouched holdout: final 25%.

Training checks that the rule is active enough to evaluate. Validation determines eligibility and ranking. Holdout data do not affect the selected rule. The single pre-holdout winner is frozen before its holdout result is revealed.

## Pre-holdout gates

A candidate must have:

- at least four completed training trades;
- training net return above -5%;
- at least three completed validation trades;
- positive validation net return;
- validation profit factor of at least 1.05;
- validation maximum drawdown no worse than 25%;
- positive validation return at the second declared cost tier: 20 basis points per side in the US or 30 in India;
- at least half of its declared neighboring parameters positive in validation.

Eligible candidates are ranked with a documented score combining validation Sharpe, capped profit factor, drawdown control, sample activity, and neighboring-parameter stability. Raw return is not the ranking objective.

## Untouched-holdout gate

The pre-selected winner qualifies only when the holdout has:

- at least three completed trades;
- positive net return;
- profit factor of at least 1.05;
- positive Sharpe ratio;
- maximum drawdown no worse than 25%;
- positive return at the second declared cost tier: 20 basis points per side in the US or 30 in India;
- at least half of declared neighbors positive.

Failure produces `NO ROBUST EDGE`. The engine does not promote the second-place rule after seeing the holdout.

## Conditional levels

When a rule qualifies, the artifact may show:

- the rule's price-based activation reference when one exists;
- a structural invalidation reference derived from the tighter valid value of a twenty-session swing low and a two-ATR distance;
- 1R and 2R arithmetic references measured from the activation reference to the invalidation reference;
- the rule's mechanical exit condition.

The historical success metrics use the mechanical exit condition. The structural invalidation and fixed 1R and 2R levels are current planning references and are not represented as historical exit rules. This distinction is stated on the page. When a rule does not qualify, all such levels are suppressed.

## Decision success

Success is not defined as a precise price forecast. A useful technical result has no ambiguity about the condition that activates the setup, the next-open execution convention, the condition that ends the tested rule, the risk frame, and the evidence supporting the rule. When the state is already active, the artifact says there is no fresh trigger. When the evidence fails, the artifact publishes no decision coordinates.

Win rate is labelled `success rate` for readability, but it is never interpreted alone. The page pairs it with average-winner-to-average-loss payoff, per-trade expectancy, profit factor, maximum drawdown, completed trades, median holding sessions, cost stress, and neighboring-parameter evidence. A low win rate with a strong payoff can be viable; a high win rate with poor payoff can be fragile.

## Known limitations

- current-constituent testing can contain survivorship bias;
- Yahoo Finance adjusted history is convenient research data, not an exchange-grade point-in-time feed;
- daily bars cannot reproduce intraday ordering when both a threshold and invalidation are crossed in one session;
- the cost model does not include market impact, taxes, borrow, or partial fills;
- one ticker is not a diversified portfolio;
- simple holdout validation reduces but cannot eliminate selection bias or non-stationarity;
- fifteen attempted rules are disclosed so the reader can see the multiple-testing surface.

The methodology is deliberately adversarial to attractive backtests. Backtest selection bias and non-normal returns can inflate Sharpe estimates, which is why the artifact emphasizes chronology, a fixed trial count, cost stress, neighboring parameters, and refusal rather than a single optimized statistic.

Research output - not a recommendation. The reader decides whether to act.
