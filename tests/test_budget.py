from datetime import datetime, timezone

import pytest

from incinerator.budget import apply_run_result, is_exhausted, make_initial_state
from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.types import RunResult


def make_run_result(**kwargs) -> RunResult:
    defaults = dict(
        prompt_category="review",
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=0,
        cost_usd=0.05,
        duration_ms=3000,
        success=True,
    )
    defaults.update(kwargs)
    return RunResult(**defaults)


def make_state(**kwargs) -> BudgetState:
    defaults = dict(
        total_tokens_used=0,
        total_cost_usd=0.0,
        run_count=0,
        started_at=datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return BudgetState(**defaults)


def make_config(**kwargs) -> DaemonConfig:
    defaults = dict(repo_path="/repo")
    defaults.update(kwargs)
    return DaemonConfig(**defaults)


class TestMakeInitialState:
    def test_creates_state_with_zero_counts(self):
        state = make_initial_state()
        assert state.total_tokens_used == 0
        assert state.total_cost_usd == 0.0
        assert state.run_count == 0
        assert state.last_run_at is None


class TestApplyRunResult:
    def test_accumulates_tokens(self):
        state = make_state(total_tokens_used=5000)
        result = make_run_result(input_tokens=1000, output_tokens=500, cache_read_tokens=100)
        new_state = apply_run_result(state, result)
        assert new_state.total_tokens_used == 5000 + 1000 + 500 + 100

    def test_accumulates_cost(self):
        state = make_state(total_cost_usd=1.50)
        result = make_run_result(cost_usd=0.25)
        new_state = apply_run_result(state, result)
        assert abs(new_state.total_cost_usd - 1.75) < 0.001

    def test_increments_run_count(self):
        state = make_state(run_count=3)
        result = make_run_result()
        new_state = apply_run_result(state, result)
        assert new_state.run_count == 4

    def test_sets_last_run_at(self):
        state = make_state()
        result = make_run_result()
        new_state = apply_run_result(state, result)
        assert new_state.last_run_at is not None

    def test_original_state_is_unchanged(self):
        state = make_state(total_tokens_used=1000)
        apply_run_result(state, make_run_result())
        assert state.total_tokens_used == 1000

    def test_skips_failed_runs(self):
        state = make_state(total_tokens_used=0, run_count=0)
        result = make_run_result(success=False, input_tokens=999, cost_usd=0.99)
        new_state = apply_run_result(state, result)
        assert new_state.total_tokens_used == 0
        assert new_state.run_count == 0


class TestIsExhausted:
    def test_not_exhausted_with_no_limits(self):
        state = make_state(total_tokens_used=999_999, total_cost_usd=999.0)
        config = make_config()
        assert not is_exhausted(state, config)

    def test_exhausted_when_token_budget_exceeded(self):
        state = make_state(total_tokens_used=500_001)
        config = make_config(budget_tokens=500_000)
        assert is_exhausted(state, config)

    def test_not_exhausted_when_under_token_budget(self):
        state = make_state(total_tokens_used=499_999)
        config = make_config(budget_tokens=500_000)
        assert not is_exhausted(state, config)

    def test_exhausted_when_usd_budget_exceeded(self):
        state = make_state(total_cost_usd=10.01)
        config = make_config(budget_usd=10.0)
        assert is_exhausted(state, config)

    def test_not_exhausted_when_under_usd_budget(self):
        state = make_state(total_cost_usd=9.99)
        config = make_config(budget_usd=10.0)
        assert not is_exhausted(state, config)

    def test_exhausted_when_duration_exceeded(self):
        started = datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc)
        state = make_state(started_at=started, total_cost_usd=0.0, total_tokens_used=0)
        # budget_duration_seconds=3600, but we simulate time passing via a custom now
        config = make_config(budget_duration_seconds=1)
        import time
        time.sleep(0.01)
        # The function checks wall clock, so with 1 second budget and enough time passing it will
        # exhaust. To test deterministically, we pass a custom now_fn:
        assert is_exhausted(state, config, now=datetime(2026, 4, 15, 10, 1, tzinfo=timezone.utc))

    def test_not_exhausted_when_within_duration(self):
        started = datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc)
        state = make_state(started_at=started)
        config = make_config(budget_duration_seconds=7200)
        now = datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc)  # 1 hour later
        assert not is_exhausted(state, config, now=now)

    def test_stops_on_first_limit_reached(self):
        state = make_state(total_tokens_used=500_001, total_cost_usd=1.0)
        config = make_config(budget_tokens=500_000, budget_usd=100.0)
        assert is_exhausted(state, config)
