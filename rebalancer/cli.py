from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .engine import PortfolioRebalancerEngine
from .models import HoldingPosition, MarketStackQuote


def run_demo(run_id: str = "demo-run-001") -> dict:
    now = datetime.now(timezone.utc)
    holdings = [
        HoldingPosition(ticker="VTI", shares=50.0, target_weight=0.60),
        HoldingPosition(ticker="VXUS", shares=40.0, target_weight=0.25),
        HoldingPosition(ticker="BND", shares=30.0, target_weight=0.15),
    ]
    quotes = {
        "VTI": MarketStackQuote(ticker="VTI", price=280.0, quoted_at=now),
        "VXUS": MarketStackQuote(ticker="VXUS", price=62.5, quoted_at=now),
        "BND": MarketStackQuote(ticker="BND", price=75.0, quoted_at=now),
    }

    engine = PortfolioRebalancerEngine(max_quote_age_seconds=300)
    staged = engine.stage_rebalance(run_id=run_id, holdings=holdings, quotes=quotes, as_of=now)
    committed = engine.commit_rebalance(staged)
    return committed.model_dump(mode="json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotent Portfolio Rebalancer CLI Demo")
    parser.add_argument("--run-id", default="demo-run-001", help="Unique idempotency run ID")
    args = parser.parse_args()
    result = run_demo(run_id=args.run_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
