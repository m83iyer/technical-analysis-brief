#!/usr/bin/env python3
"""Deterministic ticker-level technical evidence engine.

The engine consumes already-fetched adjusted daily OHLCV data. It never places
orders and never calls an LLM. Close-time decisions are executed at the next
session open with declared costs.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from technical_brief.market import MarketProfile, resolve_security


VERSION = "0.2.0"
DISCLAIMER = "Research output — not a recommendation. The reader decides whether to act."
# Backward-compatible US defaults. Analysis uses the resolved market profile.
BASE_COST_BPS = 10.0
STRESS_COSTS_BPS = (10.0, 20.0, 40.0)
MIN_SESSIONS = 2_016
MAX_SESSIONS = 3_780
MIN_MEDIAN_DOLLAR_VOLUME = 25_000_000.0


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    label: str
    params: tuple[float, ...]
    entry_rule: str
    exit_rule: str


@dataclass
class Metrics:
    sessions: int
    years: float
    trades: int
    net_return: float
    cagr: float
    benchmark_return: float
    max_drawdown: float
    sharpe: float
    sortino: float
    profit_factor: float | None
    win_rate: float
    expectancy: float
    exposure: float
    turnover: float


def candidate_registry() -> list[Candidate]:
    return [
        Candidate("donchian-20-10", "breakout", "20/10 Donchian", (20, 10), "Close clears prior 20-session high", "Close breaks prior 10-session low"),
        Candidate("donchian-55-20", "breakout", "55/20 Donchian", (55, 20), "Close clears prior 55-session high", "Close breaks prior 20-session low"),
        Candidate("donchian-100-40", "breakout", "100/40 Donchian", (100, 40), "Close clears prior 100-session high", "Close breaks prior 40-session low"),
        Candidate("bollinger-20-2.0", "mean_reversion", "20D Bollinger 2.0x", (20, 2.0), "Close falls below lower band while above 200D average", "Close returns to mid-band or loses 200D average"),
        Candidate("bollinger-20-2.5", "mean_reversion", "20D Bollinger 2.5x", (20, 2.5), "Close falls below lower band while above 200D average", "Close returns to mid-band or loses 200D average"),
        Candidate("bollinger-30-2.0", "mean_reversion", "30D Bollinger 2.0x", (30, 2.0), "Close falls below lower band while above 200D average", "Close returns to mid-band or loses 200D average"),
        Candidate("momentum-63-21", "momentum", "63/21 Momentum", (63, 21), "Close exceeds its 63-session reference above the 200D average", "Close loses its 21-session reference or 200D average"),
        Candidate("momentum-126-42", "momentum", "126/42 Momentum", (126, 42), "Close exceeds its 126-session reference above the 200D average", "Close loses its 42-session reference or 200D average"),
        Candidate("momentum-252-63", "momentum", "252/63 Momentum", (252, 63), "Close exceeds its 252-session reference above the 200D average", "Close loses its 63-session reference or 200D average"),
        Candidate("sma-20-100", "trend", "20/100 SMA Trend", (20, 100), "20D average is above 100D average", "20D average falls below 100D average"),
        Candidate("sma-30-150", "trend", "30/150 SMA Trend", (30, 150), "30D average is above 150D average", "30D average falls below 150D average"),
        Candidate("sma-50-200", "trend", "50/200 SMA Trend", (50, 200), "50D average is above 200D average", "50D average falls below 200D average"),
        Candidate("macd-8-21-5", "trend", "8/21/5 MACD Trend", (8, 21, 5), "MACD is above its signal while price is above 200D average", "MACD falls below signal or price loses 200D average"),
        Candidate("macd-12-26-9", "trend", "12/26/9 MACD Trend", (12, 26, 9), "MACD is above its signal while price is above 200D average", "MACD falls below signal or price loses 200D average"),
        Candidate("macd-19-39-9", "trend", "19/39/9 MACD Trend", (19, 39, 9), "MACD is above its signal while price is above 200D average", "MACD falls below signal or price loses 200D average"),
    ]


def _canonical_frame(df: pd.DataFrame, profile: MarketProfile) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")
    frame = df[required].copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(None).normalize()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=required)
    if len(frame) < MIN_SESSIONS:
        raise ValueError(f"Insufficient history: {len(frame)} sessions; need {MIN_SESSIONS}")
    # Validate the retained research window. Some providers expose malformed
    # legacy bars from decades before the maximum supported horizon; those rows
    # must neither enter the model nor incorrectly block a clean recent sample.
    frame = frame.tail(MAX_SESSIONS)
    if (frame[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (frame["Volume"] < 0).any():
        raise ValueError("Volume must be non-negative")
    row_scale = frame[["Open", "High", "Low", "Close"]].abs().max(axis=1).clip(lower=1.0)
    tolerance = row_scale * 1e-10
    if (frame["High"] + tolerance < frame[["Open", "Close", "Low"]].max(axis=1)).any():
        raise ValueError("High price is inconsistent with OHLC values")
    if (frame["Low"] - tolerance > frame[["Open", "Close", "High"]].min(axis=1)).any():
        raise ValueError("Low price is inconsistent with OHLC values")
    notional_turnover = (frame["Close"] * frame["Volume"]).tail(20).median()
    if (
        not math.isfinite(float(notional_turnover))
        or float(notional_turnover) < profile.minimum_notional_turnover
    ):
        raise ValueError(
            "Liquidity gate failed: 20-session median notional turnover "
            f"{profile.currency_symbol}{float(notional_turnover):,.0f}; need "
            f"{profile.currency_symbol}{profile.minimum_notional_turnover:,.0f}"
        )
    return frame


def _state_from_events(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    values = np.zeros(len(entry), dtype=bool)
    active = False
    for index, (enter_now, exit_now) in enumerate(zip(entry.fillna(False), exit_.fillna(False))):
        if not active and bool(enter_now):
            active = True
        elif active and bool(exit_now):
            active = False
        values[index] = active
    return pd.Series(values, index=entry.index, dtype=bool)


def build_signal_frame(df: pd.DataFrame, candidate: Candidate) -> pd.DataFrame:
    close, high, low = df["Close"], df["High"], df["Low"]
    sma200 = close.rolling(200).mean()
    state = pd.Series(False, index=df.index, dtype=bool)
    entry_level = pd.Series(np.nan, index=df.index, dtype=float)
    exit_level = pd.Series(np.nan, index=df.index, dtype=float)

    if candidate.family == "breakout":
        entry_window, exit_window = map(int, candidate.params)
        entry_level = high.shift(1).rolling(entry_window).max()
        exit_level = low.shift(1).rolling(exit_window).min()
        state = _state_from_events(close > entry_level, close < exit_level)
    elif candidate.family == "mean_reversion":
        window, width = int(candidate.params[0]), float(candidate.params[1])
        middle = close.rolling(window).mean()
        deviation = close.rolling(window).std(ddof=0)
        entry_level = middle - width * deviation
        exit_level = middle
        state = _state_from_events((close < entry_level) & (close > sma200), (close >= middle) | (close < sma200))
    elif candidate.family == "momentum":
        entry_window, exit_window = map(int, candidate.params)
        entry_level = close.shift(entry_window)
        exit_level = close.shift(exit_window)
        state = _state_from_events((close > entry_level) & (close > sma200), (close < exit_level) | (close < sma200))
    elif candidate.candidate_id.startswith("sma-"):
        fast, slow = map(int, candidate.params)
        fast_ma, slow_ma = close.rolling(fast).mean(), close.rolling(slow).mean()
        state = (fast_ma > slow_ma).fillna(False)
        entry_level = slow_ma
        exit_level = slow_ma
    elif candidate.candidate_id.startswith("macd-"):
        fast, slow, signal_window = map(int, candidate.params)
        macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
        signal = macd.ewm(span=signal_window, adjust=False).mean()
        state = ((macd > signal) & (close > sma200)).fillna(False)
        entry_level = sma200
        exit_level = sma200
    elif candidate.candidate_id.startswith("triple-ma-"):
        fast, middle_window, slow = map(int, candidate.params)
        fast_ma = close.rolling(fast).mean()
        middle_ma = close.rolling(middle_window).mean()
        slow_ma = close.rolling(slow).mean()
        state = ((fast_ma > middle_ma) & (middle_ma > slow_ma)).fillna(False)
        entry_level = slow_ma
        exit_level = middle_ma
    else:
        raise ValueError(f"Unsupported candidate: {candidate.candidate_id}")

    return pd.DataFrame({"state": state.astype(bool), "entry_level": entry_level, "exit_level": exit_level}, index=df.index)


def _max_drawdown(curve: pd.Series) -> float:
    if curve.empty:
        return 0.0
    peak = curve.cummax()
    return float(((peak - curve) / peak.replace(0, np.nan)).max())


def evaluate_window(
    df: pd.DataFrame,
    state: pd.Series,
    start: int,
    end: int,
    cost_bps_per_side: float,
) -> tuple[Metrics, pd.DataFrame, list[dict[str, Any]]]:
    if not (0 <= start < end < len(df)):
        raise ValueError("Invalid evaluation window")
    window = df.iloc[start : end + 1]
    signals = state.reindex(df.index).fillna(False)
    cost_rate = cost_bps_per_side / 10_000.0
    equity = 1.0
    benchmark = 1.0
    prior_position = 0
    entry_price: float | None = None
    entry_session: str | None = None
    trades: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    changes = 0
    exposed = 0

    for absolute_index in range(start, end + 1):
        bar = df.iloc[absolute_index]
        session = df.index[absolute_index]
        if absolute_index == start:
            desired = 0
            prior_close = float(bar["Open"])
        else:
            desired = 1 if bool(signals.iloc[absolute_index - 1]) else 0
            prior_close = float(df.iloc[absolute_index - 1]["Close"])

        day_start = equity
        if prior_position:
            equity *= float(bar["Open"]) / prior_close

        if desired != prior_position:
            equity *= 1.0 - cost_rate
            changes += 1
            if desired:
                entry_price = float(bar["Open"]) * (1.0 + cost_rate)
                entry_session = session.date().isoformat()
            elif entry_price is not None and entry_session is not None:
                exit_price = float(bar["Open"]) * (1.0 - cost_rate)
                trades.append({
                    "entry_session": entry_session,
                    "exit_session": session.date().isoformat(),
                    "entry_price": round(entry_price, 6),
                    "exit_price": round(exit_price, 6),
                    "net_return": round(exit_price / entry_price - 1.0, 10),
                    "exit_reason": "rule_state_off",
                })
                entry_price = None
                entry_session = None

        if desired:
            equity *= float(bar["Close"]) / float(bar["Open"])
            exposed += 1

        if absolute_index == start:
            benchmark *= 1.0 - cost_rate
        benchmark *= float(bar["Close"]) / (float(bar["Open"]) if absolute_index == start else prior_close)
        if absolute_index == end:
            benchmark *= 1.0 - cost_rate

        rows.append({
            "session": session.date().isoformat(),
            "equity": equity,
            "benchmark": benchmark,
            "daily_return": equity / day_start - 1.0,
            "position": desired,
        })
        prior_position = desired

    if prior_position and entry_price is not None and entry_session is not None:
        equity *= 1.0 - cost_rate
        exit_price = float(df.iloc[end]["Close"]) * (1.0 - cost_rate)
        trades.append({
            "entry_session": entry_session,
            "exit_session": df.index[end].date().isoformat(),
            "entry_price": round(entry_price, 6),
            "exit_price": round(exit_price, 6),
            "net_return": round(exit_price / entry_price - 1.0, 10),
            "exit_reason": "window_end",
        })
        rows[-1]["equity"] = equity

    curve = pd.DataFrame(rows).set_index("session")
    daily = curve["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    downside = daily[daily < 0]
    annual_vol = float(daily.std(ddof=0) * math.sqrt(252)) if len(daily) else 0.0
    downside_vol = float(downside.std(ddof=0) * math.sqrt(252)) if len(downside) else 0.0
    years = max((df.index[end] - df.index[start]).days / 365.25, 1 / 252)
    trade_returns = [float(trade["net_return"]) for trade in trades]
    wins = [value for value in trade_returns if value > 0]
    losses = [value for value in trade_returns if value <= 0]
    gross_loss = -sum(losses)
    profit_factor = (sum(wins) / gross_loss) if gross_loss > 0 else (None if not wins else 99.0)
    final_equity = float(curve["equity"].iloc[-1])
    benchmark_final = float(curve["benchmark"].iloc[-1])
    metrics = Metrics(
        sessions=len(window),
        years=round(years, 4),
        trades=len(trades),
        net_return=round(final_equity - 1.0, 10),
        cagr=round(final_equity ** (1.0 / years) - 1.0, 10) if final_equity > 0 else -1.0,
        benchmark_return=round(benchmark_final - 1.0, 10),
        max_drawdown=round(_max_drawdown(curve["equity"]), 10),
        sharpe=round(float(daily.mean() * 252 / annual_vol), 10) if annual_vol > 0 else 0.0,
        sortino=round(float(daily.mean() * 252 / downside_vol), 10) if downside_vol > 0 else 0.0,
        profit_factor=round(float(profit_factor), 10) if profit_factor is not None else None,
        win_rate=round(len(wins) / len(trade_returns), 10) if trade_returns else 0.0,
        expectancy=round(sum(trade_returns) / len(trade_returns), 10) if trade_returns else 0.0,
        exposure=round(exposed / len(window), 10),
        turnover=round(changes / len(window), 10),
    )
    return metrics, curve, trades


def _neighbor_map(registry: list[Candidate]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for candidate in registry:
        parameter_family = candidate.candidate_id.split("-", 1)[0]
        groups.setdefault(parameter_family, []).append(candidate.candidate_id)
    result: dict[str, list[str]] = {}
    for identifiers in groups.values():
        for index, identifier in enumerate(identifiers):
            neighbors: list[str] = []
            if index > 0:
                neighbors.append(identifiers[index - 1])
            if index + 1 < len(identifiers):
                neighbors.append(identifiers[index + 1])
            result[identifier] = neighbors
    return result


def _metric_dict(metrics: Metrics) -> dict[str, Any]:
    payload = asdict(metrics)
    if payload["profit_factor"] is not None and payload["profit_factor"] > 9.99:
        payload["profit_factor"] = 9.99
    return payload


def _score(metrics: Metrics, neighbor_ratio: float) -> float:
    sharpe_component = min(max((metrics.sharpe + 0.25) / 2.25, 0.0), 1.0)
    pf_value = metrics.profit_factor or 0.0
    pf_component = min(max((pf_value - 1.0) / 2.0, 0.0), 1.0)
    drawdown_component = min(max(1.0 - metrics.max_drawdown / 0.25, 0.0), 1.0)
    activity_component = min(metrics.trades / 12.0, 1.0)
    return round(100.0 * (
        0.35 * sharpe_component
        + 0.25 * pf_component
        + 0.20 * drawdown_component
        + 0.10 * activity_component
        + 0.10 * neighbor_ratio
    ), 2)


def _frame_hash(df: pd.DataFrame) -> str:
    canonical = df.to_csv(index=True, date_format="%Y-%m-%d", float_format="%.8f").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _current_context(df: pd.DataFrame) -> dict[str, Any]:
    close = df["Close"]
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    returns = close.pct_change()
    vol20 = returns.rolling(20).std(ddof=0) * math.sqrt(252)
    vol_reference = float(vol20.tail(252).median())
    trend = "UPTREND" if float(close.iloc[-1]) > float(sma200.iloc[-1]) and float(sma50.iloc[-1]) > float(sma200.iloc[-1]) else "DOWNTREND" if float(close.iloc[-1]) < float(sma200.iloc[-1]) else "MIXED"
    volatility = "HIGH VOL" if float(vol20.iloc[-1]) > vol_reference else "LOW VOL"
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - close.shift(1)).abs(),
        (df["Low"] - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr14 = true_range.rolling(14).mean()
    return {
        "session": df.index[-1].date().isoformat(),
        "close": round(float(close.iloc[-1]), 4),
        "sma50": round(float(sma50.iloc[-1]), 4),
        "sma200": round(float(sma200.iloc[-1]), 4),
        "atr14": round(float(atr14.iloc[-1]), 4),
        "realized_vol20": round(float(vol20.iloc[-1]), 6),
        "trend": trend,
        "volatility": volatility,
        "regime": f"{trend} / {volatility}",
        "median_notional_turnover20": round(float((df["Close"] * df["Volume"]).tail(20).median()), 2),
    }


def _trade_profile(df: pd.DataFrame, trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the completed trades without hiding payoff behind win rate."""
    if not trades:
        return {
            "completed_trades": 0,
            "success_rate": 0.0,
            "average_winner": None,
            "average_loser": None,
            "median_winner": None,
            "median_loser": None,
            "payoff_ratio": None,
            "median_holding_sessions": None,
        }
    returns = [float(trade["net_return"]) for trade in trades]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value <= 0]
    positions = {session.date().isoformat(): index for index, session in enumerate(df.index)}
    holding_sessions = [
        max(1, positions[trade["exit_session"]] - positions[trade["entry_session"]])
        for trade in trades
        if trade["entry_session"] in positions and trade["exit_session"] in positions
    ]
    average_winner = float(np.mean(winners)) if winners else None
    average_loser = float(np.mean(losers)) if losers else None
    payoff_ratio = (
        average_winner / abs(average_loser)
        if average_winner is not None and average_loser not in (None, 0.0)
        else None
    )
    return {
        "completed_trades": len(trades),
        "success_rate": round(len(winners) / len(trades), 10),
        "average_winner": round(average_winner, 10) if average_winner is not None else None,
        "average_loser": round(average_loser, 10) if average_loser is not None else None,
        "median_winner": round(float(np.median(winners)), 10) if winners else None,
        "median_loser": round(float(np.median(losers)), 10) if losers else None,
        "payoff_ratio": round(payoff_ratio, 10) if payoff_ratio is not None else None,
        "median_holding_sessions": int(round(float(np.median(holding_sessions)))) if holding_sessions else None,
    }


