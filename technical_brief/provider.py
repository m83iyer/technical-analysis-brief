from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from .market import Security


class YahooResearchProvider:
    """Read-only adapter that returns adjusted daily OHLCV research data."""

    source = "Yahoo Finance via yfinance"

    def fetch(self, security: Security) -> tuple[pd.DataFrame, str, str]:
        frame = yf.download(
            security.canonical_ticker,
            period="max",
            interval="1d",
            auto_adjust=True,
            actions=False,
            progress=False,
            threads=False,
        )
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        required = ["Open", "High", "Low", "Close", "Volume"]
        if frame.empty or any(column not in frame.columns for column in required):
            raise ValueError(f"No usable adjusted daily OHLCV data for {security.canonical_ticker}")
        fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return frame[required], self.source, fetched_at
