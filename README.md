# Idempotent Portfolio Rebalancer (Project 09)

An idempotent, audit-ready portfolio rebalancing automation engine with **MarketStack quote freshness checks**, **staging sheet previews**, and **post-write read-back verification**.

## Architecture Overview

This project implements a deterministic Python rebalancing core designed to back an **n8n** workflow (or standalone CLI/batch runner). Every rebalancing run is keyed by an `idempotency_key` so retries never duplicate trades or corrupt staging sheets.

```
[Trigger + Idempotency Key] -> [Portfolio & Target Weights] -> [MarketStack Quote Freshness Gate]
        -> [Drift & Order Sizing] -> [Staging Sheet Preview] -> [Commit + Read-Back Verification]
```

## 6-Stage Workflow

1. **Idempotency & Run Registration**: Validates the `run_id` / `idempotency_key` against previously committed runs to prevent duplicate execution.
2. **Holdings & Target Contract Ingestion**: Parses current positions (`ticker`, `shares`, `target_weight`) and cash balance, verifying target weights sum to `1.0` (within tolerance).
3. **MarketStack Quote Freshness Check**: Validates that every ticker's MarketStack quote timestamp is within `max_quote_age_seconds` (default `900s`) and has a positive price.
4. **Drift Calculation & Order Sizing**: Computes current weights, target dollar values, drift percentage, and `BUY` / `SELL` / `HOLD` deltas, filtering out dust orders below `min_trade_notional`.
5. **Staging Sheet Preview**: Generates a deterministic staging table (`StagingRow`) with pre-trade and projected post-trade weights for human or policy review before committing.
6. **Commit & Read-Back Verification**: Persists the committed ledger and performs a read-back check comparing expected post-trade shares against the stored ledger state.

## Data Contract

- **Input**:
  - `idempotency_key`: Unique string per rebalancing cycle (e.g. `rebal-2026-11-17-eod`).
  - `holdings`: List of `{ticker, shares, target_weight}`.
  - `quotes`: Mapping of `ticker -> {price, quoted_at, source}`.
  - `cash_balance`: Available USD cash.
- **Output (`RebalancePlan`)**:
  - `status`: `STAGED`, `COMMITTED`, `DUPLICATE_SKIPPED`, or `REJECTED_STALE_QUOTE`.
  - `staging_rows`: Ordered list of proposed orders and weight projections.
  - `read_back_verified`: Boolean confirming stored state matches committed plan.

## Production Controls

- **Idempotency Guard**: Duplicate `idempotency_key` submissions return the cached receipt without re-staging or re-executing orders.
- **Quote Freshness Gate**: Any quote older than `max_quote_age_seconds` aborts the run before order generation.
- **Dust & Drift Thresholds**: Trades smaller than `min_trade_notional` or drift below `min_drift_pct` are suppressed as `HOLD`.
- **Read-Back Verification**: Committed changes are immediately read back and diffed against expected share counts.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -v
python -m rebalancer.cli
```

## Attribution

Inspired by and adapted from **Ed Donner's AI Builder** course (B1: Portfolio Rebalancing Automation).
