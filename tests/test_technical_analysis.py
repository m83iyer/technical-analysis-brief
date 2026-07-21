from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import fitz
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from technical_analysis import (  # noqa: E402
    DISCLAIMER,
    analyze,
    build_signal_frame,
    candidate_registry,
    evaluate_window,
)
from technical_brief.market import resolve_security  # noqa: E402
from technical_brief.render import render  # noqa: E402


def synthetic_history(sessions: int = 2_520) -> pd.DataFrame:
    index = pd.bdate_range("2015-01-02", periods=sessions)
    values = []
    prior = 100.0
    for number in range(sessions):
        regime = 0.00045 if number < 1_350 else -0.00008 if number < 1_650 else 0.00035
        cycle = 0.005 * math.sin(number / 18.0) + 0.002 * math.sin(number / 61.0)
        gap = 0.001 * math.sin(number / 13.0)
        open_price = prior * math.exp(gap)
        close = open_price * math.exp(regime + cycle)
        high = max(open_price, close) * 1.006
        low = min(open_price, close) * 0.994
        values.append((open_price, high, low, close, 4_000_000 + (number % 19) * 30_000))
        prior = close
    return pd.DataFrame(values, index=index, columns=["Open", "High", "Low", "Close", "Volume"])


class TechnicalAnalysisTests(unittest.TestCase):
    def test_market_resolver_handles_nse_bse_and_us_symbols(self):
        self.assertEqual(resolve_security("RELIANCE", "in").canonical_ticker, "RELIANCE.NS")
        self.assertEqual(resolve_security("500325", "in").canonical_ticker, "500325.BO")
        self.assertEqual(resolve_security("TCS.NS").profile.currency, "INR")
        self.assertEqual(resolve_security("BRK.B", "us").canonical_ticker, "BRK-B")

    def test_registry_is_frozen_and_unique(self):
        registry = candidate_registry()
        self.assertEqual(len(registry), 15)
        self.assertEqual(len({candidate.candidate_id for candidate in registry}), 15)
        self.assertEqual({candidate.family for candidate in registry}, {"breakout", "mean_reversion", "momentum", "trend"})

    def test_close_signal_fills_next_open(self):
        index = pd.bdate_range("2024-01-02", periods=5)
        frame = pd.DataFrame(
            {
                "Open": [10.0, 20.0, 21.0, 30.0, 31.0],
                "High": [10.5, 20.5, 21.5, 30.5, 31.5],
                "Low": [9.5, 19.5, 20.5, 29.5, 30.5],
                "Close": [10.0, 20.0, 21.0, 30.0, 31.0],
                "Volume": [5_000_000] * 5,
            },
            index=index,
        )
        close_state = pd.Series([True, True, False, False, False], index=index)
        _, _, trades = evaluate_window(frame, close_state, 0, 4, 0.0)
        self.assertEqual(trades[0]["entry_session"], index[1].date().isoformat())
        self.assertEqual(trades[0]["entry_price"], 20.0)
        self.assertEqual(trades[0]["exit_session"], index[3].date().isoformat())
        self.assertEqual(trades[0]["exit_price"], 30.0)

    def test_insufficient_history_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Insufficient history"):
            analyze("TEST", synthetic_history(1_000), source="fixture", fetched_at="2026-07-21T00:00:00Z")

    def test_discarded_legacy_provider_anomaly_does_not_poison_retained_window(self):
        frame = synthetic_history(4_000)
        frame.iloc[0, frame.columns.get_loc("High")] = frame.iloc[0]["Low"] * 0.5
        payload = analyze("TEST", frame, source="fixture", fetched_at="2026-07-21T00:00:00Z")
        self.assertEqual(payload["data"]["sessions"], 3_780)

    def test_future_holdout_change_cannot_change_preholdout_winner(self):
        frame = synthetic_history()
        first = analyze("TEST", frame, source="fixture", fetched_at="2026-07-21T00:00:00Z")
        altered = frame.copy()
        holdout_start = int(len(altered.tail(3_780)) * 0.75)
        base_index = altered.index[-len(altered.tail(3_780)) + holdout_start]
        affected = altered.index >= base_index
        shocks = np.exp(np.linspace(0.0, 1.0, affected.sum()))
        for column in ("Open", "High", "Low", "Close"):
            altered.loc[affected, column] = altered.loc[affected, column].values * shocks
        second = analyze("TEST", altered, source="fixture", fetched_at="2026-07-21T00:00:00Z")
        first_id = first["selected"]["candidate"]["candidate_id"] if first["selected"] else None
        second_id = second["selected"]["candidate"]["candidate_id"] if second["selected"] else None
        self.assertEqual(first_id, second_id)

    def test_receipt_discloses_trials_costs_and_boundary(self):
        payload = analyze("TEST", synthetic_history(), source="fixture", fetched_at="2026-07-21T00:00:00Z")
        self.assertEqual(payload["trial_count"], 15)
        self.assertEqual(payload["data"]["base_cost_bps_per_side"], 10.0)
        self.assertEqual(payload["data"]["stress_costs_bps_per_side"], [10.0, 20.0, 40.0])
        self.assertEqual(payload["disclaimer"], DISCLAIMER)
        self.assertEqual(DISCLAIMER, "Research output — not a recommendation. The reader decides whether to act.")
        self.assertEqual(payload["windows"]["holdout"]["purpose"], "untouched final gate")

    def test_india_receipt_uses_inr_costs_and_notional_liquidity(self):
        frame = synthetic_history()
        frame["Volume"] = frame["Volume"] * 5
        payload = analyze(
            "RELIANCE.NS",
            frame,
            source="fixture",
            fetched_at="2026-07-21T00:00:00Z",
            market="in",
        )
        self.assertEqual(payload["ticker"], "RELIANCE.NS")
        self.assertEqual(payload["currency"], "INR")
        self.assertEqual(payload["data"]["base_cost_bps_per_side"], 15.0)
        self.assertEqual(payload["data"]["stress_costs_bps_per_side"], [15.0, 30.0, 60.0])
        self.assertIn("minimum_notional_turnover", payload["data"])
        self.assertNotIn("minimum_dollar_volume", payload["data"])

    def test_india_render_is_one_page_inr_only_and_deterministic(self):
        frame = synthetic_history()
        frame["Volume"] = frame["Volume"] * 5
        payload = analyze(
            "RELIANCE.NS",
            frame,
            source="fixture",
            fetched_at="2026-07-21T00:00:00Z",
            market="in",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sidecar = root / "evidence.json"
            first_pdf, first_png = root / "first.pdf", root / "first.png"
            second_pdf, second_png = root / "second.pdf", root / "second.png"
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            render(sidecar, first_pdf, first_png)
            render(sidecar, second_pdf, second_png)
            self.assertEqual(first_pdf.read_bytes(), second_pdf.read_bytes())
            self.assertEqual(first_png.read_bytes(), second_png.read_bytes())
            document = fitz.open(first_pdf)
            self.assertEqual(document.page_count, 1)
            text = document[0].get_text()
            self.assertIn("₹", text)
            self.assertNotIn("$", text)
            pixmap = fitz.Pixmap(first_png)
            self.assertEqual((pixmap.width, pixmap.height), (1600, 2000))

    def test_levels_exist_only_for_qualified_result(self):
        payload = analyze("TEST", synthetic_history(), source="fixture", fetched_at="2026-07-21T00:00:00Z")
        self.assertEqual(payload["conditional_levels"]["available"], payload["status"] == "qualified")
        if payload["status"] != "qualified":
            self.assertIsNone(payload["conditional_levels"]["trigger"])

    def test_decision_contract_pairs_success_rate_with_payoff(self):
        payload = analyze("TEST", synthetic_history(), source="fixture", fetched_at="2026-07-21T00:00:00Z")
        self.assertEqual(payload["schema_version"], "technical-analysis-brief-v2")
        if payload["selected"]:
            profile = payload["selected"]["trade_profile"]
            self.assertEqual(profile["completed_trades"], payload["selected"]["metrics"]["holdout"]["trades"])
            self.assertGreaterEqual(profile["success_rate"], 0.0)
            self.assertLessEqual(profile["success_rate"], 1.0)
        levels = payload["conditional_levels"]
        if levels["available"]:
            self.assertIn(levels["setup_status"], {"ACTIVE / NO FRESH TRIGGER", "WAITING FOR ACTIVATION"})
            self.assertTrue(levels["activation_condition"])
            self.assertTrue(levels["backtested_exit_condition"])
            self.assertIn("not these fixed levels", levels["planning_reference_note"])

    def test_signal_frame_is_causal_under_future_mutation(self):
        frame = synthetic_history()
        candidate = candidate_registry()[0]
        baseline = build_signal_frame(frame, candidate)
        changed = frame.copy()
        changed.iloc[-1, changed.columns.get_loc("Close")] *= 4
        changed.iloc[-1, changed.columns.get_loc("High")] *= 4
        changed_signal = build_signal_frame(changed, candidate)
        pd.testing.assert_frame_equal(baseline.iloc[:-1], changed_signal.iloc[:-1])


if __name__ == "__main__":
    unittest.main()