def _conditional_levels(
    df: pd.DataFrame,
    signal_frame: pd.DataFrame,
    qualified: bool,
    candidate: Candidate | None,
) -> dict[str, Any]:
    if not qualified:
        return {
            "available": False,
            "reason": "Suppressed because the pre-holdout winner did not qualify out of sample.",
            "setup_status": "NO QUALIFIED SETUP",
            "activation_condition": None,
            "execution_timing": None,
            "trigger": None,
            "invalidation": None,
            "one_r": None,
            "two_r": None,
            "backtested_exit_condition": None,
        }
    if candidate is None:
        raise ValueError("A qualified result requires a selected candidate")
    close = float(df["Close"].iloc[-1])
    state_active = bool(signal_frame["state"].iloc[-1])
    raw_trigger = float(signal_frame["entry_level"].iloc[-1]) if math.isfinite(float(signal_frame["entry_level"].iloc[-1])) else close
    price_triggered = candidate.family in {"breakout", "mean_reversion", "momentum"}
    trigger = close if state_active or not price_triggered else raw_trigger
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1])
    swing_low = float(df["Low"].tail(20).min())
    invalidation = max(swing_low, trigger - 2.0 * atr)
    if not math.isfinite(invalidation) or invalidation >= trigger:
        invalidation = trigger - 2.0 * atr
    risk = max(trigger - invalidation, trigger * 0.005)
    return {
        "available": True,
        "state": "IN MODEL" if state_active else "WAITING",
        "setup_status": "ACTIVE / NO FRESH TRIGGER" if state_active else "WAITING FOR ACTIVATION",
        "activation_condition": candidate.entry_rule,
        "activation_type": "PRICE LEVEL + CONDITION" if price_triggered else "INDICATOR CONDITION",
        "execution_timing": "Next session open after the condition is confirmed at the close",
        "fresh_entry": not state_active,
        "trigger": round(trigger, 4),
        "trigger_label": "Current planning reference" if state_active or not price_triggered else "Activation price reference",
        "invalidation": round(invalidation, 4),
        "one_r": round(trigger + risk, 4),
        "two_r": round(trigger + 2.0 * risk, 4),
        "risk_width": round(risk, 4),
        "risk_percent": round(risk / trigger, 8),
        "backtested_exit_condition": candidate.exit_rule,
        "backtested_exit_timing": "Next session open after the exit condition is confirmed at the close",
        "planning_reference_note": "Invalidation and 1R/2R are current planning references. The historical success statistics use the stated rule exit, not these fixed levels.",
        "logic": "Activation and exit follow the selected rule. Risk and R-levels translate the current chart into a bounded planning frame.",
    }


