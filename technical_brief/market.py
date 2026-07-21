from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    code: str
    label: str
    currency: str
    currency_symbol: str
    exchange_label: str
    base_cost_bps: float
    stress_costs_bps: tuple[float, float, float]
    minimum_notional_turnover: float
    turnover_label: str


@dataclass(frozen=True)
class Security:
    raw_ticker: str
    canonical_ticker: str
    display_ticker: str
    profile: MarketProfile


US = MarketProfile(
    code="us",
    label="United States",
    currency="USD",
    currency_symbol="$",
    exchange_label="US",
    base_cost_bps=10.0,
    stress_costs_bps=(10.0, 20.0, 40.0),
    minimum_notional_turnover=25_000_000.0,
    turnover_label="USD",
)

INDIA = MarketProfile(
    code="in",
    label="India",
    currency="INR",
    currency_symbol="₹",
    exchange_label="NSE/BSE",
    base_cost_bps=15.0,
    stress_costs_bps=(15.0, 30.0, 60.0),
    minimum_notional_turnover=1_000_000_000.0,
    turnover_label="INR",
)


def resolve_security(ticker: str, market: str | None = None) -> Security:
    raw = ticker.strip().upper()
    if not raw:
        raise ValueError("Ticker is required")
    requested = market.lower() if market else None
    if requested not in (None, "us", "in"):
        raise ValueError("Market must be 'us' or 'in'")

    inferred_india = raw.endswith((".NS", ".BO")) or raw.isdigit()
    profile = INDIA if requested == "in" or (requested is None and inferred_india) else US
    if profile.code == "in":
        if raw.endswith((".NS", ".BO")):
            canonical = raw
        elif raw.isdigit() and len(raw) == 6:
            canonical = f"{raw}.BO"
        else:
            canonical = f"{raw}.NS"
        display = canonical.rsplit(".", 1)[0]
    else:
        canonical = raw.replace(".", "-") if raw.count(".") == 1 else raw
        display = raw
    return Security(raw, canonical, display, profile)


def format_price(value: float, profile: MarketProfile, digits: int = 2) -> str:
    return f"{profile.currency_symbol}{value:,.{digits}f}"
