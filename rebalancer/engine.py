from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from .models import (
    HoldingPosition,
    MarketStackQuote,
    OrderSide,
    RebalancePlan,
    RebalanceStatus,
    StagingRow,
)


class PortfolioRebalancerEngine:
    """Idempotent portfolio rebalancer with MarketStack freshness checks,
    two-phase staging preview, and post-write read-back verification.
    """

    def __init__(
        self,
        max_quote_age_seconds: int = 300,
        drift_threshold_pct: float = 0.01,
        weight_tolerance: float = 1e-4,
    ) -> None:
        self.max_quote_age_seconds = max_quote_age_seconds
        self.drift_threshold_pct = drift_threshold_pct
        self.weight_tolerance = weight_tolerance
        self._committed_runs: Set[str] = set()
        self._ledger: Dict[str, float] = {}

    @property
    def ledger(self) -> Dict[str, float]:
        return dict(self._ledger)

    def load_ledger(self, holdings: List[HoldingPosition]) -> None:
        self._ledger = {h.ticker: h.shares for h in holdings}

    def validate_quotes(
        self,
        holdings: List[HoldingPosition],
        quotes: Dict[str, MarketStackQuote],
        as_of: Optional[datetime] = None,
    ) -> Optional[str]:
        now = as_of or datetime.now(timezone.utc)
        for holding in holdings:
            quote = quotes.get(holding.ticker)
            if quote is None:
                return f"Missing MarketStack quote for {holding.ticker}"
            quoted_at = quote.quoted_at
            if quoted_at.tzinfo is None:
                quoted_at = quoted_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - quoted_at).total_seconds()
            if age_seconds > self.max_quote_age_seconds:
                return (
                    f"Stale quote for {holding.ticker}: age {age_seconds:.1f}s "
                    f"exceeds max {self.max_quote_age_seconds}s"
                )
        return None

    def stage_rebalance(
        self,
        run_id: str,
        holdings: List[HoldingPosition],
        quotes: Dict[str, MarketStackQuote],
        as_of: Optional[datetime] = None,
    ) -> RebalancePlan:
        if run_id in self._committed_runs:
            return RebalancePlan(
                idempotency_key=run_id,
                status=RebalanceStatus.DUPLICATE_SKIPPED,
                total_portfolio_value=0.0,
                staging_rows=[],
                read_back_verified=False,
                reason=f"Run ID '{run_id}' already committed.",
            )

        target_sum = sum(h.target_weight for h in holdings)
        if abs(target_sum - 1.0) > self.weight_tolerance:
            raise ValueError(
                f"Target weights must sum to 1.0 (100%), got {target_sum:.6f}"
            )

        quote_error = self.validate_quotes(holdings, quotes, as_of=as_of)
        if quote_error:
            return RebalancePlan(
                idempotency_key=run_id,
                status=RebalanceStatus.REJECTED_STALE_QUOTE,
                total_portfolio_value=0.0,
                staging_rows=[],
                read_back_verified=False,
                reason=quote_error,
            )

        if not self._ledger:
            self.load_ledger(holdings)

        total_value = sum(
            h.shares * quotes[h.ticker].price for h in holdings
        )
        if total_value <= 0:
            raise ValueError("Total portfolio value must be positive.")

        staging_rows: List[StagingRow] = []
        for h in holdings:
            price = quotes[h.ticker].price
            current_value = h.shares * price
            current_weight = current_value / total_value
            drift_pct = current_weight - h.target_weight

            target_value = total_value * h.target_weight
            delta_value = target_value - current_value
            if abs(drift_pct) < self.drift_threshold_pct:
                side = OrderSide.HOLD
                trade_shares = 0.0
                trade_notional = 0.0
                projected_shares = h.shares
            elif delta_value > 0:
                side = OrderSide.BUY
                trade_shares = round(delta_value / price, 6)
                trade_notional = round(trade_shares * price, 4)
                projected_shares = round(h.shares + trade_shares, 6)
            else:
                side = OrderSide.SELL
                trade_shares = round(abs(delta_value) / price, 6)
                trade_notional = round(trade_shares * price, 4)
                projected_shares = round(h.shares - trade_shares, 6)

            projected_weight = (projected_shares * price) / total_value
            staging_rows.append(
                StagingRow(
                    ticker=h.ticker,
                    current_shares=h.shares,
                    current_price=price,
                    current_value=round(current_value, 4),
                    current_weight=round(current_weight, 6),
                    target_weight=h.target_weight,
                    drift_pct=round(drift_pct, 6),
                    side=side,
                    trade_shares=trade_shares,
                    trade_notional=trade_notional,
                    projected_shares=projected_shares,
                    projected_weight=round(projected_weight, 6),
                )
            )

        return RebalancePlan(
            idempotency_key=run_id,
            status=RebalanceStatus.STAGED,
            total_portfolio_value=round(total_value, 4),
            staging_rows=staging_rows,
            read_back_verified=False,
            reason="Staged successfully; ready for commit.",
        )

    def commit_rebalance(
        self,
        plan: RebalancePlan,
        sheet_writer: Optional[Callable[[Dict[str, float]], Dict[str, float]]] = None,
    ) -> RebalancePlan:
        if plan.idempotency_key in self._committed_runs:
            return plan.model_copy(
                update={
                    "status": RebalanceStatus.DUPLICATE_SKIPPED,
                    "read_back_verified": False,
                    "reason": f"Run ID '{plan.idempotency_key}' already committed.",
                }
            )

        if plan.status != RebalanceStatus.STAGED:
            return plan

        snapshot = dict(self._ledger)
        expected_shares = {
            row.ticker: row.projected_shares for row in plan.staging_rows
        }

        if sheet_writer is not None:
            read_back = sheet_writer(dict(expected_shares))
        else:
            self._ledger = dict(expected_shares)
            read_back = dict(self._ledger)

        # Verify exact share match and 100% projected allocation sum
        shares_match = all(
            abs(read_back.get(row.ticker, -1.0) - row.projected_shares) <= 1e-4
            for row in plan.staging_rows
        )
        total_projected_weight = sum(row.projected_weight for row in plan.staging_rows)
        weights_valid = abs(total_projected_weight - 1.0) <= self.weight_tolerance

        if not (shares_match and weights_valid):
            self._ledger = snapshot
            return plan.model_copy(
                update={
                    "status": RebalanceStatus.READ_BACK_MISMATCH,
                    "read_back_verified": False,
                    "reason": "Post-write read-back verification failed; rolled back ledger.",
                }
            )

        self._ledger = dict(read_back)
        self._committed_runs.add(plan.idempotency_key)
        return plan.model_copy(
            update={
                "status": RebalanceStatus.COMMITTED,
                "read_back_verified": True,
                "reason": "Committed and verified via post-write read-back.",
            }
        )
