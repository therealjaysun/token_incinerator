from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.types import RunResult


def make_initial_state() -> BudgetState:
    return BudgetState(
        total_tokens_used=0,
        total_cost_usd=0.0,
        run_count=0,
        started_at=datetime.now(tz=timezone.utc),
        last_run_at=None,
    )


def apply_run_result(state: BudgetState, result: RunResult) -> BudgetState:
    if not result.success:
        return state
    total_tokens = result.input_tokens + result.output_tokens + result.cache_read_tokens
    return BudgetState(
        total_tokens_used=state.total_tokens_used + total_tokens,
        total_cost_usd=state.total_cost_usd + result.cost_usd,
        run_count=state.run_count + 1,
        started_at=state.started_at,
        last_run_at=datetime.now(tz=timezone.utc),
    )


def is_exhausted(
    state: BudgetState,
    config: DaemonConfig,
    now: Optional[datetime] = None,
) -> bool:
    if config.budget_tokens is not None and state.total_tokens_used >= config.budget_tokens:
        return True
    if config.budget_usd is not None and state.total_cost_usd >= config.budget_usd:
        return True
    if config.budget_duration_seconds is not None:
        _now = now or datetime.now(tz=timezone.utc)
        elapsed = (_now - state.started_at).total_seconds()
        if elapsed >= config.budget_duration_seconds:
            return True
    return False
