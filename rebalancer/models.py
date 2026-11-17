from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class RebalanceStatus(str, Enum):
    STAGED = "STAGED"
    COMMITTED = "COMMITTED"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
    REJECTED_STALE_QUOTE = "REJECTED_STALE_QUOTE"
    READ_BACK_MISMATCH = "READ_BACK_MISMATCH"


class HoldingPosition(BaseModel):
    ticker: str = Field(..., min_length=1)
    shares: float = Field(..., ge=0.0)
    target_weight: float = Field(..., ge=0.0, le=1.0)


class MarketStackQuote(BaseModel):
    ticker: str = Field(..., min_length=1)
    price: float = Field(..., gt=0.0)
    quoted_at: datetime
    source: str = "marketstack"


class StagingRow(BaseModel):
    ticker: str
    current_shares: float
    current_price: float
    current_value: float
    current_weight: float
    target_weight: float
    drift_pct: float
    side: OrderSide
    trade_shares: float
    trade_notional: float
    projected_shares: float
    projected_weight: float


class RebalancePlan(BaseModel):
    idempotency_key: str
    status: RebalanceStatus
    total_portfolio_value: float
    staging_rows: list[StagingRow] = Field(default_factory=list)
    read_back_verified: bool = False
    reason: str = ""