def _regime_matrix(df: pd.DataFrame, curve: pd.DataFrame, start: int, end: int) -> list[dict[str, Any]]:
    segment = df.iloc[start : end + 1].copy()
    close = df["Close"]
    segment["trend"] = np.where(close.rolling(200).mean().iloc[start : end + 1].values < segment["Close"].values, "ABOVE 200D", "BELOW 200D")
    vol = close.pct_change().rolling(20).std(ddof=0) * math.sqrt(252)
    threshold = float(vol.iloc[start : end + 1].median())
    segment["vol"] = np.where(vol.iloc[start : end + 1].values > threshold, "HIGH VOL", "LOW VOL")
    strategy_returns = pd.Series(curve["daily_return"].values, index=segment.index)
    result: list[dict[str, Any]] = []
    for trend in ("ABOVE 200D", "BELOW 200D"):
        for volatility in ("LOW VOL", "HIGH VOL"):
            mask = (segment["trend"] == trend) & (segment["vol"] == volatility)
            values = strategy_returns[mask].dropna()
            annualized = float(values.mean() * 252) if len(values) else 0.0
            result.append({
                "trend": trend,
                "volatility": volatility,
                "sessions": int(mask.sum()),
                "annualized_return": round(annualized, 8),
            })
    return result


def analyze(
    ticker: str,
    raw_df: pd.DataFrame,
    *,
    source: str,
    fetched_at: str,
    market: str | None = None,
) -> dict[str, Any]:
    security = resolve_security(ticker, market)
    profile = security.profile
    df = _canonical_frame(raw_df, profile)
    registry = candidate_registry()
    neighbors = _neighbor_map(registry)
    frames = {candidate.candidate_id: build_signal_frame(df, candidate) for candidate in registry}
    n = len(df)
    train_end = int(n * 0.50) - 1
    validation_end = int(n * 0.75) - 1
    windows = {
        "training": (0, train_end),
        "validation": (train_end + 1, validation_end),
        "holdout": (validation_end + 1, n - 1),
    }

    evaluations: dict[str, dict[str, Any]] = {}
    for candidate in registry:
        identifier = candidate.candidate_id
        window_metrics: dict[str, Metrics] = {}
        curves: dict[str, pd.DataFrame] = {}
        trades: dict[str, list[dict[str, Any]]] = {}
        for name, (start, end) in windows.items():
            metrics, curve, trade_rows = evaluate_window(
                df,
                frames[identifier]["state"],
                start,
                end,
                profile.base_cost_bps,
            )
            window_metrics[name] = metrics
            curves[name] = curve
            trades[name] = trade_rows
        stress: dict[str, dict[str, Any]] = {}
        for cost in profile.stress_costs_bps:
            validation_metrics, _, _ = evaluate_window(df, frames[identifier]["state"], *windows["validation"], cost)
            holdout_metrics, _, _ = evaluate_window(df, frames[identifier]["state"], *windows["holdout"], cost)
            stress[str(int(cost))] = {
                "validation_return": validation_metrics.net_return,
                "holdout_return": holdout_metrics.net_return,
            }
        evaluations[identifier] = {
            "candidate": asdict(candidate),
            "metrics": {name: _metric_dict(metrics) for name, metrics in window_metrics.items()},
            "raw_metrics": window_metrics,
            "curves": curves,
            "trades": trades,
            "stress": stress,
        }

    for candidate in registry:
        identifier = candidate.candidate_id
        neighbor_ids = neighbors[identifier]
        validation_positive = sum(evaluations[item]["raw_metrics"]["validation"].net_return > 0 for item in neighbor_ids)
        holdout_positive = sum(evaluations[item]["raw_metrics"]["holdout"].net_return > 0 for item in neighbor_ids)
        validation_ratio = validation_positive / len(neighbor_ids) if neighbor_ids else 1.0
        holdout_ratio = holdout_positive / len(neighbor_ids) if neighbor_ids else 1.0
        training = evaluations[identifier]["raw_metrics"]["training"]
        validation = evaluations[identifier]["raw_metrics"]["validation"]
        validation_pf = validation.profit_factor or 0.0
        gates = {
            "training_activity": training.trades >= 4,
            "training_net": training.net_return > -0.05,
            "validation_activity": validation.trades >= 3,
            "validation_net": validation.net_return > 0,
            "validation_profit_factor": validation_pf >= 1.05,
            "validation_drawdown": validation.max_drawdown <= 0.25,
            "double_cost_validation": evaluations[identifier]["stress"][str(int(profile.stress_costs_bps[1]))]["validation_return"] > 0,
            "neighbor_validation": validation_ratio >= 0.50,
        }
        eligible = all(gates.values())
        evaluations[identifier]["neighbor_ids"] = neighbor_ids
        evaluations[identifier]["neighbor_validation_ratio"] = round(validation_ratio, 4)
        evaluations[identifier]["neighbor_holdout_ratio"] = round(holdout_ratio, 4)
        evaluations[identifier]["preholdout_gates"] = gates
        evaluations[identifier]["eligible"] = eligible
        evaluations[identifier]["score"] = _score(validation, validation_ratio) if eligible else None

    ranked = sorted(
        (item for item in evaluations.values() if item["eligible"]),
        key=lambda item: (-float(item["score"]), item["candidate"]["candidate_id"]),
    )
    selected = ranked[0] if ranked else None
    qualified = False
    holdout_gates: dict[str, bool] = {}
    if selected:
        holdout = selected["raw_metrics"]["holdout"]
        holdout_pf = holdout.profit_factor or 0.0
        holdout_gates = {
            "holdout_activity": holdout.trades >= 3,
            "holdout_net": holdout.net_return > 0,
            "holdout_profit_factor": holdout_pf >= 1.05,
            "holdout_sharpe": holdout.sharpe > 0,
            "holdout_drawdown": holdout.max_drawdown <= 0.25,
            "double_cost_holdout": selected["stress"][str(int(profile.stress_costs_bps[1]))]["holdout_return"] > 0,
            "neighbor_holdout": selected["neighbor_holdout_ratio"] >= 0.50,
        }
        qualified = all(holdout_gates.values())

    context = _current_context(df)
    selected_id = selected["candidate"]["candidate_id"] if selected else None
    selected_frame = frames[selected_id] if selected_id else pd.DataFrame(index=df.index, data={"state": False, "entry_level": np.nan, "exit_level": np.nan})
    selected_candidate = next((candidate for candidate in registry if candidate.candidate_id == selected_id), None)
    levels = _conditional_levels(df, selected_frame, qualified, selected_candidate)

    train_count = sum(item["preholdout_gates"]["training_activity"] and item["preholdout_gates"]["training_net"] for item in evaluations.values())
    validation_count = sum(
        item["preholdout_gates"]["training_activity"]
        and item["preholdout_gates"]["training_net"]
        and item["preholdout_gates"]["validation_activity"]
        and item["preholdout_gates"]["validation_net"]
        and item["preholdout_gates"]["validation_profit_factor"]
        and item["preholdout_gates"]["validation_drawdown"]
        for item in evaluations.values()
    )
    robust_count = sum(bool(item["eligible"]) for item in evaluations.values())

    public_candidates: list[dict[str, Any]] = []
    for candidate in registry:
        item = evaluations[candidate.candidate_id]
        failed = [name for name, passed in item["preholdout_gates"].items() if not passed]
        public_candidates.append({
            "candidate": item["candidate"],
            "metrics": item["metrics"],
            "stress": item["stress"],
            "neighbor_ids": item["neighbor_ids"],
            "neighbor_validation_ratio": item["neighbor_validation_ratio"],
            "neighbor_holdout_ratio": item["neighbor_holdout_ratio"],
            "preholdout_gates": item["preholdout_gates"],
            "eligible": item["eligible"],
            "score": item["score"],
            "failed_preholdout_gates": failed,
        })

    selected_payload: dict[str, Any] | None = None
    if selected:
        holdout_curve = selected["curves"]["holdout"]
        selected_payload = {
            "candidate": selected["candidate"],
            "score": selected["score"],
            "metrics": selected["metrics"],
            "stress": selected["stress"],
            "neighbor_ids": selected["neighbor_ids"],
            "neighbor_validation_ratio": selected["neighbor_validation_ratio"],
            "neighbor_holdout_ratio": selected["neighbor_holdout_ratio"],
            "holdout_gates": holdout_gates,
            "qualified": qualified,
            "rule_state": "IN MODEL" if bool(selected_frame["state"].iloc[-1]) else "WAITING",
            "trade_profile": _trade_profile(df, selected["trades"]["holdout"]),
            "equity_curve": [
                {
                    "session": session,
                    "strategy": round(float(row["equity"]), 8),
                    "benchmark": round(float(row["benchmark"]), 8),
                }
                for session, row in holdout_curve.iloc[:: max(1, len(holdout_curve) // 180)].iterrows()
            ],
            "holdout_trades": selected["trades"]["holdout"],
            "regime_matrix": _regime_matrix(df, holdout_curve, *windows["holdout"]),
        }

    price_history = []
    price_tail = df.tail(504)
    sma50 = df["Close"].rolling(50).mean().reindex(price_tail.index)
    sma200 = df["Close"].rolling(200).mean().reindex(price_tail.index)
    for session in price_tail.index[:: max(1, len(price_tail) // 180)]:
        price_history.append({
            "session": session.date().isoformat(),
            "close": round(float(df.loc[session, "Close"]), 4),
            "sma50": round(float(sma50.loc[session]), 4) if math.isfinite(float(sma50.loc[session])) else None,
            "sma200": round(float(sma200.loc[session]), 4) if math.isfinite(float(sma200.loc[session])) else None,
        })

    return {
        "schema_version": "technical-analysis-brief-v2",
        "engine_version": VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "ticker": security.canonical_ticker,
        "display_ticker": security.display_ticker,
        "market": profile.code,
        "market_label": profile.label,
        "exchange": profile.exchange_label,
        "currency": profile.currency,
        "currency_symbol": profile.currency_symbol,
        "status": "qualified" if qualified else "no_robust_edge",
        "verdict": "OUT-OF-SAMPLE QUALIFIED" if qualified else "NO ROBUST EDGE",
        "disclaimer": DISCLAIMER,
        "data": {
            "source": source,
            "fetched_at": fetched_at,
            "adjustment_policy": "Adjusted daily OHLCV",
            "sessions": len(df),
            "start": df.index[0].date().isoformat(),
            "end": df.index[-1].date().isoformat(),
            "sha256": _frame_hash(df),
            "base_cost_bps_per_side": profile.base_cost_bps,
            "stress_costs_bps_per_side": list(profile.stress_costs_bps),
            "minimum_notional_turnover": profile.minimum_notional_turnover,
            "notional_turnover_currency": profile.turnover_label,
        },
        "windows": {
            name: {
                "start": df.index[start].date().isoformat(),
                "end": df.index[end].date().isoformat(),
                "sessions": end - start + 1,
                "purpose": "eligibility" if name == "training" else "selection" if name == "validation" else "untouched final gate",
            }
            for name, (start, end) in windows.items()
        },
        "current": context,
        "trial_count": len(registry),
        "survival_funnel": [
            {"label": "FIXED REGISTRY", "count": len(registry)},
            {"label": "TRAINING ACTIVE", "count": train_count},
            {"label": "VALIDATION PASS", "count": validation_count},
            {"label": "ROBUSTNESS PASS", "count": robust_count},
            {"label": "PRE-HOLDOUT WINNER", "count": 1 if selected else 0},
            {"label": "OOS QUALIFIED", "count": 1 if qualified else 0},
        ],
        "selected": selected_payload,
        "conditional_levels": levels,
        "candidates": public_candidates,
        "price_history": price_history,
        "limitations": [
            "Historical adjusted daily data; not an exchange-grade point-in-time feed.",
            "Current-constituent research can retain survivorship bias.",
            "Daily bars, simplified costs, no taxes, market impact, or partial fills.",
            f"{len(registry)} pre-declared rules were attempted; selection bias cannot be eliminated.",
        ],
    }


def read_ohlcv_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["Date"])
    return frame.set_index("Date")


def write_analysis(
    ticker: str,
    input_csv: Path,
    output_json: Path,
    *,
    source: str,
    fetched_at: str,
    market: str | None = None,
) -> dict[str, Any]:
    payload = analyze(
        ticker,
        read_ohlcv_csv(input_csv),
        source=source,
        fetched_at=fetched_at,
        market=market,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload
