"""
Tests for the watch command display rendering.
The polling loop itself is kept thin (hard to unit test); we test the pure
render_display function that produces the Rich renderable.
"""

from datetime import datetime, timezone
from typing import Optional

import pytest
from rich.console import Console
from rich.text import Text

from incinerator.schemas import BudgetState, DaemonConfig
from incinerator.watch import render_display, elapsed_from_state


def make_state(
    tokens: int = 12_500,
    cost: float = 0.2341,
    runs: int = 8,
    started_at: Optional[datetime] = None,
) -> BudgetState:
    return BudgetState(
        total_tokens_used=tokens,
        total_cost_usd=cost,
        run_count=runs,
        started_at=started_at or datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
        last_run_at=datetime(2026, 4, 15, 9, 30, tzinfo=timezone.utc),
    )


def make_config(**kwargs) -> DaemonConfig:
    defaults = dict(repo_path="/home/user/myproject", rate_per_hour=12000)
    defaults.update(kwargs)
    return DaemonConfig(**defaults)


def render_to_text(renderable) -> str:
    """Render a Rich renderable to a plain string for assertions."""
    console = Console(width=100, force_terminal=False, no_color=True)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


class TestRenderDisplay:
    def test_shows_token_count(self):
        output = render_to_text(render_display(
            state=make_state(tokens=12_500),
            config=make_config(),
            elapsed_seconds=1800,
            is_running=True,
        ))
        assert "12,500" in output or "12500" in output

    def test_shows_cost(self):
        output = render_to_text(render_display(
            state=make_state(cost=0.2341),
            config=make_config(),
            elapsed_seconds=1800,
            is_running=True,
        ))
        assert "0.2341" in output or "0.23" in output

    def test_shows_run_count(self):
        output = render_to_text(render_display(
            state=make_state(runs=8),
            config=make_config(),
            elapsed_seconds=1800,
            is_running=True,
        ))
        assert "8" in output

    def test_shows_running_status(self):
        output = render_to_text(render_display(
            state=make_state(),
            config=make_config(),
            elapsed_seconds=60,
            is_running=True,
            tick=0,
        ))
        assert "wasting" in output.lower()

    def test_rotates_spinner_frame_every_tick_but_verb_every_three_ticks(self):
        base_kwargs = dict(
            state=make_state(),
            config=make_config(),
            elapsed_seconds=60,
            is_running=True,
        )
        tick_0 = render_to_text(render_display(tick=0, **base_kwargs))
        tick_1 = render_to_text(render_display(tick=1, **base_kwargs))
        tick_2 = render_to_text(render_display(tick=2, **base_kwargs))
        tick_3 = render_to_text(render_display(tick=3, **base_kwargs))

        assert "wasting" in tick_0.lower()
        assert "wasting" in tick_1.lower()
        assert "wasting" in tick_2.lower()
        assert "being annoying" in tick_3.lower()

    def test_shows_stopped_status(self):
        output = render_to_text(render_display(
            state=make_state(),
            config=make_config(),
            elapsed_seconds=60,
            is_running=False,
        ))
        assert "stopped" in output.lower() or "STOPPED" in output

    def test_shows_repo_path(self):
        output = render_to_text(render_display(
            state=make_state(),
            config=make_config(repo_path="/home/user/myproject"),
            elapsed_seconds=60,
            is_running=True,
        ))
        assert "myproject" in output

    def test_shows_tokens_per_hour_rate(self):
        # 3600 tokens in 3600 seconds = 1 token/sec = 3600 tokens/hr
        output = render_to_text(render_display(
            state=make_state(tokens=3600),
            config=make_config(),
            elapsed_seconds=3600,
            is_running=True,
        ))
        assert "3,600" in output or "3600" in output  # rate appears somewhere

    def test_shows_token_budget_progress_when_set(self):
        output = render_to_text(render_display(
            state=make_state(tokens=25_000),
            config=make_config(budget_tokens=100_000),
            elapsed_seconds=600,
            is_running=True,
        ))
        # Should show something like "12,000 / 100,000" or a percentage
        assert "100,000" in output or "100000" in output or "25%" in output

    def test_shows_usd_budget_progress_when_set(self):
        output = render_to_text(render_display(
            state=make_state(cost=2.50),
            config=make_config(budget_usd=10.0),
            elapsed_seconds=600,
            is_running=True,
        ))
        assert "10" in output  # budget ceiling visible

    def test_shows_no_budget_message_when_no_limits(self):
        output = render_to_text(render_display(
            state=make_state(),
            config=make_config(),  # no budget_tokens, budget_usd, budget_duration_seconds
            elapsed_seconds=600,
            is_running=True,
        ))
        # Should render without crashing and show something sensible
        assert len(output.strip()) > 0

    def test_shows_elapsed_time(self):
        output = render_to_text(render_display(
            state=make_state(),
            config=make_config(),
            elapsed_seconds=3661,  # 1h 1m 1s
            is_running=True,
        ))
        # Some representation of the elapsed time should appear
        assert "1h" in output or "01:01" in output or "3661" in output or "1:01" in output

    def test_renders_with_zero_state(self):
        # Should not crash on initial empty state
        state = BudgetState(
            total_tokens_used=0,
            total_cost_usd=0.0,
            run_count=0,
            started_at=datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
        )
        output = render_to_text(render_display(
            state=state,
            config=make_config(),
            elapsed_seconds=0,
            is_running=True,
        ))
        assert len(output.strip()) > 0

    def test_returns_rich_renderable(self):
        result = render_display(
            state=make_state(),
            config=make_config(),
            elapsed_seconds=60,
            is_running=True,
        )
        console = Console(width=100, force_terminal=False, no_color=True)
        with console.capture():
            console.print(result)  # should not raise

    def test_shows_next_run_countdown_when_statistical(self):
        from datetime import datetime, timedelta, timezone
        next_run = datetime.now(tz=timezone.utc) + timedelta(seconds=90)
        state = make_state()
        state = state.model_copy(update={"next_run_at": next_run})
        output = render_to_text(render_display(
            state=state,
            config=make_config(statistical=True),
            elapsed_seconds=60,
            is_running=True,
        ))
        assert "next run" in output.lower()

    def test_shows_steady_mode_when_not_statistical(self):
        output = render_to_text(render_display(
            state=make_state(),
            config=make_config(statistical=False),
            elapsed_seconds=60,
            is_running=True,
        ))
        assert "steady" in output.lower()

    def test_elapsed_from_state_reflects_session_start(self):
        started = datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc)
        state = BudgetState(
            total_tokens_used=0,
            total_cost_usd=0.0,
            run_count=0,
            started_at=started,
        )
        # Simulate "now" is 1 hour after session start
        fake_now = datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc)
        elapsed = elapsed_from_state(state, now=fake_now)
        assert abs(elapsed - 3600) < 1

    def test_next_run_shows_now_when_past_due(self):
        from datetime import datetime, timedelta, timezone
        past = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        state = make_state()
        state = state.model_copy(update={"next_run_at": past})
        output = render_to_text(render_display(
            state=state,
            config=make_config(statistical=True),
            elapsed_seconds=60,
            is_running=True,
        ))
        assert "now" in output.lower()
