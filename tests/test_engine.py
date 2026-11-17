from datetime import datetime, timedelta, timezone
import pytest

from rebalancer import (
    HoldingPosition,
    MarketStackQuote,
    PortfolioRebalancerEngine,
    RebalanceStatus,
)


def _sample_holdings():
    return [
        HoldingPosition(ticker="VTI", shares=50.0, target_weight=0.60),
        HoldingPosition(ticker="VXUS", shares=40.0, target_weight=0.25),
        HoldingPosition(ticker="BND", shares=30.0, target_weight=0.15),
    ]


def _sample_quotes(quoted_at: datetime):
    return {
        "VTI": MarketStackQuote(ticker="VTI", price=280.0, quoted_at=quoted_at),
        "VXUS": MarketStackQuote(ticker="VXUS", price=62.5, quoted_at=quoted_at),
        "BND": MarketStackQuote(ticker="BND", price=75.0, quoted_at=quoted_at),
    }


def test_stale_quote_rejection():
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(seconds=600)
    engine = PortfolioRebalancerEngine(max_quote_age_seconds=300)
    plan = engine.stage_rebalance(
        run_id="run-stale-01",
        holdings=_sample_holdings(),
        quotes=_sample_quotes(stale_time),
        as_of=now,
    )
    assert plan.status == RebalanceStatus.REJECTED_STALE_QUOTE
    assert plan.staging_rows == []


def test_duplicate_run_id_idempotency():
    now = datetime.now(timezone.utc)
    engine = PortfolioRebalancerEngine(max_quote_age_seconds=300)
    staged = engine.stage_rebalance(
        run_id="run-idem-01",
        holdings=_sample_holdings(),
        quotes=_sample_quotes(now),
        as_of=now,
    )
    committed = engine.commit_rebalance(staged)
    assert committed.status == RebalanceStatus.COMMITTED
    assert committed.read_back_verified is True

    duplicate = engine.stage_rebalance(
        run_id="run-idem-01",
        holdings=_sample_holdings(),
        quotes=_sample_quotes(now),
        as_of=now,
    )
    assert duplicate.status == RebalanceStatus.DUPLICATE_SKIPPED


def test_read_back_mismatch_rollback():
    now = datetime.now(timezone.utc)
    holdings = _sample_holdings()
    engine = PortfolioRebalancerEngine(max_quote_age_seconds=300)
    engine.load_ledger(holdings)
    original_ledger = engine.ledger

    staged = engine.stage_rebalance(
        run_id="run-mismatch-01",
        holdings=holdings,
        quotes=_sample_quotes(now),
        as_of=now,
    )

    def corrupted_writer(shares: dict) -> dict:
        corrupted = dict(shares)
        corrupted["VTI"] = 9999.0
        return corrupted

    result = engine.commit_rebalance(staged, sheet_writer=corrupted_writer)
    assert result.status == RebalanceStatus.READ_BACK_MISMATCH
    assert result.read_back_verified is False
    assert engine.ledger == original_ledger


def test_100_percent_allocation_sum():
    now = datetime.now(timezone.utc)
    engine = PortfolioRebalancerEngine(max_quote_age_seconds=300)
    staged = engine.stage_rebalance(
        run_id="run-alloc-01",
        holdings=_sample_holdings(),
        quotes=_sample_quotes(now),
        as_of=now,
    )
    total_projected_weight = sum(row.projected_weight for row in staged.staging_rows)
    assert pytest.approx(total_projected_weight, abs=1e-4) == 1.0

    bad_holdings = [
        HoldingPosition(ticker="VTI", shares=10.0, target_weight=0.50),
        HoldingPosition(ticker="VXUS", shares=10.0, target_weight=0.30),
    ]
    with pytest.raises(ValueError, match="100%"):
        engine.stage_rebalance(
            run_id="run-bad-alloc",
            holdings=bad_holdings,
            quotes=_sample_quotes(now),
            as_of=now,
        )
