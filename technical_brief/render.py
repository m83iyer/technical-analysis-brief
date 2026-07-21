#!/usr/bin/env python3
"""Render the Stockcentric ticker-level technical evidence one-pager."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import fitz
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
PAGE_W = 900
PAGE_H = 1125
EXPORT_W = 1600
EXPORT_H = 2000
MARGIN = 36

BG = HexColor("#EAF4E8")
SURFACE = HexColor("#F8FBF4")
NAVY = HexColor("#15263E")
INK = HexColor("#172132")
TEAL = HexColor("#167B77")
MINT = HexColor("#79B8A5")
BLUE = HexColor("#3F6FB5")
PLUM = HexColor("#76538C")
GOLD = HexColor("#B98018")
CORAL = HexColor("#C9593A")
MUTED = HexColor("#5B6878")
LINE = HexColor("#BFD5BF")
PALE = HexColor("#E0EBDE")
SOFT_CORAL = HexColor("#F3D8CE")
SOFT_GOLD = HexColor("#F1E3C5")


def _font_path(preferred: str, bundled: str) -> str:
    preferred_path = Path(preferred)
    return str(preferred_path if preferred_path.is_file() else Path(__file__).parent / "fonts" / bundled)


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Display", _font_path("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf", "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Body", _font_path("/System/Library/Fonts/Supplemental/Arial.ttf", "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("BodyBold", _font_path("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", _font_path("/System/Library/Fonts/SFNSMono.ttf", "DejaVuSansMono.ttf")))
    pdfmetrics.registerFont(TTFont("Currency", str(Path(__file__).parent / "fonts" / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("CurrencyBold", str(Path(__file__).parent / "fonts" / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("CurrencyMono", str(Path(__file__).parent / "fonts" / "DejaVuSansMono.ttf")))


def money(data: dict, value: float, digits: int = 2) -> str:
    return f"{data.get('currency_symbol', '$')}{value:,.{digits}f}"


def money_font(data: dict, font: str) -> str:
    if data.get("currency") != "INR":
        return font
    return {"Body": "Currency", "BodyBold": "CurrencyBold", "Display": "CurrencyBold", "Mono": "CurrencyMono"}.get(font, font)


def panel(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setFillColor(HexColor("#D8E6D7"))
    c.roundRect(x + 3, y - 3, w, h, 9, stroke=0, fill=1)
    c.setFillColor(SURFACE)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.roundRect(x, y, w, h, 9, stroke=1, fill=1)


def fit_text(text: str, font: str, size: float, max_width: float) -> float:
    while size > 5 and pdfmetrics.stringWidth(text, font, size) > max_width:
        size -= 0.25
    return size


def wrapped_lines(text: str, font: str, size: float, max_width: float, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    consumed = 0
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
            consumed += 1
            continue
        lines.append(current)
        if len(lines) >= max_lines - 1:
            break
        current = word
        consumed += 1
    if current and len(lines) < max_lines:
        remaining = " ".join(words[sum(len(line.split()) for line in lines):])
        original = remaining
        while remaining and pdfmetrics.stringWidth(remaining, font, size) > max_width:
            remaining = remaining[:-1]
        if remaining != original:
            remaining = remaining.rstrip(" .,;:") + "..."
        lines.append(remaining)
    return lines


def section_title(c: canvas.Canvas, x: float, y: float, w: float, number: str, title: str, source: str) -> None:
    c.setFillColor(TEAL)
    c.circle(x + 7, y - 1, 7, stroke=0, fill=1)
    c.setFillColor(SURFACE)
    c.setFont("Mono", 6.6)
    c.drawCentredString(x + 7, y - 3.3, number)
    c.setFillColor(INK)
    c.setFont("BodyBold", fit_text(title, "BodyBold", 11.8, w - 85))
    c.drawString(x + 21, y - 4, title)
    c.setFillColor(MUTED)
    c.setFont("Mono", 5.7)
    c.drawRightString(x + w, y - 4, source.upper())


def insight_band(c: canvas.Canvas, x: float, y: float, w: float, text: str, tone=TEAL) -> None:
    c.setFillColor(PALE if tone == TEAL else SOFT_CORAL)
    c.roundRect(x, y, w, 37, 5, stroke=0, fill=1)
    c.setFillColor(tone)
    c.setFont("BodyBold", 7.4)
    c.drawString(x + 9, y + 23, "KEY INSIGHT")
    c.setFillColor(INK)
    c.setFont("BodyBold", 8.5)
    for index, line in enumerate(wrapped_lines(text, "BodyBold", 8.5, w - 90, 2)):
        c.drawString(x + 81, y + 23 - index * 10.8, line)


def pct(value: float | None, digits: int = 1) -> str:
    return "N/A" if value is None else f"{value * 100:.{digits}f}%"


def multiple(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}x"


def metric_color(value: float, good: float = 0.0) -> object:
    return TEAL if value > good else CORAL if value < good else GOLD


def _axis(values: list[float]) -> tuple[float, float]:
    clean = [value for value in values if math.isfinite(value)] or [0.0, 1.0]
    low, high = min(clean), max(clean)
    if low == high:
        pad = max(abs(low) * 0.1, 1.0)
        return low - pad, high + pad
    pad = (high - low) * 0.08
    return low - pad, high + pad


def _plot_line(c: canvas.Canvas, points: list[tuple[float, float]], color: object, width: float = 1.5) -> None:
    if len(points) < 2:
        return
    path = c.beginPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.drawPath(path, stroke=1, fill=0)


def price_structure_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 14, y + h - 19, w - 28, "01", "Two-year price structure", "Adjusted daily")
    history = data["price_history"]
    closes = [float(item["close"]) for item in history]
    ma50 = [float(item["sma50"]) for item in history if item.get("sma50") is not None]
    ma200 = [float(item["sma200"]) for item in history if item.get("sma200") is not None]
    level_values = [value for key, value in data["conditional_levels"].items() if key in {"trigger", "invalidation", "one_r", "two_r"} and isinstance(value, (int, float))]
    low, high = _axis(closes + ma50 + ma200 + level_values)
    chart_x, chart_y = x + 47, y + 58
    chart_w, chart_h = w - 68, h - 112

    for fraction in (0.0, 0.25, 0.50, 0.75, 1.0):
        gy = chart_y + fraction * chart_h
        value = low + fraction * (high - low)
        c.setStrokeColor(PALE)
        c.setLineWidth(0.6)
        c.line(chart_x, gy, chart_x + chart_w, gy)
        c.setFillColor(MUTED)
        c.setFont(money_font(data, "Mono"), 5.2)
        c.drawRightString(chart_x - 6, gy - 2, money(data, value, 0))

    def points_for(key: str) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for index, item in enumerate(history):
            value = item.get(key)
            if value is None:
                continue
            px = chart_x + chart_w * index / max(1, len(history) - 1)
            py = chart_y + chart_h * (float(value) - low) / (high - low)
            result.append((px, py))
        return result

    _plot_line(c, points_for("close"), NAVY, 2.2)
    _plot_line(c, points_for("sma50"), TEAL, 1.5)
    _plot_line(c, points_for("sma200"), GOLD, 1.5)

    levels = data["conditional_levels"]
    if levels.get("available"):
        for label, key, color in (("2R", "two_r", BLUE), ("1R", "one_r", PLUM), ("TRIGGER", "trigger", TEAL), ("INVALID", "invalidation", CORAL)):
            value = float(levels[key])
            ly = chart_y + chart_h * (value - low) / (high - low)
            if chart_y <= ly <= chart_y + chart_h:
                c.setStrokeColor(color)
                c.setDash(3, 2)
                c.setLineWidth(0.8)
                c.line(chart_x, ly, chart_x + chart_w, ly)
                c.setDash()
                c.setFillColor(color)
                c.setFont(money_font(data, "Mono"), 5.2)
                c.drawRightString(chart_x + chart_w, ly + 3, f"{label} {money(data, value)}")

    for offset, label, color in ((0, "PRICE", NAVY), (43, "50D", TEAL), (75, "200D", GOLD)):
        lx = chart_x + offset
        c.setStrokeColor(color)
        c.setLineWidth(2)
        c.line(lx, y + h - 42, lx + 14, y + h - 42)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.3)
        c.drawString(lx + 18, y + h - 44, label)

    dates = [history[0]["session"], history[len(history) // 2]["session"], history[-1]["session"]]
    for fraction, label in zip((0, 0.5, 1), dates):
        c.setFillColor(MUTED)
        c.setFont("Mono", 5)
        c.drawCentredString(chart_x + chart_w * fraction, chart_y - 12, label[:7])

    current = data["current"]
    if levels.get("available"):
        text = f"Qualified rule: {data['selected']['rule_state'].lower()}. Price: {money(data, current['close'])}. Levels are conditional model coordinates, not instructions."
        tone = TEAL
    else:
        text = "The selected pre-holdout rule did not clear every final gate, so trigger, invalidation and R references are suppressed."
        tone = CORAL
    insight_band(c, x + 11, y + 10, w - 22, text, tone=tone)


def verdict_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 14, y + h - 19, w - 28, "02", "Evidence verdict", "Pre-holdout lock")
    qualified = data["status"] == "qualified"
    color = TEAL if qualified else CORAL
    c.setFillColor(color)
    c.roundRect(x + 14, y + h - 76, w - 28, 37, 6, stroke=0, fill=1)
    c.setFillColor(SURFACE)
    c.setFont("Display", fit_text(data["verdict"], "Display", 25, w - 45))
    c.drawString(x + 24, y + h - 67, data["verdict"])

    selected = data.get("selected")
    if selected:
        rows = [
            ("PRE-HOLDOUT RULE", selected["candidate"]["label"]),
            ("VALIDATION SCORE", f"{selected['score']:.1f} / 100"),
            ("OOS PERIOD", f"{data['windows']['holdout']['start']} to {data['windows']['holdout']['end']}"),
            ("OOS PROFIT FACTOR", multiple(selected["metrics"]["holdout"]["profit_factor"])),
            ("OOS SHARPE", f"{selected['metrics']['holdout']['sharpe']:.2f}"),
            ("OOS MAX DRAWDOWN", pct(selected["metrics"]["holdout"]["max_drawdown"])),
            ("OOS TRADES", str(selected["metrics"]["holdout"]["trades"])),
        ]
        for index, (label, value) in enumerate(rows):
            row_y = y + h - 101 - index * 18
            c.setFillColor(MUTED)
            c.setFont("Mono", 5.7)
            c.drawString(x + 16, row_y, label)
            c.setFillColor(INK)
            c.setFont("BodyBold", fit_text(value, "BodyBold", 8.6, w - 137))
            c.drawRightString(x + w - 16, row_y, value)
            c.setStrokeColor(PALE)
            c.setLineWidth(0.5)
            c.line(x + 16, row_y - 5, x + w - 16, row_y - 5)
        gate_text = "All seven holdout gates passed." if qualified else "Failed: " + ", ".join(label.replace("_", " ") for label, passed in selected["holdout_gates"].items() if not passed)
    else:
        c.setFillColor(INK)
        c.setFont("BodyBold", 10)
        c.drawString(x + 16, y + h - 112, "No rule cleared the validation and robustness gates.")
        gate_text = "The engine stopped before opening the untouched holdout."

    c.setFillColor(SOFT_CORAL if not qualified else PALE)
    c.roundRect(x + 14, y + 10, w - 28, 42, 6, stroke=0, fill=1)
    c.setFillColor(color)
    c.setFont("BodyBold", 6.4)
    c.drawString(x + 23, y + 39, "WHY THIS VERDICT")
    c.setFillColor(INK)
    c.setFont("BodyBold", 7.6)
    for index, line in enumerate(wrapped_lines(gate_text, "BodyBold", 7.6, w - 46, 2)):
        c.drawString(x + 23, y + 26 - index * 9, line)


def survival_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 13, y + h - 18, w - 26, "03", "Strategy survival", f"{data['trial_count']} frozen trials")
    funnel = data["survival_funnel"]
    maximum = max(item["count"] for item in funnel) or 1
    top = y + h - 51
    for index, item in enumerate(funnel):
        by = top - index * 26
        width = max(6, (w - 100) * item["count"] / maximum)
        color = TEAL if index < len(funnel) - 1 else TEAL if item["count"] else CORAL
        c.setFillColor(PALE)
        c.roundRect(x + 90, by - 8, w - 106, 12, 3, stroke=0, fill=1)
        c.setFillColor(color)
        c.roundRect(x + 90, by - 8, width, 12, 3, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.2)
        c.drawRightString(x + 82, by - 5, item["label"])
        c.setFillColor(INK)
        c.setFont("Display", 12)
        c.drawRightString(x + w - 12, by - 6, str(item["count"]))
    selected = data.get("selected")
    insight = "Selection stopped cleanly before holdout." if not selected else f"{selected['candidate']['label']} was frozen before the final OOS reveal."
    insight_band(c, x + 10, y + 9, w - 20, insight, tone=TEAL if selected else CORAL)


def equity_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 13, y + h - 18, w - 26, "04", "Untouched holdout path", "Strategy vs benchmark")
    selected = data.get("selected")
    if not selected:
        c.setFillColor(MUTED)
        c.setFont("BodyBold", 12)
        c.drawCentredString(x + w / 2, y + h / 2, "NO PRE-HOLDOUT WINNER")
        insight_band(c, x + 10, y + 9, w - 20, "No equity comparison is shown because validation produced no eligible rule.", tone=CORAL)
        return
    curve = selected["equity_curve"]
    strategy = [float(item["strategy"]) for item in curve]
    benchmark = [float(item["benchmark"]) for item in curve]
    low, high = _axis(strategy + benchmark + [1.0])
    chart_x, chart_y, chart_w, chart_h = x + 38, y + 60, w - 58, h - 116
    for fraction in (0, 0.5, 1):
        gy = chart_y + fraction * chart_h
        c.setStrokeColor(PALE)
        c.line(chart_x, gy, chart_x + chart_w, gy)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5)
        c.drawRightString(chart_x - 5, gy - 2, f"{low + fraction * (high - low):.1f}x")
    def make(values: list[float]) -> list[tuple[float, float]]:
        return [
            (chart_x + chart_w * index / max(1, len(values) - 1), chart_y + chart_h * (value - low) / (high - low))
            for index, value in enumerate(values)
        ]
    _plot_line(c, make(strategy), TEAL, 2.2)
    _plot_line(c, make(benchmark), NAVY, 1.5)
    for values, label, color, offset in ((strategy, "RULE", TEAL, 8), (benchmark, "B&H", NAVY, -9)):
        px, py = make(values)[-1]
        c.setFillColor(color)
        c.setFont("BodyBold", 6.5)
        c.drawRightString(px, py + offset, f"{label} {values[-1]:.2f}x")
    dates = [curve[0]["session"], curve[-1]["session"]]
    for fraction, label in ((0, dates[0]), (1, dates[1])):
        c.setFillColor(MUTED)
        c.setFont("Mono", 5)
        c.drawCentredString(chart_x + chart_w * fraction, chart_y - 12, label[:7])
    oos = selected["metrics"]["holdout"]
    text = f"Rule: {pct(oos['net_return'])} after costs. Buy-and-hold: {pct(oos['benchmark_return'])}. Max drawdown: {pct(oos['max_drawdown'])}."
    insight_band(c, x + 10, y + 9, w - 20, text, tone=TEAL if selected["qualified"] else CORAL)


def regime_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 13, y + h - 18, w - 26, "05", "Regime map", "OOS annualized")
    selected = data.get("selected")
    if not selected:
        c.setFillColor(MUTED)
        c.setFont("BodyBold", 11)
        c.drawCentredString(x + w / 2, y + h / 2, "NOT AVAILABLE")
        insight_band(c, x + 10, y + 9, w - 20, "Regime attribution requires a pre-holdout winner.", tone=CORAL)
        return
    matrix = {(item["trend"], item["volatility"]): item for item in selected["regime_matrix"]}
    grid_x, grid_y = x + 58, y + 73
    cell_w, cell_h = (w - 76) / 2, 55
    for row, trend in enumerate(("ABOVE 200D", "BELOW 200D")):
        for column, volatility in enumerate(("LOW VOL", "HIGH VOL")):
            item = matrix[(trend, volatility)]
            value = float(item["annualized_return"])
            color = HexColor("#B9D9C8") if value > 0.05 else HexColor("#DDEAD5") if value >= 0 else SOFT_CORAL
            cx = grid_x + column * cell_w
            cy = grid_y + (1 - row) * cell_h
            c.setFillColor(color)
            c.roundRect(cx, cy, cell_w - 5, cell_h - 5, 5, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("Display", 19)
            c.drawCentredString(cx + (cell_w - 5) / 2, cy + 25, pct(value))
            c.setFillColor(MUTED)
            c.setFont("Mono", 4.8)
            c.drawCentredString(cx + (cell_w - 5) / 2, cy + 10, f"{item['sessions']} SESSIONS")
    for column, label in enumerate(("LOW VOL", "HIGH VOL")):
        c.setFillColor(MUTED)
        c.setFont("Mono", 5)
        c.drawCentredString(grid_x + column * cell_w + (cell_w - 5) / 2, grid_y + 2 * cell_h + 4, label)
    for row, label in enumerate(("ABOVE 200D", "BELOW 200D")):
        c.saveState()
        c.translate(x + 20, grid_y + (1 - row) * cell_h + 8)
        c.rotate(90)
        c.setFillColor(MUTED)
        c.setFont("Mono", 4.7)
        c.drawString(0, 0, label)
        c.restoreState()
    best = max(selected["regime_matrix"], key=lambda item: item["annualized_return"])
    insight_band(c, x + 10, y + 9, w - 20, f"Best OOS cell: {best['trend'].lower()} / {best['volatility'].lower()}, {pct(best['annualized_return'])} annualized.", tone=TEAL if best["annualized_return"] > 0 else CORAL)


def scorecard_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 13, y + h - 18, w - 26, "06", "OOS scorecard", "After 10 bps / side")
    selected = data.get("selected")
    if not selected:
        c.setFillColor(MUTED)
        c.setFont("BodyBold", 11)
        c.drawCentredString(x + w / 2, y + h / 2, "NO ELIGIBLE RULE")
        insight_band(c, x + 10, y + 9, w - 20, "No headline metric is substituted for missing evidence.", tone=CORAL)
        return
    metrics = selected["metrics"]["holdout"]
    rows = [
        ("NET RETURN", pct(metrics["net_return"]), min(max(metrics["net_return"] / 0.30, 0), 1), metrics["net_return"] > 0),
        ("SHARPE", f"{metrics['sharpe']:.2f}", min(max(metrics["sharpe"] / 1.5, 0), 1), metrics["sharpe"] > 0),
        ("PROFIT FACTOR", multiple(metrics["profit_factor"]), min(max(((metrics["profit_factor"] or 0) - 1) / 1.5, 0), 1), (metrics["profit_factor"] or 0) >= 1.05),
        ("MAX DRAWDOWN", pct(metrics["max_drawdown"]), min(max(1 - metrics["max_drawdown"] / 0.25, 0), 1), metrics["max_drawdown"] <= 0.25),
        ("EXPECTANCY", pct(metrics["expectancy"]), min(max(metrics["expectancy"] / 0.04, 0), 1), metrics["expectancy"] > 0),
        ("COMPLETED TRADES", str(metrics["trades"]), min(metrics["trades"] / 12, 1), metrics["trades"] >= 3),
    ]
    top = y + h - 54
    for index, (label, value, strength, passed) in enumerate(rows):
        by = top - index * 27
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.4)
        c.drawString(x + 14, by, label)
        c.setFillColor(PALE)
        c.roundRect(x + 103, by - 3, w - 158, 9, 3, stroke=0, fill=1)
        c.setFillColor(TEAL if passed else CORAL)
        c.roundRect(x + 103, by - 3, max(4, (w - 158) * strength), 9, 3, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("BodyBold", 7.5)
        c.drawRightString(x + w - 14, by, value)
    insight_band(c, x + 10, y + 9, w - 20, "Win rate is reported, not gated. Payoff and drawdown decide the result.", tone=TEAL)


def robustness_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    costs = tuple(str(int(value)) for value in data["data"]["stress_costs_bps_per_side"])
    section_title(c, x + 13, y + h - 18, w - 26, "07", "Cost and parameter stress", " / ".join(costs) + " bps")
    selected = data.get("selected")
    if not selected:
        c.setFillColor(MUTED)
        c.setFont("BodyBold", 11)
        c.drawCentredString(x + w / 2, y + h / 2, "NO PRE-HOLDOUT WINNER")
        insight_band(c, x + 10, y + 9, w - 20, "Stress panels remain empty when selection stops early.", tone=CORAL)
        return
    grid_x, grid_y = x + 82, y + 98
    cell_w, cell_h = 51, 35
    for column, cost in enumerate(costs):
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.2)
        c.drawCentredString(grid_x + column * cell_w + 23, grid_y + 2 * cell_h + 8, f"{cost} BPS")
    for row, (window, key) in enumerate((("VALIDATION", "validation_return"), ("HOLDOUT", "holdout_return"))):
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.1)
        c.drawRightString(grid_x - 7, grid_y + (1 - row) * cell_h + 12, window)
        for column, cost in enumerate(costs):
            value = float(selected["stress"][cost][key])
            cx = grid_x + column * cell_w
            cy = grid_y + (1 - row) * cell_h
            c.setFillColor(HexColor("#B9D9C8") if value > 0 else SOFT_CORAL)
            c.roundRect(cx, cy, cell_w - 5, cell_h - 5, 4, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont("BodyBold", 7.2)
            c.drawCentredString(cx + (cell_w - 5) / 2, cy + 12, pct(value))
    c.setFillColor(PALE)
    c.roundRect(x + 18, y + 54, w - 36, 32, 5, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Mono", 5.2)
    c.drawString(x + 27, y + 72, "NEIGHBOR PARAMETERS POSITIVE")
    c.setFillColor(INK)
    c.setFont("Display", 15)
    c.drawRightString(x + w - 27, y + 65, f"VAL {pct(selected['neighbor_validation_ratio'], 0)}  /  OOS {pct(selected['neighbor_holdout_ratio'], 0)}")
    worst_cost = costs[-1]
    worst = float(selected["stress"][worst_cost]["holdout_return"])
    insight_band(c, x + 10, y + 9, w - 20, f"{worst_cost} bps per side OOS: {pct(worst)}. Positive neighbors: {pct(selected['neighbor_holdout_ratio'], 0)}.", tone=TEAL if worst > 0 else CORAL)


def levels_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 13, y + h - 18, w - 26, "08", "Conditional rule levels", "Model coordinates")
    levels = data["conditional_levels"]
    selected = data.get("selected")
    if not levels.get("available"):
        c.setFillColor(CORAL)
        c.setFont("Display", 25)
        c.drawString(x + 18, y + h - 78, "LEVELS SUPPRESSED")
        c.setFillColor(INK)
        c.setFont("BodyBold", 8)
        for index, line in enumerate(wrapped_lines(levels["reason"], "BodyBold", 8, w - 36, 5)):
            c.drawString(x + 18, y + h - 105 - index * 11, line)
        insight_band(c, x + 10, y + 9, w - 20, "No qualified edge. Conditional price levels stay blank.", tone=CORAL)
        return
    entries = [
        ("2R REFERENCE", float(levels["two_r"]), BLUE),
        ("1R REFERENCE", float(levels["one_r"]), PLUM),
        ("TRIGGER REFERENCE", float(levels["trigger"]), TEAL),
        ("INVALIDATION", float(levels["invalidation"]), CORAL),
    ]
    low, high = min(value for _, value, _ in entries), max(value for _, value, _ in entries)
    axis_x, axis_y, axis_h = x + 42, y + 67, h - 125
    c.setStrokeColor(LINE)
    c.setLineWidth(4)
    c.line(axis_x, axis_y, axis_x, axis_y + axis_h)
    for label, value, color in entries:
        py = axis_y + axis_h * (value - low) / max(high - low, 1e-9)
        c.setFillColor(color)
        c.circle(axis_x, py, 5.2, stroke=0, fill=1)
        c.setStrokeColor(color)
        c.setLineWidth(1)
        c.line(axis_x + 6, py, x + w - 17, py)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.3)
        c.drawString(axis_x + 13, py + 6, label)
        c.setFillColor(INK)
        c.setFont(money_font(data, "Display"), 16)
        c.drawRightString(x + w - 17, py - 4, money(data, value))
    c.setFillColor(MUTED)
    c.setFont("Body", 6.2)
    rule = selected["candidate"] if selected else {}
    exit_text = f"Exit logic: {rule.get('exit_rule', 'N/A')}."
    c.drawString(x + 16, y + 48, exit_text[:80])
    insight_band(c, x + 10, y + 9, w - 20, f"State: {levels['state'].lower()}. Coordinates only, not forecasts or instructions.", tone=TEAL)


def decision_map_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    """Make the current decision coordinates the dominant visual."""
    panel(c, x, y, w, h)
    section_title(c, x + 14, y + h - 19, w - 28, "01", "Decision map", "Adjusted daily")
    history = data["price_history"]
    levels = data["conditional_levels"]
    closes = [float(item["close"]) for item in history]
    ma50 = [float(item["sma50"]) for item in history if item.get("sma50") is not None]
    ma200 = [float(item["sma200"]) for item in history if item.get("sma200") is not None]
    level_values = [
        float(levels[key])
        for key in ("trigger", "invalidation", "one_r", "two_r")
        if levels.get("available") and isinstance(levels.get(key), (int, float))
    ]
    low, high = _axis(closes + ma50 + ma200 + level_values)
    rail_w = 218
    chart_x, chart_y = x + 48, y + 69
    chart_w, chart_h = w - rail_w - 75, h - 128
    rail_x = chart_x + chart_w + 22

    for fraction in (0.0, 0.25, 0.50, 0.75, 1.0):
        gy = chart_y + fraction * chart_h
        value = low + fraction * (high - low)
        c.setStrokeColor(PALE)
        c.setLineWidth(0.6)
        c.line(chart_x, gy, chart_x + chart_w, gy)
        c.setFillColor(MUTED)
        c.setFont(money_font(data, "Mono"), 5.8)
        c.drawRightString(chart_x - 7, gy - 2, money(data, value, 0))

    def points_for(key: str) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for index, item in enumerate(history):
            value = item.get(key)
            if value is None:
                continue
            px = chart_x + chart_w * index / max(1, len(history) - 1)
            py = chart_y + chart_h * (float(value) - low) / (high - low)
            points.append((px, py))
        return points

    _plot_line(c, points_for("close"), NAVY, 2.5)
    _plot_line(c, points_for("sma50"), TEAL, 1.4)
    _plot_line(c, points_for("sma200"), GOLD, 1.4)
    last_x = chart_x + chart_w
    last_y = chart_y + chart_h * (closes[-1] - low) / (high - low)
    c.setFillColor(NAVY)
    c.circle(last_x, last_y, 3.8, stroke=0, fill=1)

    if levels.get("available"):
        for key, color in (("two_r", BLUE), ("one_r", PLUM), ("trigger", TEAL), ("invalidation", CORAL)):
            value = float(levels[key])
            py = chart_y + chart_h * (value - low) / (high - low)
            if chart_y <= py <= chart_y + chart_h:
                c.setStrokeColor(color)
                c.setDash(4, 2)
                c.setLineWidth(0.9)
                c.line(chart_x, py, chart_x + chart_w, py)
                c.setDash()

    for offset, label, color in ((0, "PRICE", NAVY), (48, "50D", TEAL), (84, "200D", GOLD)):
        lx = chart_x + offset
        c.setStrokeColor(color)
        c.setLineWidth(2)
        c.line(lx, y + h - 43, lx + 14, y + h - 43)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.6)
        c.drawString(lx + 18, y + h - 45, label)

    dates = [history[0]["session"], history[len(history) // 2]["session"], history[-1]["session"]]
    for fraction, label in zip((0, 0.5, 1), dates):
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.4)
        c.drawCentredString(chart_x + chart_w * fraction, chart_y - 14, label[:7])

    c.setFillColor(PALE if levels.get("available") else SOFT_CORAL)
    c.roundRect(rail_x, chart_y, rail_w - 12, chart_h, 7, stroke=0, fill=1)
    c.setFillColor(TEAL if levels.get("available") else CORAL)
    c.setFont("Mono", 6.3)
    c.drawString(rail_x + 13, chart_y + chart_h - 19, "CURRENT DECISION")
    if not levels.get("available"):
        c.setFillColor(CORAL)
        c.setFont("Display", fit_text("NO QUALIFIED SETUP", "Display", 25, rail_w - 38))
        c.drawString(rail_x + 13, chart_y + chart_h - 53, "NO QUALIFIED SETUP")
        c.setFillColor(INK)
        c.setFont("BodyBold", 8.4)
        for index, line in enumerate(wrapped_lines(levels["reason"], "BodyBold", 8.4, rail_w - 38, 7)):
            c.drawString(rail_x + 13, chart_y + chart_h - 82 - index * 11.5, line)
    else:
        c.setFillColor(INK)
        c.setFont("Display", fit_text(levels["setup_status"], "Display", 25, rail_w - 38))
        c.drawString(rail_x + 13, chart_y + chart_h - 51, levels["setup_status"])
        entries = [
            ("2R PLANNING REF", levels["two_r"], BLUE),
            ("1R PLANNING REF", levels["one_r"], PLUM),
            (levels["trigger_label"].upper(), levels["trigger"], TEAL),
            ("RISK INVALIDATION", levels["invalidation"], CORAL),
        ]
        start_y = chart_y + chart_h - 80
        for index, (label, value, color) in enumerate(entries):
            ey = start_y - index * 43
            c.setFillColor(color)
            c.rect(rail_x + 13, ey - 21, 4, 32, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.setFont("Mono", 5.3)
            c.drawString(rail_x + 25, ey + 2, label)
            c.setFillColor(INK)
            c.setFont(money_font(data, "Display"), 19)
            c.drawString(rail_x + 25, ey - 18, money(data, float(value)))
    selected = data.get("selected")
    if levels.get("available") and selected:
        message = f"{levels['setup_status'].title()}. Activation: {levels['activation_condition']}."
        tone = TEAL
    else:
        message = "No decision coordinates are published unless the rule clears the untouched holdout and robustness gates."
        tone = CORAL
    insight_band(c, x + 11, y + 10, w - 22, message, tone=tone)


def decision_blueprint_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 14, y + h - 19, w - 28, "02", "Exact decision protocol", "Close to next open")
    levels = data["conditional_levels"]
    selected = data.get("selected")
    if not levels.get("available") or not selected:
        c.setFillColor(CORAL)
        c.setFont("Display", fit_text("STOP: NO ROBUST EDGE", "Display", 29, w - 36))
        c.drawString(x + 18, y + h - 78, "STOP: NO ROBUST EDGE")
        c.setFillColor(INK)
        c.setFont("BodyBold", 9)
        for index, line in enumerate(wrapped_lines("No entry, stop or target is published when the tested rule fails the final evidence gate.", "BodyBold", 9, w - 36, 3)):
            c.drawString(x + 18, y + h - 111 - index * 13, line)
        c.setFillColor(PALE)
        c.roundRect(x + 15, y + 65, w - 30, 191, 7, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont("Mono", 6.1)
        c.drawString(x + 27, y + 238, "FINAL EVIDENCE GATES")
        if selected:
            gate_labels = {
                "holdout_activity": "ENOUGH OOS TRADES",
                "holdout_net": "POSITIVE OOS RETURN",
                "holdout_profit_factor": "PROFIT FACTOR >= 1.05",
                "holdout_sharpe": "POSITIVE OOS SHARPE",
                "holdout_drawdown": "DRAWDOWN <= 25%",
                "double_cost_holdout": "SURVIVES HIGHER COST",
                "neighbor_holdout": "NEIGHBOR RULES STABLE",
            }
            gates = selected.get("holdout_gates", {})
            for index, (key, label) in enumerate(gate_labels.items()):
                passed = bool(gates.get(key))
                gy = y + 214 - index * 21
                c.setFillColor(TEAL if passed else CORAL)
                c.circle(x + 29, gy + 1, 4, stroke=0, fill=1)
                c.setFillColor(INK)
                c.setFont("BodyBold", 7.2)
                c.drawString(x + 41, gy - 2, label)
                c.setFillColor(TEAL if passed else CORAL)
                c.setFont("Mono", 6)
                c.drawRightString(x + w - 27, gy - 2, "PASS" if passed else "FAIL")
        else:
            c.setFillColor(CORAL)
            c.setFont("BodyBold", 9)
            for index, line in enumerate(wrapped_lines("No rule cleared the pre-holdout selection gates. The engine stopped before revealing a preferred strategy.", "BodyBold", 9, w - 55, 5)):
                c.drawString(x + 27, y + 208 - index * 13, line)
        insight_band(c, x + 10, y + 10, w - 20, "Failing closed is a valid result, not missing analysis.", tone=CORAL)
        return

    status_color = GOLD if levels["state"] == "WAITING" else TEAL
    c.setFillColor(status_color)
    c.roundRect(x + 15, y + h - 75, w - 30, 34, 6, stroke=0, fill=1)
    c.setFillColor(NAVY if status_color == GOLD else SURFACE)
    c.setFont("Display", fit_text(levels["setup_status"], "Display", 22, w - 48))
    c.drawString(x + 24, y + h - 66, levels["setup_status"])

    steps = [
        ("1", "ACTIVATE", levels["activation_condition"], TEAL),
        ("2", "EXECUTE", levels["execution_timing"], BLUE),
        ("3", "INVALIDATE", f"Risk reference {money(data, levels['invalidation'])}; width {pct(levels['risk_percent'])}", CORAL),
        ("4", "EXIT", levels["backtested_exit_condition"], PLUM),
    ]
    top = y + h - 107
    for index, (number, label, detail, color) in enumerate(steps):
        row_y = top - index * 52
        c.setFillColor(color)
        c.circle(x + 29, row_y, 10, stroke=0, fill=1)
        c.setFillColor(SURFACE)
        c.setFont("BodyBold", 7.5)
        c.drawCentredString(x + 29, row_y - 2.5, number)
        c.setFillColor(color)
        c.setFont("Mono", 6.0)
        c.drawString(x + 48, row_y + 7, label)
        c.setFillColor(INK)
        detail_font = money_font(data, "BodyBold") if data.get("currency_symbol") in detail else "BodyBold"
        c.setFont(detail_font, 7.8)
        for line_index, line in enumerate(wrapped_lines(detail, detail_font, 7.8, w - 72, 3)):
            c.drawString(x + 48, row_y - 6 - line_index * 9.5, line)
        if index < len(steps) - 1:
            c.setStrokeColor(LINE)
            c.setLineWidth(1)
            c.line(x + 29, row_y - 12, x + 29, row_y - 40)

    c.setFillColor(SOFT_GOLD)
    c.roundRect(x + 15, y + 50, w - 30, 44, 6, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont("Mono", 5.8)
    c.drawString(x + 24, y + 78, "PLANNING REFERENCES")
    c.setFillColor(INK)
    references = f"1R {money(data, levels['one_r'])}   /   2R {money(data, levels['two_r'])}"
    reference_font = money_font(data, "Display")
    c.setFont(reference_font, fit_text(references, reference_font, 20, w - 48))
    c.drawString(x + 24, y + 57, references)
    insight_band(c, x + 10, y + 9, w - 20, "Entry and exit are rules. Stop and R-levels are explicit planning references.", tone=TEAL)


def strategy_evidence_panel(c: canvas.Canvas, data: dict, x: float, y: float, w: float, h: float) -> None:
    panel(c, x, y, w, h)
    section_title(c, x + 14, y + h - 19, w - 28, "03", "Why trust this rule?", "Untouched holdout")
    selected = data.get("selected")
    if not selected:
        c.setFillColor(CORAL)
        c.setFont("Display", 27)
        c.drawString(x + 18, y + h - 78, "NO PRE-HOLDOUT WINNER")
        insight_band(c, x + 10, y + 9, w - 20, "No strategy evidence is manufactured when selection stops early.", tone=CORAL)
        return
    metrics = selected["metrics"]["holdout"]
    profile = selected["trade_profile"]
    c.setFillColor(INK)
    c.setFont("Display", fit_text(selected["candidate"]["label"].upper(), "Display", 27, w - 36))
    c.drawString(x + 18, y + h - 68, selected["candidate"]["label"].upper())
    c.setFillColor(MUTED)
    c.setFont("Mono", 5.7)
    c.drawString(x + 18, y + h - 83, f"OOS {data['windows']['holdout']['start']} TO {data['windows']['holdout']['end']}  |  {int(data['data']['base_cost_bps_per_side'])} BPS / SIDE")

    payoff = profile.get("payoff_ratio")
    headline = [
        ("SUCCESS RATE", pct(profile["success_rate"]), TEAL),
        ("PAYOFF RATIO", multiple(payoff), BLUE),
        ("EXPECTANCY", pct(metrics["expectancy"]), PLUM),
    ]
    cell_w = (w - 36) / 3
    for index, (label, value, color) in enumerate(headline):
        cx = x + 18 + index * cell_w
        c.setFillColor(PALE)
        c.roundRect(cx, y + h - 157, cell_w - 7, 57, 6, stroke=0, fill=1)
        c.setFillColor(color)
        c.setFont("Display", fit_text(value, "Display", 25, cell_w - 23))
        c.drawString(cx + 10, y + h - 133, value)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.3)
        c.drawString(cx + 10, y + h - 148, label)

    worst_cost = str(int(data["data"]["stress_costs_bps_per_side"][-1]))
    rows = [
        ("PROFIT FACTOR", multiple(metrics["profit_factor"])),
        ("MAX DRAWDOWN", pct(metrics["max_drawdown"])),
        ("COMPLETED TRADES", str(metrics["trades"])),
        ("MEDIAN HOLD", f"{profile['median_holding_sessions']} sessions" if profile.get("median_holding_sessions") else "N/A"),
        (f"{worst_cost} BPS STRESS", pct(selected["stress"][worst_cost]["holdout_return"])),
        ("NEIGHBORS POSITIVE", pct(selected["neighbor_holdout_ratio"], 0)),
    ]
    for index, (label, value) in enumerate(rows):
        column = index % 2
        row = index // 2
        rx = x + 18 + column * ((w - 36) / 2)
        ry = y + h - 191 - row * 34
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.4)
        c.drawString(rx, ry, label)
        c.setFillColor(INK)
        c.setFont("BodyBold", 9)
        c.drawString(rx, ry - 14, value)

    if payoff is not None:
        logic = f"{pct(profile['success_rate'])} of completed OOS trades won; the average winner was {payoff:.2f}x the average loss. Expectancy was {pct(metrics['expectancy'])} per trade."
    else:
        logic = f"Success rate was {pct(profile['success_rate'])}; payoff was not measurable across both wins and losses. Expectancy was {pct(metrics['expectancy'])} per trade."
    c.setFillColor(PALE if selected["qualified"] else SOFT_CORAL)
    c.roundRect(x + 15, y + 50, w - 30, 58, 6, stroke=0, fill=1)
    c.setFillColor(TEAL if selected["qualified"] else CORAL)
    c.setFont("Mono", 5.8)
    c.drawString(x + 24, y + 92, "READ THE SUCCESS RATE WITH THE PAYOFF")
    c.setFillColor(INK)
    c.setFont("BodyBold", 7.5)
    for index, line in enumerate(wrapped_lines(logic, "BodyBold", 7.5, w - 48, 3)):
        c.drawString(x + 24, y + 78 - index * 9.5, line)
    insight = "Qualified after costs, drawdown, activity and parameter-neighbor checks." if selected["qualified"] else "The pre-holdout winner failed at least one final evidence gate."
    insight_band(c, x + 10, y + 9, w - 20, insight, tone=TEAL if selected["qualified"] else CORAL)


def render(sidecar_path: Path, pdf_path: Path, png_path: Path) -> None:
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "technical-analysis-brief-v2":
        raise ValueError("Unsupported technical-analysis sidecar schema")
    if data.get("disclaimer") != "Research output - not a recommendation. The reader decides whether to act.":
        raise ValueError("Research boundary is missing or altered")
    register_fonts()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf_path), pagesize=(PAGE_W, PAGE_H), invariant=1)
    display_ticker = data.get("display_ticker", data["ticker"])
    c.setTitle(f"{display_ticker} Technical Evidence Brief")
    c.setAuthor("stockcentric")

    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.rect(0, 988, PAGE_W, 137, stroke=0, fill=1)
    c.setFillColor(MINT)
    c.rect(0, 983, PAGE_W, 5, stroke=0, fill=1)
    c.setFillColor(MINT)
    c.setFont("Mono", 8.8)
    c.drawString(MARGIN, 1092, "STOCKCENTRIC / TECHNICAL EVIDENCE BRIEF")
    c.setFillColor(SURFACE)
    c.setFont("Display", fit_text(display_ticker, "Display", 65, 132))
    c.drawString(MARGIN, 1017, display_ticker)
    header_question = "WHERE DOES THE RULE ACTIVATE, FAIL AND EXIT?"
    c.setFont("BodyBold", fit_text(header_question, "BodyBold", 17, 448))
    c.drawString(183, 1054, header_question)
    c.setFillColor(MINT)
    c.setFont("BodyBold", 8.4)
    c.drawString(184, 1029, f"{data.get('exchange', 'US')} / {data.get('currency', 'USD')}  |  DECISION PROTOCOL  |  {data['data']['start']} TO {data['data']['end']}")
    c.setFillColor(SURFACE)
    c.setFont("BodyBold", 9.1)
    selected_label = data["selected"]["candidate"]["label"] if data.get("selected") else "NO PRE-HOLDOUT WINNER"
    c.drawString(184, 1005, f"PRE-HOLDOUT LOCK: {selected_label.upper()}  |  CURRENT REGIME: {data['current']['regime']}")

    levels = data["conditional_levels"]
    setup_status = levels.get("setup_status", "NO QUALIFIED SETUP")
    verdict_color = MINT if data["status"] == "qualified" else HexColor("#F1A68F")
    c.setFillColor(verdict_color)
    c.roundRect(646, 1038, 218, 39, 7, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Display", fit_text(setup_status, "Display", 23, 194))
    c.drawCentredString(755, 1050, setup_status)
    c.setFillColor(SURFACE)
    c.setFont(money_font(data, "Display"), 30)
    c.drawRightString(864, 1004, money(data, data["current"]["close"]))
    c.setFillColor(MINT)
    c.setFont("Mono", 6.4)
    c.drawRightString(864, 993, f"AS OF {data['current']['session']} CLOSE")

    ribbon_y = 935
    selected = data.get("selected")
    oos = selected["metrics"]["holdout"] if selected else None
    profile = selected.get("trade_profile", {}) if selected else {}
    ribbon = [
        ("SETUP", setup_status, TEAL if data["status"] == "qualified" else CORAL),
        ("ACTIVATION", levels.get("activation_type") or "N/A", GOLD),
        ("RISK WIDTH", pct(levels.get("risk_percent")) if levels.get("available") else "N/A", CORAL),
        ("OOS SUCCESS", pct(profile.get("success_rate")) if selected else "N/A", BLUE),
        ("PAYOFF", multiple(profile.get("payoff_ratio")) if selected else "N/A", PLUM),
    ]
    item_w = (PAGE_W - 2 * MARGIN) / len(ribbon)
    for index, (label, value, color) in enumerate(ribbon):
        rx = MARGIN + index * item_w
        c.setFillColor(color)
        c.rect(rx, ribbon_y, 6, 36, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("Display", fit_text(value, "Display", 16.5, item_w - 22))
        c.drawString(rx + 14, ribbon_y + 13, value)
        c.setFillColor(MUTED)
        c.setFont("Mono", 5.5)
        c.drawString(rx + 14, ribbon_y + 2, label)

    decision_map_panel(c, data, 36, 535, 828, 384)
    decision_blueprint_panel(c, data, 36, 112, 404, 404)
    strategy_evidence_panel(c, data, 458, 112, 406, 404)

    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.line(MARGIN, 94, PAGE_W - MARGIN, 94)
    c.setFillColor(MUTED)
    c.setFont("Body", 5.7)
    c.drawString(MARGIN, 78, f"Source: {data['data']['source']}; adjusted daily OHLCV fetched {data['data']['fetched_at']}. Input hash {data['data']['sha256'][:16]}.")
    stress_text = ", ".join(str(int(value)) for value in data["data"]["stress_costs_bps_per_side"][1:])
    c.drawString(MARGIN, 66, f"Tested rule: 50% training / 25% validation / 25% untouched holdout; next-open execution; {int(data['data']['base_cost_bps_per_side'])} bps per side; {stress_text} bps stress; adjacent-parameter gate.")
    c.drawString(MARGIN, 54, "Important: the historical result uses the stated rule exit. Fixed invalidation and 1R/2R levels are planning references, not backtested exits.")
    c.setFillColor(INK)
    c.setFont("BodyBold", 6.2)
    c.drawString(MARGIN, 35, "Research output - not a recommendation. The reader decides whether to act.")
    c.setFillColor(TEAL)
    c.setFont("Mono", 5.8)
    c.drawRightString(PAGE_W - MARGIN, 35, "STOCKCENTRIC / TECHNICAL-ANALYSIS-BRIEF / 01")
    c.showPage()
    c.save()

    document = fitz.open(pdf_path)
    page = document[0]
    pixmap = page.get_pixmap(matrix=fitz.Matrix(EXPORT_W / PAGE_W, EXPORT_H / PAGE_H), alpha=False)
    pixmap.save(png_path)
    document.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    args = parser.parse_args()
    render(args.sidecar.resolve(), args.pdf.resolve(), args.png.resolve())
    print(json.dumps({"pdf": str(args.pdf.resolve()), "png": str(args.png.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
