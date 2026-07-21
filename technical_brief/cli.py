from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from technical_analysis import analyze, read_ohlcv_csv

from .market import resolve_security
from .provider import YahooResearchProvider
from .render import render


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(
    *,
    ticker: str,
    market: str | None,
    output_dir: Path,
    input_csv: Path | None = None,
    source: str | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    security = resolve_security(ticker, market)
    if input_csv:
        frame = read_ohlcv_csv(input_csv)
        source_label = source or "Saved adjusted OHLCV research input"
        fetched = fetched_at or frame.index[-1].date().isoformat() + "T00:00:00+00:00"
    else:
        frame, source_label, fetched = YahooResearchProvider().fetch(security)

    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "adjusted-ohlcv.csv"
    frame.to_csv(input_path, index_label="Date", date_format="%Y-%m-%d", float_format="%.8f")
    evidence = analyze(
        security.canonical_ticker,
        frame,
        source=source_label,
        fetched_at=fetched,
        market=security.profile.code,
    )
    evidence_path = output_dir / "technical-evidence.json"
    safe_ticker = security.canonical_ticker.replace(".", "-")
    pdf_path = output_dir / f"{safe_ticker}-technical-brief.pdf"
    png_path = output_dir / f"{safe_ticker}-technical-brief.png"
    _write_json(evidence_path, evidence)
    render(evidence_path, pdf_path, png_path)
    return {
        "ticker": security.canonical_ticker,
        "market": security.profile.code,
        "status": evidence["status"],
        "input": str(input_path),
        "evidence": str(evidence_path),
        "pdf": str(pdf_path),
        "png": str(png_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a refusal-first US or Indian technical-analysis brief."
    )
    parser.add_argument("ticker")
    parser.add_argument("--market", choices=("us", "in"), default=None)
    parser.add_argument("--out", type=Path, default=Path("outputs"))
    parser.add_argument("--input-csv", type=Path)
    parser.add_argument("--source")
    parser.add_argument("--fetched-at")
    args = parser.parse_args()
    try:
        result = run(
            ticker=args.ticker,
            market=args.market,
            output_dir=args.out.resolve(),
            input_csv=args.input_csv.resolve() if args.input_csv else None,
            source=args.source,
            fetched_at=args.fetched_at,
        )
    except (ValueError, KeyError) as error:
        receipt = {
            "ticker": args.ticker.upper(),
            "market": args.market,
            "status": "insufficient_evidence",
            "reason": str(error),
        }
        _write_json(args.out.resolve() / "failure-receipt.json", receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
