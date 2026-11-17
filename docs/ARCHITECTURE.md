# Architecture: Idempotent Portfolio Rebalancer (Project 09)

## Overview
The Idempotent Portfolio Rebalancer provides a deterministic, audit-ready Python core designed to back an n8n workflow or standalone CLI. It prevents double-trades, stale-price execution, and silent ledger corruption.

## Core Safeguards

### 1. MarketStack Quote Freshness Check
Every `MarketStackQuote` is validated against `max_quote_age_seconds` relative to the evaluation timestamp. If any required ticker quote is missing or older than the freshness threshold, the run is immediately rejected with `RebalanceStatus.REJECTED_STALE_QUOTE` before any staging or ledger mutation occurs.

### 2. Idempotent `run_id` Lock
Each rebalance execution requires a unique `run_id` (stored as `idempotency_key` on `RebalancePlan`). Executed run IDs are recorded in an idempotency store. Re-submitting an already committed `run_id` short-circuits with `RebalanceStatus.DUPLICATE_SKIPPED` and returns without modifying portfolio holdings.

### 3. Two-Phase Staging Sheet Preview
Before committing any changes, `PortfolioRebalancerEngine.stage_rebalance` computes:
- Total portfolio value from current shares and fresh MarketStack prices
- Current weight vs. target weight and drift percentage (`drift_pct`)
- Exact `BUY`, `SELL`, or `HOLD` trade shares and notional values
- Projected shares and projected weights in `StagingRow` entries (`RebalanceStatus.STAGED`)

### 4. Post-Write Read-Back Verification & Rollback
During `commit_rebalance`, the engine snapshots the prior ledger state, writes the projected shares to the target sheet/ledger, and immediately reads back the persisted balances. It verifies:
- Total projected allocation weights sum to 100% (1.0 within tolerance)
- Read-back shares match the staged `projected_shares` per ticker

If any discrepancy is detected, the engine rolls back to the pre-write snapshot and returns `RebalanceStatus.READ_BACK_MISMATCH`. Otherwise, it marks the `run_id` as committed and returns `RebalanceStatus.COMMITTED` with `read_back_verified=True`.
